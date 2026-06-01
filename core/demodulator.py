# core/demodulator.py
# Direkte RTL-SDR-Anbindung via pyrtlsdr (persistent USB, I2C-Retune ~10 ms)
# Ersetzt rtl_fm-Subprocess: kein 200-300 ms USB-Open/Close pro Kanalwechsel mehr.

import glob
import math
import os
import subprocess
import threading
import time
import logging
from typing import Callable, Optional

import numpy as np
from scipy import signal as sp_signal

try:
    import rtlsdr
    _PYRTLSDR_OK = True
except ImportError:
    _PYRTLSDR_OK = False

import config.settings as cfg

log = logging.getLogger(__name__)


class Demodulator:
    """
    Direkte RTL-SDR-Anbindung via pyrtlsdr.
    USB-Gerät bleibt zwischen Kanalwechseln offen; Retune via I2C (~10 ms statt
    ~300 ms mit rtl_fm). Demodulation (NFM/FM/WFM/AM) und LPF in Python/numpy.
    """

    CAPTURE_RATE = 240_000   # IQ-Abtastrate Hz  (ganzzahliges Vielfaches von 48 kHz)
    OUTPUT_RATE  =  48_000   # Audio-Ausgaberate Hz
    DECIMATE     =       5   # 240 000 / 48 000
    CHUNK        =   8_000   # IQ-Samples pro Read (≈ 33 ms, 8000/5=1600 exakt)
    SKIP_BLOCKS  =       2   # Blöcke nach Retune verwerfen (PLL-Einschwingen)

    def __init__(
        self,
        audio_callback: Callable[[bytes], None],
        rssi_callback:  Callable[[float], None],
        on_unexpected_exit: Optional[Callable[[], None]] = None,
    ):
        self._audio_cb = audio_callback
        self._rssi_cb  = rssi_callback
        self._on_unexpected_exit = on_unexpected_exit

        self._sdr: Optional["rtlsdr.RtlSdr"] = None
        self._stream_thread: Optional[threading.Thread] = None
        self._running = False
        self.dongle_ok: bool = False

        self._freq: int = 100_000_000   # Platzhalter bis start() aufgerufen wird
        self._mode: str = "NFM"
        self._gain = None

        self._skip_blocks: int = 0
        self._zi_lpf: Optional[np.ndarray] = None
        self._zi_deemph: Optional[np.ndarray] = None

        # Retune wird vom Stream-Thread nach dem laufenden Bulk-Read ausgeführt,
        # nicht direkt aus start() – vermeidet gleichzeitigen USB-Zugriff.
        self._retune_needed: bool = False

        self._lock = threading.Lock()
        self._filters = self._build_filters()

        # Verwaiste rtl_fm-Prozesse vom letzten Absturz beseitigen
        try:
            if subprocess.run(["pgrep", "-x", "rtl_fm"],
                              capture_output=True).returncode == 0:
                subprocess.run(["pkill", "-x", "rtl_fm"], capture_output=True)
                time.sleep(0.5)
                log.info("Verwaiste rtl_fm-Prozesse beendet")
        except Exception:
            pass

        if not _PYRTLSDR_OK:
            log.error("pyrtlsdr nicht installiert – bitte: pip install pyrtlsdr")
            return

        self._open_device()

    # ── Filter-Design ─────────────────────────────────────────────────────────

    @staticmethod
    def _build_filters() -> dict:
        """
        Butterworth-LPF (Ordnung 4) pro Modus bei CAPTURE_RATE – wirkt als
        kombinierter Tiefpass + Anti-Aliasing-Filter vor der Dezimierung.
        De-Emphasis 50 µs (IEC/Europa) für WFM bei OUTPUT_RATE.
        """
        fs = 240_000
        nyq = fs / 2.0
        filters = {}
        for mode, cutoff in [
            ("NFM",  4_000),
            ("FM",   8_000),
            ("WFM", 75_000),
            ("AM",   4_000),
        ]:
            filters[mode] = sp_signal.butter(4, cutoff / nyq, btype="low", output="sos")
        # De-Emphasis: H(z) = (1−a) / (1 − a·z⁻¹),  a = exp(−1 / (fs·τ))
        tau = 50e-6
        a = np.exp(-1.0 / (48_000 * tau))
        filters["deemph"] = np.array([[1.0 - a, 0.0, 0.0, 1.0, -a, 0.0]])
        return filters

    # ── Gerät öffnen / schließen ───────────────────────────────────────────────

    def _open_device(self):
        try:
            sdr = rtlsdr.RtlSdr(device_index=cfg.RTL_DEVICE_INDEX)
            sdr.sample_rate = self.CAPTURE_RATE
            if cfg.RTL_PPM_CORRECTION != 0:
                sdr.set_freq_correction(cfg.RTL_PPM_CORRECTION)
            sdr.center_freq = self._freq
            self._apply_gain(sdr, self._gain)
            self._sdr = sdr
            self._running = True
            self._skip_blocks = self.SKIP_BLOCKS
            self._stream_thread = threading.Thread(
                target=self._stream_loop, daemon=True, name="demod-iq"
            )
            self._stream_thread.start()
            log.info("RTL-SDR geöffnet (pyrtlsdr, %d kHz, PPM=%+d)",
                     self.CAPTURE_RATE // 1000, cfg.RTL_PPM_CORRECTION)
        except Exception as e:
            log.error("RTL-SDR konnte nicht geöffnet werden: %s", e)
            self._sdr = None
            self.dongle_ok = False

    @staticmethod
    def _apply_gain(sdr: "rtlsdr.RtlSdr", gain) -> None:
        if gain is None or gain == "auto":
            sdr.gain = "auto"
        else:
            try:
                sdr.gain = float(int(gain)) / 10.0   # Zehntel-dB → dB
            except (ValueError, TypeError):
                sdr.gain = "auto"

    # ── Öffentliche API ───────────────────────────────────────────────────────

    def start(self, freq: int, mode: str, squelch_db: int, gain=None):
        """
        Abstimmen auf neue Frequenz / Modus.
        USB-Gerät bleibt offen; nur I2C-Retune via librtlsdr (~10 ms).
        War das Gerät geschlossen (nach close()), wird es neu geöffnet.
        """
        if not _PYRTLSDR_OK:
            return

        if self._sdr is None:
            self._freq = freq
            self._mode = mode
            self._gain = gain
            self._open_device()
            return

        with self._lock:
            self._freq = freq
            self._mode = mode
            self._gain = gain
            self._zi_lpf    = None   # Filterzustand zurücksetzen
            self._zi_deemph = None
            self._skip_blocks = self.SKIP_BLOCKS
            # Retune wird vom Stream-Thread nach dem laufenden read_samples() ausgeführt.
            # Direkter Aufruf von sdr.center_freq aus einem anderen Thread würde mit dem
            # laufenden libusb-Bulk-Transfer kollidieren und blockieren oder ihn stören.
            self._retune_needed = True

    def stop(self) -> bool:
        """
        No-op: USB-Gerät bleibt offen für schnelles I2C-Retune.
        Gibt immer True zurück (Kompatibilität mit scanner._tune()).
        """
        return True

    def apply_ppm(self, ppm: int) -> None:
        """Setzt PPM-Korrektur live ohne Geräte-Neustart."""
        if ppm == 0:
            return
        with self._lock:
            sdr = self._sdr
        if sdr is not None:
            try:
                sdr.set_freq_correction(ppm)
                log.info("PPM-Korrektur auf %+d gesetzt", ppm)
            except Exception as e:
                log.error("PPM-Korrektur fehlgeschlagen: %s", e)

    def close(self):
        """
        Schließt das USB-Gerät vollständig.
        Wird von scanner.stop() und vor der PPM-Kalibrierung aufgerufen.
        """
        self._running = False
        sdr, self._sdr = self._sdr, None
        if sdr is not None:
            try:
                sdr.close()   # unterbricht blockierendes read_samples()
            except Exception:
                pass
        if self._stream_thread and self._stream_thread.is_alive():
            self._stream_thread.join(timeout=2.0)
        self._stream_thread = None
        self.dongle_ok = False
        log.info("RTL-SDR geschlossen")

    # ── IQ-Stream und Demodulation ────────────────────────────────────────────

    def _stream_loop(self):
        _t_prev = time.monotonic()
        while self._running:
            sdr = self._sdr
            if sdr is None:
                break
            try:
                iq = sdr.read_samples(self.CHUNK)   # blockiert ~33 ms
            except Exception as e:
                if self._running:
                    log.error("IQ-Lesefehler: %s", e)
                    self.dongle_ok = False
                    if self._on_unexpected_exit:
                        self._on_unexpected_exit()
                    time.sleep(0.5)
                break

            _t_read_done = time.monotonic()

            if not self._running:
                break

            # Retune hier ausführen – Bulk-Transfer ist abgeschlossen, USB-Bus frei.
            # Lock nur kurz für State-Lesen; sdr.center_freq außerhalb des Locks.
            with self._lock:
                do_retune   = self._retune_needed
                retune_freq = self._freq
                retune_gain = self._gain
                if do_retune:
                    self._retune_needed = False
                mode = self._mode
                skip = self._skip_blocks
                if skip > 0:
                    self._skip_blocks -= 1

            if do_retune:
                try:
                    self._apply_gain(sdr, retune_gain)
                    sdr.center_freq = retune_freq
                except Exception as e:
                    if self._running:
                        log.error("Retune auf %d Hz fehlgeschlagen: %s", retune_freq, e)
                        self.dongle_ok = False
                        if self._on_unexpected_exit:
                            self._on_unexpected_exit()
                    break

            if skip > 0:
                self._rssi_cb(-120.0)
                _t_prev = time.monotonic()
                continue

            try:
                audio     = self._demodulate(iq, mode)         # bei CAPTURE_RATE
                audio_dec = audio[:: self.DECIMATE]             # → OUTPUT_RATE

                if mode == "WFM":
                    audio_dec = self._deemphasis(audio_dec)

                pcm = (np.clip(audio_dec, -1.0, 1.0) * 32767).astype(np.int16)

                # RSSI: IQ-Trägerleistung in dBFS (stabil, modusneutral).
                # Typische Werte: Rauschboden −30 bis −25 dBFS, Signal −20 bis −5 dBFS.
                # SQUELCH_DEFAULT in settings.py muss zur Zielantenne/Hardware kalibriert werden.
                power = float(np.mean(np.abs(iq) ** 2))
                rssi  = 10.0 * math.log10(max(power, 1e-12))
                self._rssi_cb(rssi)
                self._audio_cb(pcm.tobytes())
                self.dongle_ok = True

            except Exception as e:
                log.debug("Demodulations-Fehler: %s", e)
                self._rssi_cb(-120.0)

            _t_now = time.monotonic()
            _proc_ms  = (_t_now - _t_read_done) * 1000
            _total_ms = (_t_now - _t_prev) * 1000
            if _total_ms > 60:
                log.warning("Langsamer Chunk: gesamt=%.0f ms  verarbeitung=%.0f ms",
                            _total_ms, _proc_ms)
            _t_prev = _t_now

    def _demodulate(self, iq: np.ndarray, mode: str) -> np.ndarray:
        """
        Demoduliert IQ zu Audio bei CAPTURE_RATE, normiert auf ±1.0 Vollaussteuerung.

        FM-Diskriminator: np.angle(iq[n] · iq*[n−1]) gibt die instantane Phasendifferenz
        in Radian. Division durch π normiert auf ±1.0 für maximale Phasendifferenz.
        Bei NFM-Standardhub ±2,5 kHz / 240 kHz ergibt das ~2 % Aussteuerung → passt zu
        AUDIO_SOFT_GAIN × 20 → ~40 % Nutzpegel (Sprachverständlichkeit).
        WFM (±75 kHz) ergibt ~62 % Aussteuerung – Clipping am Gain-Stufe ist erwartet.

        AM: Hüllkurven-Detektor (|IQ|) mit DC-Entfernung.
        """
        sos = self._filters.get(mode, self._filters["NFM"])

        if mode == "AM":
            audio = np.abs(iq).astype(np.float32)
            audio -= np.mean(audio)
        else:
            conj_prod = iq[1:] * np.conj(iq[:-1])
            diff = np.angle(conj_prod).astype(np.float32)
            audio = np.append(diff, diff[-1] if len(diff) else 0.0)
            audio /= np.pi   # normiert auf ±1.0

        # LPF + Anti-Aliasing (Zustand über Chunks hinweg beibehalten → keine Knackser)
        if self._zi_lpf is None:
            zi0 = sp_signal.sosfilt_zi(sos)
            self._zi_lpf = zi0 * float(audio[0])
        audio, self._zi_lpf = sp_signal.sosfilt(sos, audio, zi=self._zi_lpf)

        return audio

    def _deemphasis(self, audio: np.ndarray) -> np.ndarray:
        """50 µs IIR-De-Emphasis bei OUTPUT_RATE (nur für WFM)."""
        sos = self._filters["deemph"]
        if self._zi_deemph is None:
            zi0 = sp_signal.sosfilt_zi(sos)
            self._zi_deemph = zi0 * float(audio[0])
        audio, self._zi_deemph = sp_signal.sosfilt(sos, audio, zi=self._zi_deemph)
        return audio

    # ── USB-Reset ─────────────────────────────────────────────────────────────

    @staticmethod
    def usb_reset() -> bool:
        """USB-Reset des RTL-SDR via sysfs (braucht Root oder udev-Regel)."""
        rtl_pids = {"2832", "2838", "2848", "2849"}
        for vendor_path in glob.glob("/sys/bus/usb/devices/*/idVendor"):
            try:
                with open(vendor_path) as f:
                    if f.read().strip() != "0bda":
                        continue
                pid_path = vendor_path.replace("idVendor", "idProduct")
                with open(pid_path) as f:
                    if f.read().strip() not in rtl_pids:
                        continue
                auth_path = os.path.join(os.path.dirname(vendor_path), "authorized")
                log.info("USB-Reset RTL-SDR: %s", os.path.dirname(vendor_path))
                with open(auth_path, "w") as f:
                    f.write("0")
                time.sleep(0.5)
                with open(auth_path, "w") as f:
                    f.write("1")
                time.sleep(1.5)
                return True
            except PermissionError:
                log.warning("USB-Reset: keine Root-Rechte – udev-Regel oder root nötig")
                return False
            except Exception as e:
                log.debug("USB-Reset Fehler: %s", e)
        log.warning("USB-Reset: RTL-SDR nicht in /sys/bus/usb/devices gefunden")
        return False

    # ── Kompatibilitäts-Shim ──────────────────────────────────────────────────

    @property
    def pid(self) -> Optional[int]:
        return None   # kein Subprocess mehr

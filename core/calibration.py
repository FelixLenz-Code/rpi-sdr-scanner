# core/calibration.py
# Automatische PPM-Frequenzkorrektur via kalibrate_rtl_sdr oder manuellem Sweep.

import os
import subprocess
import re
import time
import logging
import threading
from typing import Callable, Optional

import config.settings as cfg

log = logging.getLogger(__name__)

# Regex für kalibrate_rtl_sdr Ausgabe: "ppm error: -8.103"
_PPM_RE = re.compile(r"ppm\s+error[:\s]+([+-]?\d+(?:\.\d+)?)", re.IGNORECASE)
# Alternativ: "average error: -7.9 ppm"
_PPM_RE2 = re.compile(r"([+-]?\d+(?:\.\d+)?)\s*ppm", re.IGNORECASE)


class CalibrationResult:
    def __init__(self, ppm: float, method: str, duration: float):
        self.ppm      = ppm
        self.method   = method
        self.duration = duration
        self.ts       = time.time()

    def __str__(self):
        return (f"Kalibrierung ({self.method}): {self.ppm:+.1f} ppm "
                f"in {self.duration:.1f}s")


class Calibrator:
    """
    Führt eine PPM-Kalibrierung durch und schreibt das Ergebnis
    zurück in config/settings.py (RTL_PPM_CORRECTION).

    Methoden:
      1. kalibrate_rtl_sdr  – nutzt GSM-Baken (empfohlen, braucht Paket)
      2. manual_sweep       – misst bekannte Frequenz, schätzt Abweichung
    """

    def __init__(self, progress_cb: Optional[Callable[[str], None]] = None):
        self._progress = progress_cb or (lambda msg: log.info(msg))
        self.result: Optional[CalibrationResult] = None
        self._running = False

    # ── Öffentliche API ───────────────────────────────────────────────────────

    def run_auto(self, band: str = "GSM900") -> Optional[CalibrationResult]:
        """
        Versucht kalibrate_rtl_sdr, fällt auf manuellen Sweep zurück.
        Blockiert – in einem Thread aufrufen.
        """
        self._running = True
        t0 = time.monotonic()
        self._progress(f"Starte Kalibrierung mit kalibrate_rtl_sdr ({band})…")

        result = self._try_kalibrate(band)
        if result is None:
            self._progress("kalibrate_rtl_sdr nicht verfügbar – manueller Sweep…")
            result = self._manual_sweep()

        if result:
            self.result = result
            self._progress(str(result))
        self._running = False
        return result

    def run_in_background(self, band: str = "GSM900",
                          done_cb: Optional[Callable[[Optional[CalibrationResult]], None]] = None):
        """Nicht-blockierende Variante."""
        def _worker():
            res = self.run_auto(band)
            if done_cb:
                done_cb(res)

        t = threading.Thread(target=_worker, daemon=True, name="calibration")
        t.start()

    def stop(self):
        self._running = False

    # ── Methode 1: kalibrate_rtl_sdr ─────────────────────────────────────────

    # Regex für "chan: 42 (935.2MHz ...)\tpower: 185025.89"
    _CHAN_RE  = re.compile(r"chan:\s*(\d+).*?power:\s*([\d.]+)")
    # Regex für "average absolute error: -2.6 ppm"
    _ERR_RE   = re.compile(r"average absolute error:\s*([+-]?\d+(?:\.\d+)?)\s*ppm", re.I)

    # Binär-Namen in Suchreihenfolge
    _KAL_BINS = ("kal", "kalibrate_rtl_sdr", "kalibrate-rtl")

    def _kal_bin(self) -> Optional[str]:
        import shutil
        for name in self._KAL_BINS:
            if shutil.which(name):
                return name
        return None

    def _try_kalibrate(self, band: str) -> Optional[CalibrationResult]:
        binary = self._kal_bin()
        if binary is None:
            return None

        t0 = time.monotonic()

        # Schritt 1: Scan – stärksten GSM-Kanal finden
        scan_band = {
            "GSM900": "GSM900", "GSM1800": "DCS", "UMTS": "GSM900",
        }.get(band, "GSM900")

        self._progress(f"Scanne {scan_band}-Band nach GSM-Kanälen…")
        scan_out = self._run_kal([binary, "-s", scan_band, "-d", str(cfg.RTL_DEVICE_INDEX)])
        if scan_out is None:
            return None

        best_chan, best_power = None, -1.0
        for line in scan_out.splitlines():
            m = self._CHAN_RE.search(line)
            if m:
                chan, power = int(m.group(1)), float(m.group(2))
                self._progress(f"  Kanal {chan}: {power:.0f}")
                if power > best_power:
                    best_power, best_chan = power, chan

        if best_chan is None:
            self._progress("Keine GSM-Kanäle gefunden")
            return None

        self._progress(f"Messe PPM auf Kanal {best_chan}…")

        # Schritt 2: PPM-Messung auf dem stärksten Kanal
        meas_out = self._run_kal([binary, "-c", str(best_chan), "-d", str(cfg.RTL_DEVICE_INDEX)])
        if meas_out is None:
            return None

        for line in meas_out.splitlines():
            self._progress(f"  {line.strip()}")
            m = self._ERR_RE.search(line)
            if m:
                ppm = float(m.group(1))
                return CalibrationResult(ppm, binary, time.monotonic() - t0)

        self._progress("PPM-Wert nicht lesbar")
        return None

    def _run_kal(self, cmd: list) -> Optional[str]:
        """Führt kal aus, gibt stdout+stderr als String zurück oder None bei Fehler."""
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except FileNotFoundError:
            return None

        lines = []
        try:
            for line in proc.stdout:
                if not self._running:
                    proc.terminate()
                    return None
                lines.append(line)
            proc.wait(timeout=60)
        except Exception as e:
            log.debug("kal Lesefehler: %s", e)
            proc.kill()
            return None

        return "".join(lines)

    # ── Methode 2: Manueller Sweep ────────────────────────────────────────────

    def _manual_sweep(self) -> Optional[CalibrationResult]:
        """
        Einfache Methode: Empfängt einen bekannten CW-Sender (z.B. DCF77 77.5 kHz
        oder eine FM-Station) und misst den Frequenzversatz im Spektrum.

        Vereinfachung: Hier nutzen wir rtl_power um das Spektrum rund um eine
        bekannte FM-Frequenz zu scannen und suchen den Peak.
        """
        # Bekannte starke FM-Station als Referenz (NDR Info / DLF in DE)
        # Anpassen an lokale starke Sender!
        ref_freq = 90_300_000   # Hz, lokale starke FM-Station
        span     = 200_000      # ±100 kHz Sweep

        self._progress(f"Manueller Sweep um {ref_freq/1e6:.1f} MHz …")
        t0 = time.monotonic()

        cmd = [
            "rtl_power",
            "-d", str(cfg.RTL_DEVICE_INDEX),
            "-f", f"{ref_freq - span//2}:{ref_freq + span//2}:1000",
            "-g", "20",
            "-i", "2",    # 2 Sekunden messen
            "-1",          # einmaliger Sweep
            "-",
        ]
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL,
                                          timeout=10, text=True)
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError,
                FileNotFoundError) as e:
            log.warning("rtl_power Fehler: %s", e)
            return None

        # CSV parsen: date, time, freq_lo, freq_hi, freq_step, samples, db...
        peak_freq = None
        peak_db   = -999.0
        for line in out.splitlines():
            parts = line.split(",")
            if len(parts) < 7:
                continue
            try:
                freq_lo   = float(parts[2])
                freq_step = float(parts[4])
                dbs       = [float(v) for v in parts[6:] if v.strip()]
                for i, db in enumerate(dbs):
                    f = freq_lo + i * freq_step
                    if db > peak_db:
                        peak_db   = db
                        peak_freq = f
            except (ValueError, IndexError):
                continue

        if peak_freq is None:
            return None

        error_hz  = peak_freq - ref_freq
        ppm       = (error_hz / ref_freq) * 1e6
        duration  = time.monotonic() - t0
        self._progress(
            f"Peak bei {peak_freq/1e6:.4f} MHz, Versatz {error_hz:+.0f} Hz → {ppm:+.2f} ppm"
        )
        return CalibrationResult(round(ppm, 1), "manual_sweep", duration)

    # ── Ergebnis in settings.py schreiben ────────────────────────────────────

    @staticmethod
    def apply_to_settings(
        ppm: float,
        settings_path: str = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config", "settings.py",
        ),
        demod=None,
    ):
        """
        Überschreibt RTL_PPM_CORRECTION in settings.py und aktualisiert
        den laufenden Demodulator live (falls übergeben).
        Macht ein Backup als settings.py.bak.
        """
        ppm_int = int(round(ppm))
        try:
            with open(settings_path, "r") as f:
                content = f.read()

            import shutil
            shutil.copy(settings_path, settings_path + ".bak")

            new_content = re.sub(
                r"^(RTL_PPM_CORRECTION\s*=\s*)[-+]?\d+(?:\.\d+)?",
                f"\\g<1>{ppm_int}",
                content,
                flags=re.MULTILINE,
            )
            with open(settings_path, "w") as f:
                f.write(new_content)

            cfg.RTL_PPM_CORRECTION = ppm_int
            log.info("PPM-Korrektur gesetzt: %+d ppm (in %s)", ppm_int, settings_path)
        except Exception as e:
            log.error("Konnte settings.py nicht aktualisieren: %s", e)
            return

        if demod is not None:
            demod.apply_ppm(ppm_int)

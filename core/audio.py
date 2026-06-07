# core/audio.py
# PCM-Ausgabe über PyAudio (Callback-Modell, pull-basiert, kein Drift).
# Fallback auf aplay wenn PyAudio nicht verfügbar.

import subprocess
import threading
import logging
import queue

import numpy as np

import config.settings as cfg

log = logging.getLogger(__name__)

# Passt zu Demodulator: CHUNK 8000 / DECIMATE 5 = 1600 Samples pro Chunk
_FRAMES_PER_BUFFER = 1600


class AudioPipeline:
    """
    Nimmt rohe 16-bit PCM-Mono-Samples entgegen und gibt sie aus.
    PyAudio-Callback: Hardware ruft uns genau zum richtigen Zeitpunkt ab —
    keine Underruns durch Python-Overhead möglich.
    """

    _FIR_TAPS    = 64
    _FADE_SAMPLES = 1920  # 40 ms Einblend-Rampe beim Squelch-Öffnen

    @staticmethod
    def _design_lpf(cutoff_hz: int, sample_rate: int = 48000) -> np.ndarray:
        n = np.arange(AudioPipeline._FIR_TAPS) - (AudioPipeline._FIR_TAPS - 1) / 2
        fc = cutoff_hz / sample_rate
        h = np.where(n == 0, 2 * fc, np.sin(2 * np.pi * fc * n) / (np.pi * n))
        h *= np.hanning(AudioPipeline._FIR_TAPS)
        return (h / h.sum()).astype(np.float32)

    def __init__(self):
        self._volume: int = cfg.VOLUME_DEFAULT
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=40)
        self._pa = None
        self._pa_stream = None
        self._proc: subprocess.Popen | None = None
        self._writer: threading.Thread | None = None
        self.running = False
        self._squelched: bool = True
        self._fade_in: int = 0
        self._fade_out: int = 0
        self._comp_env: float = 0.0
        self.comp_enabled: bool = True
        self.channel_gain: float | None = None
        self._lpf: np.ndarray | None = None
        self._lpf_history: np.ndarray = np.zeros(0)

    # ── Starten ───────────────────────────────────────────────────────────────

    def start(self):
        self.stop()
        self.running = True
        if not self._start_pyaudio():
            self._start_aplay()
        self.set_volume(self._volume)

    def _start_pyaudio(self) -> bool:
        try:
            import pyaudio as _pa

            pa = _pa.PyAudio()
            self._pa = pa

            _prev_out = bytes(_FRAMES_PER_BUFFER * 2)   # PLC: letzter guter Output

            def _cb(in_data, frame_count, time_info, status):
                nonlocal _prev_out

                # ── Stille: Squelch zu UND Fade abgeschlossen ─────────────────
                if self._squelched and self._fade_out == 0:
                    try:
                        while True:
                            self._queue.get_nowait()
                    except queue.Empty:
                        pass
                    return (bytes(frame_count * 2), _pa.paContinue)

                # ── Daten holen ───────────────────────────────────────────────
                try:
                    raw = self._queue.get_nowait()
                except queue.Empty:
                    if self._fade_out > 0:
                        # Squelch gerade geschlossen, feed() liefert nichts mehr →
                        # Fade auf letztem bekannten Audio ausführen (kein PLC-Loop).
                        raw = _prev_out
                    else:
                        # Squelch offen, kurzer Queue-Leerstand → PLC (unhörbar).
                        return (_prev_out, _pa.paContinue)

                # ── Verarbeitung ──────────────────────────────────────────────
                samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32)

                if self._fade_out > 0:
                    n = min(self._fade_out, len(samples))
                    start_amp = self._fade_out / self._FADE_SAMPLES
                    end_amp   = max(0.0, (self._fade_out - n) / self._FADE_SAMPLES)
                    samples[:n] *= np.linspace(start_amp, end_amp, n, dtype=np.float32)
                    self._fade_out = max(0, self._fade_out - n)
                    if self._fade_out == 0 and n < len(samples):
                        samples[n:] = 0.0

                if self._fade_in > 0:
                    n = min(self._fade_in, len(samples))
                    samples[:n] *= np.linspace(0.0, 1.0, n, endpoint=False, dtype=np.float32)
                    self._fade_in -= n

                gain = self.channel_gain if self.channel_gain is not None else cfg.AUDIO_SOFT_GAIN
                if gain != 1.0:
                    samples = samples * gain

                if self.comp_enabled and cfg.AUDIO_COMP_THRESHOLD > 0:
                    rms = float(np.sqrt(np.mean(samples ** 2))) + 1e-6
                    if rms > self._comp_env:
                        self._comp_env = self._comp_env * 0.5 + rms * 0.5
                    else:
                        self._comp_env = self._comp_env * 0.92 + rms * 0.08
                    if self._comp_env > cfg.AUDIO_COMP_THRESHOLD:
                        comp_gain = (cfg.AUDIO_COMP_THRESHOLD / self._comp_env) ** (
                            1.0 - 1.0 / cfg.AUDIO_COMP_RATIO)
                        samples = samples * comp_gain
                    samples = samples * cfg.AUDIO_COMP_MAKEUP

                if cfg.AUDIO_GATE_THRESHOLD > 0:
                    rms = float(np.sqrt(np.mean(samples ** 2))) + 1e-6
                    if rms < cfg.AUDIO_GATE_THRESHOLD:
                        samples = samples * (rms / cfg.AUDIO_GATE_THRESHOLD) ** 2

                out = np.clip(samples, -32768, 32767).astype(np.int16).tobytes()
                out_len = frame_count * 2
                if len(out) < out_len:
                    out += bytes(out_len - len(out))
                out = out[:out_len]
                if not self._squelched:
                    _prev_out = out   # nur gültige Signalchunks für PLC merken
                return (out, _pa.paContinue)

            # PulseAudio-Device bevorzugen (ermöglicht Sink-Wechsel für BT-Audio)
            pulse_idx = None
            for i in range(pa.get_device_count()):
                d = pa.get_device_info_by_host_api_type_and_index(0, i) if False else \
                    pa.get_device_info_by_index(i)
                if d.get('maxOutputChannels', 0) > 0 and 'pulse' in d.get('name', '').lower():
                    pulse_idx = i
                    break

            stream = pa.open(
                format=_pa.paInt16,
                channels=1,
                rate=cfg.AUDIO_RATE,
                output=True,
                output_device_index=pulse_idx,
                frames_per_buffer=_FRAMES_PER_BUFFER,
                stream_callback=_cb,
            )
            stream.start_stream()
            self._pa_stream = stream
            log.info("PyAudio-Stream geöffnet (%d kHz, %d frames/buf)",
                     cfg.AUDIO_RATE // 1000, _FRAMES_PER_BUFFER)
            return True

        except Exception as e:
            log.warning("PyAudio nicht verfügbar (%s) – Fallback auf aplay", e)
            if self._pa:
                try:
                    self._pa.terminate()
                except Exception:
                    pass
                self._pa = None
            return False

    def _start_aplay(self):
        cmd = [
            "aplay",
            "-r", str(cfg.AUDIO_RATE),
            "-f", "S16_LE",
            "-c", "1",
            "-D", "pulse",
            "-B", "500000",
            "-F", "100000",
            "-",
        ]
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
            threading.Thread(
                target=self._stderr_loop, args=(self._proc,),
                daemon=True, name="aplay-stderr",
            ).start()
        except FileNotFoundError:
            log.warning("aplay nicht gefunden – Audio-Ausgabe deaktiviert")
            self._proc = None
        self._writer = threading.Thread(
            target=self._write_loop, daemon=True, name="audio-writer"
        )
        self._writer.start()
        log.info("aplay-Fallback gestartet")

    # ── Stoppen ───────────────────────────────────────────────────────────────

    def stop(self):
        self.running = False
        if self._pa_stream:
            try:
                self._pa_stream.stop_stream()
                self._pa_stream.close()
            except Exception:
                pass
            self._pa_stream = None
        if self._pa:
            try:
                self._pa.terminate()
            except Exception:
                pass
            self._pa = None
        if self._proc:
            try:
                self._proc.stdin.close()
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:
                pass
            self._proc = None

    # ── Squelch-Steuerung ─────────────────────────────────────────────────────

    @property
    def squelched(self) -> bool:
        return self._squelched

    @squelched.setter
    def squelched(self, value: bool):
        if value == self._squelched:
            return
        if value:
            self._fade_out = self._FADE_SAMPLES
            self._comp_env = 0.0
        else:
            self._fade_in  = self._FADE_SAMPLES
            self._fade_out = 0
            if self._lpf is not None:
                self._lpf_history = np.zeros(self._FIR_TAPS - 1, dtype=np.float32)
        self._squelched = value

    # ── Tiefpass konfigurieren ────────────────────────────────────────────────

    def set_lpf(self, cutoff_hz: int | None):
        if cutoff_hz is None:
            self._lpf = None
            self._lpf_history = np.zeros(0)
        else:
            self._lpf = self._design_lpf(cutoff_hz)
            self._lpf_history = np.zeros(self._FIR_TAPS - 1, dtype=np.float32)

    # ── Samples einspeisen (Stream-Thread) ────────────────────────────────────

    def feed(self, data: bytes):
        """Vom Demodulator aufgerufen – nur Queue-Put, keine numpy-Verarbeitung."""
        if self._squelched:
            return
        try:
            self._queue.put_nowait(data)
        except queue.Full:
            pass

    # ── aplay-Fallback-Loop ───────────────────────────────────────────────────

    @staticmethod
    def _stderr_loop(proc: subprocess.Popen):
        try:
            for line in proc.stderr:
                msg = line.decode(errors="replace").rstrip()
                if msg:
                    log.warning("aplay: %s", msg)
        except Exception:
            pass

    def _write_loop(self):
        """Fallback-Loop wenn PyAudio nicht verfügbar ist."""
        import time as _t
        _silence = bytes(self._FADE_SAMPLES * 2)
        while self.running:
            try:
                data = self._queue.get(timeout=0.10)
            except queue.Empty:
                data = _silence

            if self._fade_out > 0:
                samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                n = min(self._fade_out, len(samples))
                start_amp = self._fade_out / self._FADE_SAMPLES
                end_amp   = max(0.0, (self._fade_out - n) / self._FADE_SAMPLES)
                samples[:n] *= np.linspace(start_amp, end_amp, n, dtype=np.float32)
                self._fade_out = max(0, self._fade_out - n)
                if self._fade_out == 0 and n < len(samples):
                    samples[n:] = 0.0
                data = np.clip(samples, -32768, 32767).astype(np.int16).tobytes()
            elif self._squelched:
                try:
                    while True:
                        self._queue.get_nowait()
                except queue.Empty:
                    pass
                data = _silence

            if self._proc and self._proc.stdin:
                try:
                    self._proc.stdin.write(data)
                except BrokenPipeError:
                    break

    # ── Signaltöne ────────────────────────────────────────────────────────────

    @staticmethod
    def _render_tone(freq_hz: int, duration_s: float, amplitude: float) -> bytes:
        n    = int(cfg.AUDIO_RATE * duration_s)
        t    = np.linspace(0, duration_s, n, endpoint=False, dtype=np.float32)
        tone = np.sin(2 * np.pi * freq_hz * t)
        fade = min(int(cfg.AUDIO_RATE * 0.015), n // 4)
        tone[:fade]  *= np.linspace(0.0, 1.0, fade, dtype=np.float32)
        tone[-fade:] *= np.linspace(1.0, 0.0, fade, dtype=np.float32)
        return np.clip(tone * amplitude * 32767, -32768, 32767).astype(np.int16).tobytes()

    def play_beep(self, freq_hz: int = 880, duration_s: float = 0.25, amplitude: float = 0.4):
        def _run():
            pcm = self._render_tone(freq_hz, duration_s, amplitude)
            try:
                proc = subprocess.Popen(
                    ["aplay", "-r", str(cfg.AUDIO_RATE), "-f", "S16_LE",
                     "-c", "1", "-D", cfg.AUDIO_DEVICE, "-"],
                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                proc.stdin.write(pcm)
                proc.stdin.close()
                proc.wait(timeout=2)
            except Exception as e:
                log.debug("play_beep Fehler: %s", e)
        threading.Thread(target=_run, daemon=True, name="beep").start()

    def play_jingle(self, tones: list[tuple[int, float]], amplitude: float = 0.4):
        """Spielt eine Folge von (freq_hz, duration_s)-Tupeln nacheinander."""
        def _run():
            pcm = b"".join(self._render_tone(f, d, amplitude) for f, d in tones)
            try:
                proc = subprocess.Popen(
                    ["aplay", "-r", str(cfg.AUDIO_RATE), "-f", "S16_LE",
                     "-c", "1", "-D", cfg.AUDIO_DEVICE, "-"],
                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                proc.stdin.write(pcm)
                proc.stdin.close()
                proc.wait(timeout=4)
            except Exception as e:
                log.debug("play_jingle Fehler: %s", e)
        threading.Thread(target=_run, daemon=True, name="jingle").start()

    # ── Lautstärke ───────────────────────────────────────────────────────────

    def set_volume(self, vol: int):
        self._volume = max(0, min(100, vol))
        for cmd in [
            ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{self._volume}%"],
            ["amixer", "sset", "PCM", f"{self._volume}%"],
        ]:
            try:
                if subprocess.run(cmd, capture_output=True, check=False).returncode == 0:
                    return
            except FileNotFoundError:
                continue

    def volume_up(self):
        self.set_volume(self._volume + 5)

    def volume_down(self):
        self.set_volume(self._volume - 5)

    @property
    def volume(self) -> int:
        return self._volume

# core/scanner.py – Haupt-Controller mit Memory-Bank und Kalibrierungs-Integration

import os
import queue
import subprocess
import time
import threading
import logging
from threading import Lock
from enum import Enum, auto
from typing import Optional

# Wartezeiten zwischen Dongle-Wiederverbindungsversuchen (Sekunden)
_RETRY_INTERVALS = (0.3, 1.0, 2.0, 5.0, 10.0, 30.0)
# Nach so vielen Fehlversuchen USB-Reset probieren
_USB_RESET_AFTER = 4
# Mindestpause nach letztem Encoder-Tick bevor rtl_fm neugestartet wird
_RETUNE_DEBOUNCE = 0.12   # Sekunden

import config.settings as cfg
from core.frequency    import FrequencyManager, Channel
from core.squelch      import SquelchController
from core.demodulator  import Demodulator
from core.audio        import AudioPipeline
from core.bookmarks    import BookmarkDB
from core.memory_banks import MemoryBanks
from core.buttons      import ButtonHandler, ButtonEvent, Event
from core.calibration  import Calibrator
from core.bluetooth    import BluetoothManager

log = logging.getLogger(__name__)


class ScannerState(Enum):
    IDLE        = auto()   # Kanal stehen, kein Scan
    SCANNING    = auto()   # Scan läuft
    ACTIVE      = auto()   # Signal / Squelch offen
    BANK_SELECT = auto()   # Bank-Auswahl-Overlay
    MENU        = auto()   # Hauptmenü
    CALIBRATING = auto()   # PPM-Kalibrierung läuft
    BT_SETUP    = auto()   # Bluetooth-Einrichtungswizard



class Scanner:
    def __init__(self, debug: bool = False):
        self.debug = debug
        self.state = ScannerState.IDLE

        self._evq: queue.Queue[Event] = queue.Queue(maxsize=64)

        # Sub-Systeme
        self.freq        = FrequencyManager()
        self.squelch     = SquelchController()
        self.audio       = AudioPipeline()
        self.db          = BookmarkDB()
        self.banks       = MemoryBanks(self.db.conn)   # teilt DB-Verbindung
        self.buttons     = ButtonHandler(self._evq, debug=debug)
        self.demod       = Demodulator(
            audio_callback=self.audio.feed,
            rssi_callback=self._on_rssi,
            on_unexpected_exit=self._on_dongle_disconnect,
        )

        self._scan_timer: Optional[threading.Timer] = None
        self._active_since: float = 0.0
        self._was_scanning: bool  = False
        self._rssi_lock = Lock()
        self._tune_lock = Lock()         # verhindert parallele stop/start aus scan-Timer- und Haupt-Thread
        self._last_nav_at: float = 0.0  # Zeitstempel letzter Encoder-Navigation
        self._needs_retune: bool = False # pendender Encoder-Retune (debounced)
        self._dongle_retry_at: float = time.monotonic() + 3.0  # erste Prüfung nach 3 s
        self._dongle_was_ok: bool = False  # für Verbindungsverlust-Erkennung
        self._retry_count: int = 0
        self._loaded_bank: Optional[int] = None  # welche Bank liegt im FrequencyManager
        self.agc_enabled: bool  = True   # True = rtl_fm -g auto, False = cfg.RTL_GAIN
        self.enc_vol_mode: bool = False  # False = Encoder dreht Kanal, True = Lautstärke

        self._calib_log: list[str] = []   # letzte Meldungen für Display-Overlay
        self._calibrator: Optional[Calibrator] = None
        self.scan_all_banks: bool = False  # True → nach Bank-Wrap zur nächsten Bank
        self._hotspot_on: bool   = self._check_hotspot_active()
        self._hotspot_busy: bool = False  # Setup-Thread läuft gerade
        self.bt = BluetoothManager()
        self.bt.on_disconnect = self._bt_on_disconnect

        # BT-Reconnect-State
        self._bt_poll_at: float       = time.monotonic() + 15.0  # erste Prüfung nach 15 s
        self._bt_reconnect_at: float  = 0.0   # >0: Reconnect zu diesem Zeitpunkt starten
        self._bt_reconnecting: bool   = False  # verhindert parallele Reconnect-Threads

        # UI-Callback
        self.on_state_change = lambda: None

    # ── Start / Stop ──────────────────────────────────────────────────────────

    def start(self):
        log.info("Scanner startet")
        self.audio.start()
        self.banks.set_active_bank(0)
        self._load_active_bank()          # lädt B0 (ruft intern _tune_current auf)
        if self._loaded_bank is None:     # B0 leer → Fallback auf cfg.CHANNELS
            self._tune_current()
        log.info("Bereit – %d Kanäle, Bank %d ('%s')",
                 len(self.freq), self.banks.active_bank, self.banks.active_bank_name)
        threading.Thread(target=self._bt_watchdog, daemon=True, name="bt-watchdog").start()

    def stop(self):
        self._cancel_scan_timer()
        self.demod.close()
        self.audio.stop()
        self.db.close()

    # ── Hotspot ───────────────────────────────────────────────────────────────

    def _check_hotspot_active(self) -> bool:
        if self.debug:
            return False
        try:
            r = subprocess.run(["systemctl", "is-active", "sdr_hotspot.service"],
                               capture_output=True, text=True, timeout=2)
            return r.stdout.strip() == "active"
        except Exception:
            return False

    def toggle_hotspot(self):
        if self.debug:
            return
        if self._hotspot_busy:
            return
        # Wenn hostapd noch nicht konfiguriert: Setup in Hintergrund-Thread
        if not os.path.exists("/etc/hostapd/hostapd.conf"):
            self._hotspot_busy = True
            self.on_state_change()
            threading.Thread(target=self._run_hotspot_setup,
                             daemon=True, name="hotspot-setup").start()
            return
        cmd = "stop" if self._hotspot_on else "start"
        try:
            subprocess.run(["sudo", "systemctl", cmd, "sdr_hotspot.service"],
                           timeout=10, capture_output=True)
            self._hotspot_on = not self._hotspot_on
            log.info("Hotspot %s", "gestartet" if self._hotspot_on else "gestoppt")
        except Exception as e:
            log.warning("Hotspot-Toggle fehlgeschlagen: %s", e)
        self.on_state_change()

    def _run_hotspot_setup(self):
        script = "/usr/share/sdr-scanner/hotspot/setup_hotspot.sh"
        log.info("Hotspot-Ersteinrichtung läuft …")
        try:
            r = subprocess.run(
                ["sudo", "bash", script],
                timeout=120, capture_output=True, text=True
            )
            if r.returncode != 0:
                log.warning("Hotspot-Setup Fehler (rc=%d): %s", r.returncode, r.stderr[:200])
            self._hotspot_on = self._check_hotspot_active()
            log.info("Hotspot-Setup abgeschlossen, aktiv=%s", self._hotspot_on)
        except Exception as e:
            log.warning("Hotspot-Setup fehlgeschlagen: %s", e)
        finally:
            self._hotspot_busy = False
        self.on_state_change()

    def run(self):
        self.start()
        try:
            while True:
                try:
                    event = self._evq.get(timeout=0.1)
                    self._handle_event(event)
                except queue.Empty:
                    pass
                except Exception as e:
                    log.exception("Fehler in Event-Handler: %s", e)
                try:
                    self._tick()
                except Exception as e:
                    log.exception("Fehler in Tick: %s", e)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    # ── Tick ──────────────────────────────────────────────────────────────────

    def _tick(self):
        if self.state == ScannerState.CALIBRATING:
            return

        if self.state == ScannerState.ACTIVE and not self.squelch.open:
            elapsed = time.monotonic() - self._active_since
            if elapsed > cfg.SCAN_RESUME_DELAY:
                if self._was_scanning:
                    self._begin_scan()
                else:
                    self.state = ScannerState.IDLE
                self.on_state_change()

        # Debounced Encoder-Retune: erst nach _RETUNE_DEBOUNCE Sekunden Ruhe tunen,
        # damit schnelles Drehen keinen USB-Regen auslöst.
        if (self._needs_retune
                and self.state in (ScannerState.IDLE, ScannerState.ACTIVE)
                and time.monotonic() - self._last_nav_at >= _RETUNE_DEBOUNCE):
            self._needs_retune = False
            self._tune_current()

        # Dongle-Watchdog: Wiederverbindung mit exponentiellem Backoff
        if not self.demod.dongle_ok and not self.debug:
            if self._dongle_was_ok:
                self._dongle_was_ok = False
                log.warning("SDR-Dongle getrennt – Hinweiston")
                self.audio.play_beep(freq_hz=440, duration_s=0.4)
                self.on_state_change()  # UI sofort aktualisieren (nicht erst beim Retry)
            now = time.monotonic()
            if now >= self._dongle_retry_at:
                self._retry_count += 1
                interval = _RETRY_INTERVALS[min(self._retry_count, len(_RETRY_INTERVALS) - 1)]
                self._dongle_retry_at = now + interval
                log.info("Dongle-Wiederverbindung Versuch %d (nächster in %.0f s)",
                         self._retry_count, interval)
                if self._retry_count == _USB_RESET_AFTER:
                    log.warning("Starte USB-Reset nach %d Fehlversuchen", _USB_RESET_AFTER)
                    threading.Thread(
                        target=self._usb_reset_and_retry, daemon=True, name="usb-reset"
                    ).start()
                else:
                    self._tune_current()
                    self.on_state_change()
        else:
            if self.demod.dongle_ok and self._retry_count > 0:
                log.info("SDR-Dongle wieder verbunden (nach %d Versuchen)", self._retry_count)
                self._retry_count = 0
                self.audio.play_jingle([(880, 0.12), (1320, 0.18)])
                if self.state == ScannerState.SCANNING:
                    self._begin_scan()
            # dongle_ok False→True immer broadcasten (z.B. nach Kalibrierung)
            if self.demod.dongle_ok and not self._dongle_was_ok:
                self.on_state_change()
            self._dongle_was_ok = self.demod.dongle_ok

    def _bt_watchdog(self):
        """
        Dedizierter Hintergrundthread für BT-Verbindungsüberwachung und Auto-Reconnect.
        Läuft unabhängig vom Hauptloop – kein Blocking, kein State-Chaos.
        """
        log.warning("BT-Watchdog gestartet (Gerät: %s)", cfg.BT_DEVICE_ADDRESS or "–")
        time.sleep(10)  # Warmup: warten bis PulseAudio und BlueZ bereit sind

        while True:
            try:
                self._bt_watchdog_tick()
            except Exception as e:
                log.warning("BT-Watchdog Fehler: %s", e)
            time.sleep(15)

    def _bt_watchdog_tick(self):
        if self.debug:
            return
        addr = cfg.BT_DEVICE_ADDRESS
        if not cfg.BT_AUTO_RECONNECT or not addr:
            return

        # Verbindungsverlust erkennen: connected_address gesetzt aber D-Bus sagt nein
        if self.bt.connected_address and not self.bt.is_connected():
            log.warning("BT: Verbindung zu %s verloren – Audio auf lokal", self.bt.connected_address)
            self.bt.connected_address = None
            try:
                self.audio.stop()
                time.sleep(0.3)
                self.audio.start()
            except Exception as e:
                log.warning("BT audio-restart nach Disconnect: %s", e)
            self.on_state_change()

        # Nicht verbunden → Reconnect versuchen
        if self.bt.connected_address:
            return  # bereits verbunden
        if self._bt_reconnecting:
            return  # läuft schon

        self._bt_reconnecting = True
        log.warning("BT: Reconnect-Versuch → %s", addr)
        try:
            if not self.bt.available():
                log.warning("BT: kein Adapter – Versuch übersprungen")
                return
            ok = self.bt.connect(addr)
            if ok:
                self.bt.connected_address = addr
                sink_ok = self.bt.set_audio_sink(addr)
                if sink_ok:
                    self.audio.stop()
                    time.sleep(0.3)
                    self.audio.start()
                self.on_state_change()
                log.warning("BT: Reconnect OK → %s", addr)
            else:
                log.warning("BT: Reconnect fehlgeschlagen – nächster Versuch in ~15s")
        finally:
            self._bt_reconnecting = False

    # ── Event-Handling ────────────────────────────────────────────────────────

    def _handle_event(self, event: Event):
        t = event.type

        # ── Menü-Modus: Encoder bewegt Cursor im Display-Overlay ──────────
        if self.state == ScannerState.MENU:
            disp = getattr(self, '_display_ref', None)
            if t == ButtonEvent.ENC_UP:
                if disp: disp.menu_cursor_up()
            elif t == ButtonEvent.ENC_DOWN:
                if disp: disp.menu_cursor_down()
            elif t == ButtonEvent.ENC_PRESS:
                if disp: disp.menu_confirm()
            elif t == ButtonEvent.MENU:
                self.state = ScannerState.IDLE
            self.on_state_change()
            return

        # ── BT-Wizard: Encoder navigiert, ENC_PRESS bestätigt ────────────
        if self.state == ScannerState.BT_SETUP:
            disp = getattr(self, '_display_ref', None)
            if t == ButtonEvent.ENC_UP:
                if disp: disp.bt_cursor_up()
            elif t == ButtonEvent.ENC_DOWN:
                if disp: disp.bt_cursor_down()
            elif t == ButtonEvent.ENC_PRESS:
                if disp: disp.bt_confirm()
            elif t == ButtonEvent.MENU:
                if disp: disp.bt_back()
                else: self.state = ScannerState.IDLE
            self.on_state_change()
            return

        # ── Bank-Select-Modus: Encoder dreht Bank ─────────────────────────
        if self.state == ScannerState.BANK_SELECT:
            if t == ButtonEvent.ENC_UP:
                self.banks.next_bank()
                self._load_active_bank()
            elif t == ButtonEvent.ENC_DOWN:
                self.banks.prev_bank()
                self._load_active_bank()
            elif t == ButtonEvent.BANK_LOAD:
                self._load_active_bank()
            elif t in (ButtonEvent.ENC_PRESS, ButtonEvent.MENU):
                self.state = ScannerState.IDLE
            self.on_state_change()
            return

        # ── Normalbetrieb ──────────────────────────────────────────────────
        if t == ButtonEvent.SCAN_TOGGLE:
            self._toggle_scan()

        elif t == ButtonEvent.MONITOR_ON:
            self.squelch.forced_open = True
            self.on_state_change()

        elif t == ButtonEvent.MONITOR_OFF:
            self.squelch.forced_open = False
            self.on_state_change()

        elif t == ButtonEvent.MODE:
            self.freq.cycle_mode()
            self._tune_current()

        elif t == ButtonEvent.MEMORY:
            self.state = ScannerState.BANK_SELECT

        elif t == ButtonEvent.MEMORY_LONG:
            self._save_to_bank()

        elif t == ButtonEvent.SQ_UP:
            self.squelch.increase()
            self._save_squelch_to_channel()

        elif t == ButtonEvent.SQ_DOWN:
            self.squelch.decrease()
            self._save_squelch_to_channel()

        elif t == ButtonEvent.ENC_VOL_TOGGLE:
            if self.state in (ScannerState.IDLE, ScannerState.ACTIVE):
                self.enc_vol_mode = not self.enc_vol_mode
                log.info("Encoder-Modus: %s", "Lautstärke" if self.enc_vol_mode else "Kanal")

        elif t == ButtonEvent.ENC_UP:
            if self.state in (ScannerState.IDLE, ScannerState.ACTIVE):
                if self.enc_vol_mode:
                    self.audio.volume_up()
                else:
                    self.freq.next()
                    self._last_nav_at = time.monotonic()
                    self._needs_retune = True
                    self.on_state_change()
            else:
                self.audio.volume_up()

        elif t == ButtonEvent.ENC_DOWN:
            if self.state in (ScannerState.IDLE, ScannerState.ACTIVE):
                if self.enc_vol_mode:
                    self.audio.volume_down()
                else:
                    self.freq.prev()
                    self._last_nav_at = time.monotonic()
                    self._needs_retune = True
                    self.on_state_change()
            else:
                self.audio.volume_down()

        elif t == ButtonEvent.ENC_PRESS:
            self._toggle_scan()

        elif t == ButtonEvent.MENU:
            self.state = (ScannerState.IDLE
                          if self.state == ScannerState.MENU
                          else ScannerState.MENU)

        elif t == ButtonEvent.BT_SETUP:
            self.state = ScannerState.BT_SETUP

        elif t == ButtonEvent.BANK_NEXT:
            self.banks.next_bank()
            self._load_active_bank()

        elif t == ButtonEvent.BANK_PREV:
            self.banks.prev_bank()
            self._load_active_bank()

        elif t == ButtonEvent.BANK_LOAD:
            self._load_active_bank()

        elif t == ButtonEvent.RENAME:
            new_name = (event.extra or {}).get("name", "").strip()
            if new_name:
                self._rename_current(new_name)

        elif t == ButtonEvent.AGC_TOGGLE:
            self.agc_enabled = not self.agc_enabled
            self._tune_current()
            log.info("AGC %s", "auto" if self.agc_enabled else f"manuell ({cfg.RTL_GAIN})")

        elif t == ButtonEvent.CALIBRATE:
            self._start_calibration()

        self.on_state_change()

    # ── Memory-Bank-Operationen ───────────────────────────────────────────────

    def _save_to_bank(self):
        ch = self.freq.current
        if not ch:
            return
        mem_ch = self.banks.save(ch.name, ch.freq, ch.mode, ch.group,
                                  gain=ch.gain, squelch=self.squelch.level,
                                  bandwidth=ch.bandwidth)
        log.info("In Bank %d gespeichert: %s", self.banks.active_bank, mem_ch)

    def _load_active_bank(self):
        """Lädt alle Kanäle der aktiven Bank in den FrequencyManager."""
        channels = self.banks.list_bank()
        if not channels:
            log.info("Bank %d ist leer", self.banks.active_bank)
            return
        self.freq.channels.clear()
        self.freq.index = 0
        self.freq.scan_index = 0
        for mem_ch in channels:
            self.freq.add(Channel(
                name=mem_ch.name,
                freq=mem_ch.freq,
                mode=mem_ch.mode,
                group=mem_ch.group,
                gain=mem_ch.gain,
                squelch=mem_ch.squelch,
                bandwidth=mem_ch.bandwidth,
            ))
        self._loaded_bank = self.banks.active_bank
        self._tune_current()
        log.info("Bank %d geladen: %d Kanäle", self.banks.active_bank, len(self.freq))

    def _bt_on_disconnect(self) -> None:
        """Wird von bt.disconnect() gerufen (explizite Trennung aus dem Menü)."""
        self.bt.connected_address = None
        self.on_state_change()

    # ── Scan ──────────────────────────────────────────────────────────────────

    def _toggle_scan(self):
        # ACTIVE + _was_scanning: Scanner ist auf Signal gerastet → Scan stoppen, auf Kanal bleiben.
        # SCANNING: Scan läuft → stoppen.
        # Sonst: Scan starten.
        if self.state == ScannerState.SCANNING or (
                self.state == ScannerState.ACTIVE and self._was_scanning):
            self._cancel_scan_timer()
            self.state = ScannerState.IDLE
            self._was_scanning = False
        else:
            self._was_scanning = True
            self._begin_scan()

    def _begin_scan(self):
        self._needs_retune = False   # pendenden Encoder-Retune verwerfen
        self.state = ScannerState.SCANNING
        self._schedule_next_channel()

    def _schedule_next_channel(self):
        self._cancel_scan_timer()
        self._scan_timer = threading.Timer(cfg.SCAN_DWELL_TIME, self._scan_step)
        self._scan_timer.daemon = True
        self._scan_timer.start()

    def _scan_step(self):
        if self.state != ScannerState.SCANNING:
            return
        if self.squelch.open:
            ch = self.freq.channels[self.freq.scan_index]
            self.freq.index = self.freq.scan_index
            self.state = ScannerState.ACTIVE
            self._active_since = time.monotonic()
            self.on_state_change()
        else:
            old_idx = self.freq.scan_index
            n       = len(self.freq.channels)
            ch = self.freq.scan_next()
            if ch:
                self.freq.index = self.freq.scan_index
                self._tune(ch)
                self.on_state_change()
            # Wrap: old_idx war letzter Index → nächste Bank laden
            # (funktioniert auch bei Einzelkanal-Bänken)
            if self.scan_all_banks and n > 0 and old_idx == n - 1:
                for _ in range(10):          # leere Bänke überspringen
                    self.banks.next_bank()
                    if self.banks.list_bank():
                        self._load_active_bank()
                        log.info("Alle-Bänke-Scan: Bank %d", self.banks.active_bank)
                        break
            self._schedule_next_channel()

    def _skip_channel(self):
        ch = self.freq.current
        if ch:
            self.db.log_activity(ch.name, ch.freq, ch.mode, ch.group,
                                 self.squelch.open_duration)
        if self._was_scanning:
            self._begin_scan()
        else:
            self.state = ScannerState.IDLE

    def _save_squelch_to_channel(self):
        """Aktuellen Squelch-Pegel im RAM-Channel und in der DB speichern."""
        ch = self.freq.current
        if not ch:
            return
        ch.squelch = self.squelch.level
        self.banks.update_squelch(ch.freq, ch.mode, self.squelch.level)

    def _save_gain_to_channel(self, gain: Optional[float]):
        ch = self.freq.current
        if not ch:
            return
        ch.gain = gain
        effective = gain if gain is not None else cfg.AUDIO_SOFT_GAIN
        if self.agc_enabled:
            effective = effective * cfg.AUDIO_AGC_MAKEUP
        self.audio.channel_gain = effective
        self.banks.update_gain(ch.freq, ch.mode, gain)

    def _save_bandwidth_to_channel(self, bandwidth: Optional[int]):
        """Kanalbandbreite im RAM-Channel und in der DB speichern, LPF automatisch ableiten."""
        ch = self.freq.current
        if not ch:
            return
        ch.bandwidth = bandwidth
        bw = bandwidth if bandwidth is not None else cfg.MODE_BANDWIDTH.get(ch.mode)
        lpf = None if ch.mode == "WFM" else (bw // 3 if bw else cfg.MODE_AUDIO_LPF.get(ch.mode))
        self.audio.set_lpf(lpf)
        self.banks.update_bandwidth(ch.freq, ch.mode, bandwidth)

    def _cancel_scan_timer(self):
        if self._scan_timer:
            self._scan_timer.cancel()
            self._scan_timer = None

    # ── Tuning ────────────────────────────────────────────────────────────────

    def _tune_current(self):
        ch = self.freq.current
        if ch:
            self._tune(ch)

    def _tune(self, ch: Channel):
        if self.debug:
            return
        # Lock verhindert parallele stop/start-Aufrufe aus dem Scan-Timer-Thread
        # und dem Haupt-Loop / Flask-Thread → kein doppelter USB-Zugriff
        with self._tune_lock:
            self.squelch.level = ch.squelch if ch.squelch is not None else self.squelch.level
            self.demod.stop()
            gain = "auto" if self.agc_enabled else cfg.RTL_GAIN
            self.demod.start(ch.freq, ch.mode, self.squelch.level, gain=gain)
            # Demodulator-IIR limitiert bereits auf Modusbreite – audio.py-FIR wäre redundant
            # und kostet ~2 ms/Chunk im Stream-Thread → ALSA-Underruns alle ~2 s.
            self.audio.set_lpf(None)
            self.audio.comp_enabled = (ch.mode != "WFM")
            gain = ch.gain if ch.gain is not None else cfg.AUDIO_SOFT_GAIN
            if self.agc_enabled:
                gain = gain * cfg.AUDIO_AGC_MAKEUP
            self.audio.channel_gain = gain

    # ── RSSI-Callback ─────────────────────────────────────────────────────────

    def _on_rssi(self, rssi: float):
        with self._rssi_lock:
            was_open = self.squelch.open
            self.squelch.update(rssi)
            now_open = self.squelch.open
            self.audio.squelched = not now_open
            if now_open != was_open:
                log.warning("Squelch %s (RSSI=%.1f thr=%d)",
                            "ÖFFNET" if now_open else "SCHLIESST",
                            rssi, self.squelch.level)
                if now_open and self.state == ScannerState.IDLE:
                    self.state = ScannerState.ACTIVE
                    self._active_since = time.monotonic()
                self.on_state_change()

    def _rename_current(self, new_name: str):
        """
        Benennt den aktuell aktiven Kanal um.
        Aktualisiert sowohl den FrequencyManager-Eintrag im RAM
        als auch alle passenden Einträge in der Memory-Bank-DB.
        """
        ch = self.freq.current
        if not ch:
            return
        # RAM-Objekt sofort umbenennen (wirkt auf Display)
        ch.name = new_name
        # In DB umbenennen (alle Bänke die diese Freq+Mode haben)
        updated = self.banks.rename_by_freq(ch.freq, ch.mode, new_name)
        if updated:
            log.info("Kanal umbenannt → '%s' (in Bank %d)", new_name, self.banks.active_bank)
        else:
            log.info("Kanal umbenannt → '%s' (nur RAM, noch nicht gespeichert)", new_name)

    # ── Kalibrierung ──────────────────────────────────────────────────────────

    def _start_calibration(self):
        if self.state == ScannerState.CALIBRATING:
            return
        self._cancel_scan_timer()
        self.demod.close()
        self.state = ScannerState.CALIBRATING
        self._calib_log = ["Kalibrierung gestartet…"]
        self.on_state_change()

        def _progress(msg: str):
            self._calib_log = (self._calib_log + [msg])[-8:]
            self.on_state_change()

        def _done(result):
            if result:
                _progress(f"Ergebnis: {result.ppm:+.1f} ppm")
                Calibrator.apply_to_settings(result.ppm, demod=self.demod)
                _progress(f"PPM gesetzt: {int(round(result.ppm)):+d}")
            else:
                _progress("Kalibrierung fehlgeschlagen")
                self.demod._open_device()
            self.state = ScannerState.IDLE
            self._tune_current()
            self.on_state_change()

        self._calibrator = Calibrator(progress_cb=_progress)

        def _run():
            time.sleep(0.5)   # USB freigeben lassen bevor rtl_power öffnet
            result = self._calibrator.run_auto()
            _done(result)

        threading.Thread(target=_run, daemon=True, name="calibration").start()

    # ── Dongle-Disconnect-Callback (aus Demodulator-Thread) ───────────────────

    def _on_dongle_disconnect(self):
        """Wird aus dem Demodulator-Thread gerufen wenn rtl_fm unerwartet endet."""
        interval = _RETRY_INTERVALS[min(self._retry_count, len(_RETRY_INTERVALS) - 1)]
        self._dongle_retry_at = time.monotonic() + interval
        # Scan pausieren: ohne Pause würde jeder Scan-Schritt erneut fehlschlagen
        # und _dongle_retry_at laufend auf now+interval zurücksetzen →
        # _tick() kommt nie zum Retry-Timer (Endlosschleife).
        # threading.Timer.cancel() ist thread-safe.
        t = self._scan_timer
        if t:
            t.cancel()
            self._scan_timer = None

    def _usb_reset_and_retry(self):
        """USB-Reset im Hintergrund-Thread, danach sofortiger Reconnect-Versuch."""
        from core.demodulator import Demodulator as _D
        _D.usb_reset()
        # nach dem Reset etwas warten, dann neu einstimmen
        time.sleep(2.0)
        self._tune_current()
        self.on_state_change()

    # ── Status-Snapshot für UI ────────────────────────────────────────────────

    def status_dict(self) -> dict:
        ch = self.freq.current
        return {
            "state":        self.state.name,
            "scanning":     self._was_scanning and self.state in (
                                ScannerState.SCANNING, ScannerState.ACTIVE),
            "channel":      str(ch) if ch else "–",
            "freq":         ch.freq if ch else 0,
            "freq_mhz":     ch.freq_mhz if ch else "0.0000",
            "mode":         ch.mode if ch else "–",
            "group":        ch.group if ch else "–",
            "ch_index":     self.freq.index,
            "ch_total":     len(self.freq),
            "squelch_open": self.squelch.open,
            "rssi":         self.squelch.rssi,
            "signal_bar":   self.squelch.signal_bar,
            "sq_level":     self.squelch.level,
            "bandwidth":    ch.bandwidth if ch else None,
            "volume":       self.audio.volume,
            # Memory-Bank-Infos
            "bank":         self.banks.active_bank,
            "bank_name":    self.banks.active_bank_name,
            "bank_summary": self.banks.bank_summary(),
            # Audio-Gain des aktuellen Kanals (roher Wert ohne AGC-Makeup)
            "audio_gain":   ch.gain if ch and ch.gain is not None else cfg.AUDIO_SOFT_GAIN,
            # Kalibrierung
            "calib_log":    list(self._calib_log),
            # Hardware
            "dongle_ok":    self.demod.dongle_ok,
            "comp_enabled": self.audio.comp_enabled,
            "agc_enabled":    self.agc_enabled,
            "enc_vol_mode":   self.enc_vol_mode,
            "scan_all_banks": self.scan_all_banks,
            "loaded_bank":    self._loaded_bank,
            "bt_connected":   self.bt.is_connected(),
            "bt_name":        self.bt.connected_name() or "",
            "hotspot_on":         self._hotspot_on,
            "hotspot_configured": os.path.exists("/etc/hostapd/hostapd.conf"),
            "hotspot_busy":       self._hotspot_busy,
        }

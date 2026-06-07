# core/buttons.py – GPIO-Tasten und Rotary-Encoder (erweitert um Bank-Events)

import queue
import time
import logging
from enum import Enum, auto
from dataclasses import dataclass

import config.settings as cfg

log = logging.getLogger(__name__)


class ButtonEvent(Enum):
    SCAN_TOGGLE  = auto()
    MODE         = auto()
    MEMORY       = auto()   # kurzer MEM-Druck: aktiven Kanal in Bank speichern
    MEMORY_LONG  = auto()   # langer MEM-Druck: Bank umbenennen (im Menü)
    SQ_UP        = auto()
    SQ_DOWN      = auto()
    ENC_UP       = auto()
    ENC_DOWN     = auto()
    ENC_PRESS    = auto()
    MENU         = auto()   # langer ENC_SW: Menü öffnen / Bank-Select
    BANK_NEXT    = auto()   # zur nächsten Memory-Bank wechseln
    BANK_PREV    = auto()   # zur vorherigen Memory-Bank wechseln
    BANK_LOAD    = auto()   # Kanäle der aktiven Bank in FrequencyManager laden
    RENAME       = auto()   # Aktuellen Kanal umbenennen (extra: {"name": str})
    AGC_TOGGLE   = auto()   # RTL-Hardware-Gain zwischen "auto" und manuellem Wert umschalten
    CALIBRATE    = auto()   # PPM-Kalibrierung starten
    MONITOR_ON   = auto()   # Monitor-Taste gedrückt → Squelch force-open
    MONITOR_OFF  = auto()   # Monitor-Taste losgelassen → Squelch normal
    BT_SETUP     = auto()   # Bluetooth-Wizard öffnen
    ENC_VOL_TOGGLE = auto() # Encoder-Modus wechseln: Kanal ↔ Lautstärke


@dataclass
class Event:
    type:  ButtonEvent
    extra: dict | None = None


class _LgpioEncoder:
    """
    Encoder-Lesung via lgpio (eigener Handle, unabhängig von gpiozero).
    CW-Sequenz: 0→2→3→1→0  (per-Pin-Tracking via level-Parameter).
    Feuert nach je 2 gültigen Transitionen → einmal pro Raste.
    """
    _TABLE = {
        (0, 2):  1, (2, 3):  1, (3, 1):  1, (1, 0):  1,
        (0, 1): -1, (1, 3): -1, (3, 2): -1, (2, 0): -1,
    }

    def __init__(self, pin_a, pin_b, cw_cb, ccw_cb):
        import lgpio as _lgpio
        self._lg     = _lgpio
        self._pin_a  = pin_a
        self._pin_b  = pin_b
        self._cw_cb  = cw_cb
        self._ccw_cb = ccw_cb
        self._accum  = 0

        self._h = _lgpio.gpiochip_open(0)
        # Encoder-VCC via GPIO: Output-HIGH liefert 3,3V (~1 mA, weit unter GPIO-Limit)
        if cfg.GPIO_ENC_VCC is not None:
            _lgpio.gpio_claim_output(self._h, cfg.GPIO_ENC_VCC, 1)
        _lgpio.gpio_claim_input(self._h, pin_a, _lgpio.SET_PULL_UP)
        _lgpio.gpio_claim_input(self._h, pin_b, _lgpio.SET_PULL_UP)
        self._a = _lgpio.gpio_read(self._h, pin_a)
        self._b = _lgpio.gpio_read(self._h, pin_b)
        self._state = (self._a << 1) | self._b

        _lgpio.gpio_claim_alert(self._h, pin_a, _lgpio.BOTH_EDGES)
        _lgpio.gpio_claim_alert(self._h, pin_b, _lgpio.BOTH_EDGES)
        self._cba = _lgpio.callback(self._h, pin_a, _lgpio.BOTH_EDGES, self._cb)
        self._cbb = _lgpio.callback(self._h, pin_b, _lgpio.BOTH_EDGES, self._cb)

    def _cb(self, _chip, gpio, level, _tick):
        if gpio == self._pin_a:
            self._a = level
        else:
            self._b = level
        new   = (self._a << 1) | self._b
        delta = self._TABLE.get((self._state, new), 0)
        self._state = new
        if not delta:
            return
        self._accum += delta
        if abs(self._accum) >= 2:
            (self._cw_cb if self._accum > 0 else self._ccw_cb)()
            self._accum = 0


class ButtonHandler:
    def __init__(self, event_queue: queue.Queue, debug: bool = False):
        self._q        = event_queue
        self._debug    = debug
        # GPIO-Pins brauchen ~1s um nach Initialisierung zu stabilisieren.
        # Spurious-Events in diesem Fenster (z.B. ENC_PRESS beim Start) werden verworfen.
        self._ready_at = time.monotonic() + 1.5
        if not debug:
            self._setup_gpio()

    def _setup_gpio(self):
        try:
            from gpiozero import Button
            btn_scan   = Button(cfg.GPIO_BTN_SCAN,   pull_up=True, bounce_time=0.05)
            btn_mode   = Button(cfg.GPIO_BTN_MODE,   pull_up=True, bounce_time=0.05,
                                hold_time=0.8)
            btn_mem    = Button(cfg.GPIO_BTN_MEMORY, pull_up=True, bounce_time=0.05,
                                hold_time=1.5)
            btn_sq_up  = Button(cfg.GPIO_BTN_SQ_UP,  pull_up=True, bounce_time=0.03)
            btn_sq_dn  = Button(cfg.GPIO_BTN_SQ_DN,  pull_up=True, bounce_time=0.03)
            btn_enc_sw = Button(cfg.GPIO_ENC_SW,     pull_up=True, bounce_time=0.05,
                                hold_time=1.0)
            btn_scan.when_pressed    = lambda: self._push(ButtonEvent.MONITOR_ON)
            btn_scan.when_released   = lambda: self._push(ButtonEvent.MONITOR_OFF)

            # Kurzer Druck → ENC_VOL_TOGGLE, langer Druck → MODE
            # Flag verhindert dass der kurze Druck auch beim langen Druck feuert.
            _mode_held = [False]

            def _on_mode_held():
                _mode_held[0] = True
                self._push(ButtonEvent.MODE)

            def _on_mode_released():
                if not _mode_held[0]:
                    self._push(ButtonEvent.ENC_VOL_TOGGLE)
                _mode_held[0] = False

            btn_mode.when_held     = _on_mode_held
            btn_mode.when_released = _on_mode_released

            # MEM: kurzer Druck → TTS, langer Druck → Bank-Select
            _mem_held = [False]

            def _on_mem_held():
                _mem_held[0] = True
                self._push(ButtonEvent.MEMORY_LONG)

            def _on_mem_released():
                if not _mem_held[0]:
                    self._push(ButtonEvent.MEMORY)
                _mem_held[0] = False

            btn_mem.when_held     = _on_mem_held
            btn_mem.when_released = _on_mem_released

            btn_sq_up.when_pressed   = lambda: self._push(ButtonEvent.SQ_UP)
            btn_sq_dn.when_pressed   = lambda: self._push(ButtonEvent.SQ_DOWN)

            # ENC_SW: kurzer Druck → ENC_PRESS (Scan toggle), langer Druck → MENU
            _enc_held = [False]

            def _on_enc_held():
                _enc_held[0] = True
                self._push(ButtonEvent.MENU)

            def _on_enc_released():
                if not _enc_held[0]:
                    self._push(ButtonEvent.ENC_PRESS)
                _enc_held[0] = False

            btn_enc_sw.when_held     = _on_enc_held
            btn_enc_sw.when_released = _on_enc_released

            self._encoder = _LgpioEncoder(
                cfg.GPIO_ENC_A, cfg.GPIO_ENC_B,
                cw_cb  = lambda: self._push(ButtonEvent.ENC_UP),
                ccw_cb = lambda: self._push(ButtonEvent.ENC_DOWN),
            )
            self._buttons = [btn_scan, btn_mode, btn_mem, btn_sq_up, btn_sq_dn, btn_enc_sw]

            log.info("GPIO initialisiert")
        except ImportError as e:
            log.warning("GPIO nicht verfügbar: %s", e)
        except Exception as e:
            log.warning("GPIO-Setup Fehler: %s", e)

    def _push(self, event_type: ButtonEvent, extra: dict | None = None):
        """Physischer GPIO-Event – wird im Startup-Fenster verworfen."""
        if time.monotonic() < self._ready_at:
            log.debug("Button-Event %s beim Start verworfen (GPIO noch instabil)",
                      event_type.name)
            return
        try:
            self._q.put_nowait(Event(type=event_type, extra=extra))
        except queue.Full:
            pass

    def inject(self, event_type: ButtonEvent, extra: dict | None = None):
        """Programmatischer Event (Web-UI, Menü) – umgeht das Startup-Fenster."""
        try:
            self._q.put_nowait(Event(type=event_type, extra=extra))
        except queue.Full:
            pass

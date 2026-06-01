# core/squelch.py
# Misst Signalstärke und entscheidet ob Squelch offen/zu ist

import time
import config.settings as cfg


class SquelchController:
    """
    Wertet den RSSI-Wert aus rtl_fm aus und
    öffnet/schließt den Squelch entsprechend.
    """

    def __init__(self):
        self.level: int  = cfg.SQUELCH_DEFAULT   # dBFS-Schwelle
        self.rssi: float = -120.0                 # zuletzt gemessener Wert
        self.open: bool  = False                  # ist Squelch aktuell offen?
        self.forced_open: bool = False            # Monitor-Taste gehalten → immer offen
        self._open_since: float = 0.0
        self._below_count: int = 0                # aufeinanderfolgende Chunks unter Schwelle

    # ── RSSI verarbeiten ──────────────────────────────────────────────────────

    def update(self, rssi: float):
        self.rssi = rssi
        if self.forced_open:
            self.open = True
            return
        if not self.open:
            if rssi > self.level:
                self.open = True
                self._open_since = time.monotonic()
                self._below_count = 0
        else:
            held = (time.monotonic() - self._open_since) >= cfg.SQUELCH_HOLD_TIME
            if held and rssi < (self.level - cfg.SQUELCH_HYSTERESIS):
                self._below_count += 1
                if self._below_count >= 3:   # 3 aufeinanderfolgende schlechte Chunks (~100 ms)
                    self.open = False
                    self._below_count = 0
            else:
                self._below_count = 0

    # ── Schwelle anpassen ─────────────────────────────────────────────────────

    def increase(self):
        self.level = min(0, self.level + cfg.SQUELCH_STEP)

    def decrease(self):
        self.level = max(-120, self.level - cfg.SQUELCH_STEP)

    # ── Statistik ─────────────────────────────────────────────────────────────

    @property
    def open_duration(self) -> float:
        """Sekunden seit Squelch geöffnet wurde."""
        if self.open:
            return time.monotonic() - self._open_since
        return 0.0

    @property
    def signal_bar(self) -> int:
        """Signal als 0–5 Balken relativ zur Squelch-Schwelle."""
        # 0 Balken = 30 dB unter Schwelle, 5 Balken = 20 dB über Schwelle
        low  = self.level - 30
        high = self.level + 20
        clamped = max(low, min(high, self.rssi))
        return round((clamped - low) / (high - low) * 5)

    def __str__(self):
        state = "OPEN" if self.open else "CLOSED"
        return f"SQ [{state}] RSSI={self.rssi:.0f} dBFS  thr={self.level} dBFS"

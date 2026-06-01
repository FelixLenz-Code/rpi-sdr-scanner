# core/frequency.py
# Verwaltet Kanäle, Gruppen und Speicherplätze

from dataclasses import dataclass, field
from typing import Optional
import config.settings as cfg


@dataclass
class Channel:
    name:  str
    freq:  int          # Hz
    mode:  str          # "NFM", "FM", "WFM", "AM"
    group:     str        = "Misc"
    gain:      float | None = None   # None = globaler AUDIO_SOFT_GAIN
    squelch:   int   | None = None   # None = cfg.SQUELCH_DEFAULT
    bandwidth: int   | None = None   # None = cfg.MODE_AUDIO_LPF[mode]
    is_temp: bool  = False

    @property
    def freq_mhz(self) -> str:
        return f"{self.freq / 1_000_000:.4f}"

    def __str__(self):
        return f"{self.name} ({self.freq_mhz} MHz {self.mode})"


class FrequencyManager:
    """
    Hält die Kanalliste, den aktuell aktiven Kanal und
    stellt Scan-Navigation bereit.
    """

    def __init__(self):
        self.channels: list[Channel] = []
        self.index: int = 0            # aktuell selektierter Kanal
        self.scan_index: int = 0       # Scan-Zeiger (unabhängig von index)
        self._load_defaults()

    # ── Init ──────────────────────────────────────────────────────────────────

    def _load_defaults(self):
        for ch in cfg.CHANNELS:
            self.channels.append(Channel(**ch))

    # ── Aktueller Kanal ───────────────────────────────────────────────────────

    @property
    def current(self) -> Optional[Channel]:
        if not self.channels:
            return None
        return self.channels[self.index]

    def select(self, index: int):
        if 0 <= index < len(self.channels):
            self.index = index
            self.scan_index = index

    def next(self):
        if self.channels:
            self.index = (self.index + 1) % len(self.channels)

    def prev(self):
        if self.channels:
            self.index = (self.index - 1) % len(self.channels)

    # ── Scan-Navigation ───────────────────────────────────────────────────────

    def scan_next(self) -> Optional[Channel]:
        if not self.channels:
            return None
        self.scan_index = (self.scan_index + 1) % len(self.channels)
        return self.channels[self.scan_index]

    # ── Kanal-Verwaltung ──────────────────────────────────────────────────────

    def add(self, channel: Channel) -> int:
        """Fügt Kanal ein und gibt dessen Index zurück."""
        self.channels.append(channel)
        return len(self.channels) - 1

    def remove(self, index: int):
        if 0 <= index < len(self.channels):
            self.channels.pop(index)
            self.index = min(self.index, len(self.channels) - 1)

    # ── Modus-Wechsel ─────────────────────────────────────────────────────────

    def cycle_mode(self):
        ch = self.current
        if ch:
            modes = cfg.MODES
            ch.mode = modes[(modes.index(ch.mode) + 1) % len(modes)]

    # ── Gruppen ───────────────────────────────────────────────────────────────

    def channels_by_group(self) -> dict[str, list[Channel]]:
        groups: dict[str, list[Channel]] = {}
        for ch in self.channels:
            groups.setdefault(ch.group, []).append(ch)
        return groups

    # ── Hilfsmethoden ─────────────────────────────────────────────────────────

    def __len__(self):
        return len(self.channels)

    def __iter__(self):
        return iter(self.channels)

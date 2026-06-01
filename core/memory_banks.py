# core/memory_banks.py
# 10 Memory-Bänke (Bank 0–9), jede mit Namen und eigener Kanalliste.
# Kanäle werden in SQLite persistiert – Bänke überleben einen Neustart.

import sqlite3
import threading
import time
import logging
from dataclasses import dataclass
from typing import Optional

import config.settings as cfg

log = logging.getLogger(__name__)

NUM_BANKS = 10


@dataclass
class MemoryChannel:
    id:      int
    bank:    int        # 0–9
    slot:    int        # Platz innerhalb der Bank (0-basiert)
    name:    str
    freq:    int        # Hz
    mode:    str
    group:   str
    gain:      float | None = None  # None = globaler AUDIO_SOFT_GAIN
    squelch:   int   | None = None  # None = cfg.SQUELCH_DEFAULT
    bandwidth: int   | None = None  # None = cfg.MODE_AUDIO_LPF[mode]

    @property
    def freq_mhz(self) -> str:
        return f"{self.freq / 1_000_000:.4f}"


class MemoryBanks:
    """
    Verwaltet 10 nummerierte Memory-Bänke analog zu echten Scannern.

    Bank-Wechsel: MENU-Druck → Bank-Select-Modus → Encoder dreht Bank
    Speichern:    MEM-Taster → aktiver Kanal geht in aktive Bank
    Abrufen:      ENC_PRESS im IDLE-Modus → springt zu gespeichertem Kanal

    Daten liegen in der gleichen SQLite-DB wie Bookmarks (anderer Tabellenname).
    """

    def __init__(self, db_conn: sqlite3.Connection):
        self._conn = db_conn
        self._lock = threading.RLock()   # schützt alle DB-Zugriffe gegen gleichzeitige Thread-Nutzung
        self._active_bank: int = 0
        self._bank_names: dict[int, str] = {i: f"Bank {i}" for i in range(NUM_BANKS)}
        self._init_schema()
        self._load_bank_names()

    # ── Schema ────────────────────────────────────────────────────────────────

    def _init_schema(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS memory_banks (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                bank    INTEGER NOT NULL CHECK(bank BETWEEN 0 AND 9),
                slot    INTEGER NOT NULL,
                name    TEXT NOT NULL,
                freq    INTEGER NOT NULL,
                mode    TEXT NOT NULL DEFAULT 'NFM',
                grp     TEXT NOT NULL DEFAULT 'Misc',
                locked  INTEGER NOT NULL DEFAULT 0,
                created REAL NOT NULL,
                UNIQUE(bank, slot)
            );

            CREATE TABLE IF NOT EXISTS bank_names (
                bank INTEGER PRIMARY KEY CHECK(bank BETWEEN 0 AND 9),
                name TEXT NOT NULL
            );
        """)
        self._conn.commit()
        # Migration: gain-Spalte nachrüsten falls noch nicht vorhanden
        try:
            self._conn.execute("ALTER TABLE memory_banks ADD COLUMN gain REAL DEFAULT NULL")
            self._conn.commit()
        except Exception:
            pass  # Spalte existiert bereits
        # Migration: squelch-Spalte nachrüsten falls noch nicht vorhanden
        try:
            self._conn.execute("ALTER TABLE memory_banks ADD COLUMN squelch INTEGER DEFAULT NULL")
            self._conn.commit()
        except Exception:
            pass  # Spalte existiert bereits
        # Migration: bandwidth-Spalte nachrüsten falls noch nicht vorhanden
        try:
            self._conn.execute("ALTER TABLE memory_banks ADD COLUMN bandwidth INTEGER DEFAULT NULL")
            self._conn.commit()
        except Exception:
            pass  # Spalte existiert bereits

    def _load_bank_names(self):
        rows = self._conn.execute("SELECT bank, name FROM bank_names").fetchall()
        for r in rows:
            self._bank_names[r[0]] = r[1]

    # ── Aktive Bank ───────────────────────────────────────────────────────────

    @property
    def active_bank(self) -> int:
        return self._active_bank

    @property
    def active_bank_name(self) -> str:
        return self._bank_names[self._active_bank]

    def set_active_bank(self, bank: int):
        if 0 <= bank < NUM_BANKS:
            self._active_bank = bank
            log.info("Memory-Bank gewechselt → %d (%s)", bank, self.active_bank_name)

    def next_bank(self):
        self.set_active_bank((self._active_bank + 1) % NUM_BANKS)

    def prev_bank(self):
        self.set_active_bank((self._active_bank - 1) % NUM_BANKS)

    def rename_bank(self, bank: int, name: str):
        if 0 <= bank < NUM_BANKS:
            self._bank_names[bank] = name
            with self._lock:
                self._conn.execute(
                    "INSERT OR REPLACE INTO bank_names (bank, name) VALUES (?,?)",
                    (bank, name),
                )
                self._conn.commit()

    # ── Kanäle speichern ──────────────────────────────────────────────────────

    def save(self, name: str, freq: int, mode: str, group: str = "Misc",
             bank: Optional[int] = None,
             gain: Optional[float] = None,
             squelch: Optional[int] = None,
             bandwidth: Optional[int] = None) -> "MemoryChannel":
        """
        Speichert einen Kanal in der aktiven (oder angegebenen) Bank.
        Findet automatisch den nächsten freien Slot.
        Existiert der Kanal (gleiche Freq+Mode) schon in der Bank, wird er aktualisiert.
        """
        b = bank if bank is not None else self._active_bank
        with self._lock:
            existing = self._conn.execute(
                "SELECT id, slot FROM memory_banks WHERE bank=? AND freq=? AND mode=?",
                (b, freq, mode),
            ).fetchone()

            if existing:
                slot = existing[1]
                self._conn.execute(
                    "UPDATE memory_banks SET name=?, grp=?, gain=?, squelch=?, bandwidth=? WHERE id=?",
                    (name, group, gain, squelch, bandwidth, existing[0]),
                )
            else:
                slot = self._next_free_slot(b)
                self._conn.execute(
                    """INSERT INTO memory_banks
                       (bank, slot, name, freq, mode, grp, locked, gain, squelch, bandwidth, created)
                       VALUES (?,?,?,?,?,?,0,?,?,?,?)""",
                    (b, slot, name, freq, mode, group, gain, squelch, bandwidth, time.time()),
                )

            self._conn.commit()
            log.info("Memory B%d/%d: %s @ %.4f MHz %s", b, slot, name, freq / 1e6, mode)
            return self.get(b, slot)

    def _next_free_slot(self, bank: int) -> int:
        row = self._conn.execute(                    # wird immer unter self._lock aufgerufen
            "SELECT MAX(slot) FROM memory_banks WHERE bank=?", (bank,)
        ).fetchone()
        return (row[0] + 1) if row[0] is not None else 0

    # ── Kanäle abrufen ────────────────────────────────────────────────────────

    def list_bank(self, bank: Optional[int] = None) -> list[MemoryChannel]:
        b = bank if bank is not None else self._active_bank
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, bank, slot, name, freq, mode, grp, gain, squelch, bandwidth "
                "FROM memory_banks WHERE bank=? ORDER BY slot",
                (b,),
            ).fetchall()
        return [self._row_to_ch(r) for r in rows]

    def get(self, bank: int, slot: int) -> Optional[MemoryChannel]:
        with self._lock:
            r = self._conn.execute(
                "SELECT id, bank, slot, name, freq, mode, grp, gain, squelch, bandwidth "
                "FROM memory_banks WHERE bank=? AND slot=?",
                (bank, slot),
            ).fetchone()
        return self._row_to_ch(r) if r else None

    def all_channels(self) -> list[MemoryChannel]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, bank, slot, name, freq, mode, grp, gain, squelch, bandwidth "
                "FROM memory_banks ORDER BY bank, slot"
            ).fetchall()
        return [self._row_to_ch(r) for r in rows]

    # ── Kanal umbenennen ──────────────────────────────────────────────────────

    def rename_channel(self, bank: int, slot: int, new_name: str) -> bool:
        """
        Benennt einen gespeicherten Kanal um.
        Gibt True zurück wenn erfolgreich, False wenn Kanal nicht gefunden.
        """
        new_name = new_name.strip()
        if not new_name:
            return False
        with self._lock:
            cur = self._conn.execute(
                "UPDATE memory_banks SET name=? WHERE bank=? AND slot=?",
                (new_name, bank, slot),
            )
            self._conn.commit()
        if cur.rowcount > 0:
            log.info("Kanal B%d/%d umbenannt → '%s'", bank, slot, new_name)
            return True
        return False

    def rename_channel_by_id(self, ch_id: int, new_name: str) -> bool:
        """Umbenennen anhand der Datenbank-ID (praktisch für Web-UI)."""
        new_name = new_name.strip()
        if not new_name:
            return False
        with self._lock:
            cur = self._conn.execute(
                "UPDATE memory_banks SET name=? WHERE id=?",
                (new_name, ch_id),
            )
            self._conn.commit()
        return cur.rowcount > 0

    def rename_by_freq(self, freq: int, mode: str, new_name: str,
                       bank: Optional[int] = None) -> bool:
        """
        Umbenennen anhand von Frequenz + Modus (praktisch vom Scanner aus:
        aktuelle Frequenz direkt umbenennen ohne vorher die ID zu kennen).
        """
        new_name = new_name.strip()
        if not new_name:
            return False
        b = bank if bank is not None else self._active_bank
        with self._lock:
            cur = self._conn.execute(
                "UPDATE memory_banks SET name=? WHERE bank=? AND freq=? AND mode=?",
                (new_name, b, freq, mode),
            )
            self._conn.commit()
        return cur.rowcount > 0

    def update_squelch(self, freq: int, mode: str, squelch: int,
                       bank: Optional[int] = None) -> bool:
        """Squelch-Pegel für einen gespeicherten Kanal aktualisieren."""
        b = bank if bank is not None else self._active_bank
        with self._lock:
            cur = self._conn.execute(
                "UPDATE memory_banks SET squelch=? WHERE bank=? AND freq=? AND mode=?",
                (squelch, b, freq, mode),
            )
            self._conn.commit()
        return cur.rowcount > 0

    def update_gain(self, freq: int, mode: str, gain: Optional[float],
                    bank: Optional[int] = None) -> bool:
        """Software-Gain für einen gespeicherten Kanal aktualisieren."""
        b = bank if bank is not None else self._active_bank
        with self._lock:
            cur = self._conn.execute(
                "UPDATE memory_banks SET gain=? WHERE bank=? AND freq=? AND mode=?",
                (gain, b, freq, mode),
            )
            self._conn.commit()
        return cur.rowcount > 0

    def update_bandwidth(self, freq: int, mode: str, bandwidth: Optional[int],
                         bank: Optional[int] = None) -> bool:
        """Audio-LPF-Bandbreite für einen gespeicherten Kanal aktualisieren."""
        b = bank if bank is not None else self._active_bank
        with self._lock:
            cur = self._conn.execute(
                "UPDATE memory_banks SET bandwidth=? WHERE bank=? AND freq=? AND mode=?",
                (bandwidth, b, freq, mode),
            )
            self._conn.commit()
        return cur.rowcount > 0

    def toggle_lock(self, bank: int, slot: int) -> bool:
        """Lock-Status umschalten. Gibt den neuen Lock-Status zurück."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT locked FROM memory_banks WHERE bank=? AND slot=?", (bank, slot)
            ).fetchone()
            if cur is None:
                return False
            new_state = 0 if cur[0] else 1
            self._conn.execute(
                "UPDATE memory_banks SET locked=? WHERE bank=? AND slot=?",
                (new_state, bank, slot),
            )
            self._conn.commit()
        return bool(new_state)

    # ── Kanäle löschen ────────────────────────────────────────────────────────

    def delete(self, bank: int, slot: int):
        with self._lock:
            self._conn.execute(
                "DELETE FROM memory_banks WHERE bank=? AND slot=?", (bank, slot)
            )
            self._conn.commit()

    # ── Bank-Übersicht ────────────────────────────────────────────────────────

    def bank_summary(self) -> list[dict]:
        """Für die UI: Liste aller Bänke mit Kanalzahl."""
        result = []
        with self._lock:
            for i in range(NUM_BANKS):
                count = self._conn.execute(
                    "SELECT COUNT(*) FROM memory_banks WHERE bank=?", (i,)
                ).fetchone()[0]
                result.append({
                    "bank":   i,
                    "name":   self._bank_names[i],
                    "count":  count,
                    "active": i == self._active_bank,
                })
        return result

    # ── Hilfsmethoden ─────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_ch(r) -> MemoryChannel:
        return MemoryChannel(
            id=r[0], bank=r[1], slot=r[2], name=r[3],
            freq=r[4], mode=r[5], group=r[6],
            gain=r[7],
            squelch=r[8]   if len(r) > 8  else None,
            bandwidth=r[9] if len(r) > 9  else None,
        )

    def __repr__(self):
        return (f"<MemoryBanks active={self._active_bank} "
                f"name='{self.active_bank_name}'>")

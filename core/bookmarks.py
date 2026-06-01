# core/bookmarks.py
# SQLite-Datenbank für Empfangs-Log + gemeinsame DB-Verbindung für Memory-Bänke

import sqlite3
import time
import logging
from dataclasses import dataclass

import config.settings as cfg

log = logging.getLogger(__name__)


@dataclass
class LogEntry:
    id:       int
    name:     str
    freq:     int
    mode:     str
    group:    str
    duration: float
    ts:       float


class BookmarkDB:
    """
    Öffnet die SQLite-Datenbank und stellt die gemeinsame Verbindung
    für BookmarkDB (Empfangs-Log) und MemoryBanks bereit.
    """

    def __init__(self, path: str = cfg.DB_PATH):
        self._path = path
        self.conn  = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS activity (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                name     TEXT,
                freq     INTEGER NOT NULL,
                mode     TEXT,
                grp      TEXT,
                duration REAL,
                ts       REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_activity_ts ON activity(ts);
        """)
        self.conn.commit()

    # ── Empfangs-Log ─────────────────────────────────────────────────────────

    def log_activity(self, name: str, freq: int, mode: str, group: str, duration: float):
        if not cfg.LOG_ACTIVITY:
            return
        self.conn.execute(
            "INSERT INTO activity (name, freq, mode, grp, duration, ts) VALUES (?,?,?,?,?,?)",
            (name, freq, mode, group, duration, time.time()),
        )
        self.conn.commit()

    def recent_activity(self, limit: int = 50) -> list[LogEntry]:
        rows = self.conn.execute(
            "SELECT * FROM activity ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
        return [
            LogEntry(id=r["id"], name=r["name"] or "", freq=r["freq"],
                     mode=r["mode"] or "", group=r["grp"] or "",
                     duration=r["duration"] or 0.0, ts=r["ts"])
            for r in rows
        ]

    def export_csv(self, path: str = "activity_export.csv"):
        import csv
        rows = self.recent_activity(limit=10000)
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "name", "freq_hz", "mode", "group", "duration_s", "timestamp"])
            for r in rows:
                w.writerow([r.id, r.name, r.freq, r.mode, r.group,
                             f"{r.duration:.1f}",
                             time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r.ts))])
        log.info("CSV exportiert: %s (%d Einträge)", path, len(rows))

    def close(self):
        self.conn.close()

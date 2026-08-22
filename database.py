"""SQLite wrapper to record motion events."""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from typing import List, Optional

LOG = logging.getLogger("security_camera.database")


class Database:
    def __init__(self, path: str):
        self.path = path
        self._conn: Optional[sqlite3.Connection] = None

    def initialize(self) -> None:
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                snapshot_path TEXT,
                motion_score INTEGER,
                notification_sent INTEGER DEFAULT 0
            )
            """
        )
        self._conn.commit()
        LOG.info("Database initialized at %s", self.path)

    def insert_event(self, timestamp: datetime, snapshot_path: Optional[str], motion_score: int) -> int:
        ts = timestamp.isoformat()
        try:
            cur = self._conn.cursor()
            cur.execute("INSERT INTO events (timestamp, snapshot_path, motion_score) VALUES (?, ?, ?)", (ts, snapshot_path, int(motion_score)))
            self._conn.commit()
            return cur.lastrowid
        except Exception:
            LOG.exception("Failed to insert event")
            return -1

    def get_recent_events(self, limit: int = 50) -> List[dict]:
        cur = self._conn.cursor()
        cur.execute("SELECT id, timestamp, snapshot_path, motion_score, notification_sent FROM events ORDER BY id DESC LIMIT ?", (limit,))
        out = []
        for row in cur.fetchall():
            out.append({
                "id": row[0],
                "timestamp": row[1],
                "snapshot_path": row[2],
                "motion_score": row[3],
                "notification_sent": bool(row[4]),
            })
        return out

    def close(self) -> None:
        try:
            if self._conn:
                self._conn.commit()
                self._conn.close()
        except Exception:
            LOG.exception("Error closing DB")

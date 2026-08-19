"""SQLite state store for collector checkpoints and heartbeats."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class SqliteStateStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS collector_heartbeat (
                    collector_name TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    last_beat_utc TEXT NOT NULL,
                    ticks_collected INTEGER DEFAULT 0,
                    errors INTEGER DEFAULT 0,
                    restarts INTEGER DEFAULT 0,
                    metadata_json TEXT
                );
                CREATE TABLE IF NOT EXISTS collector_checkpoint (
                    collector_name TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    updated_utc TEXT NOT NULL,
                    PRIMARY KEY (collector_name, key)
                );
                CREATE TABLE IF NOT EXISTS tick_index (
                    symbol TEXT NOT NULL,
                    timestamp_ms INTEGER NOT NULL,
                    file_path TEXT NOT NULL,
                    PRIMARY KEY (symbol, timestamp_ms)
                );
                CREATE TABLE IF NOT EXISTS gap_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    gap_start_ms INTEGER NOT NULL,
                    gap_end_ms INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_utc TEXT NOT NULL
                );
                """
            )

    def upsert_heartbeat(
        self,
        name: str,
        *,
        status: str,
        ticks_collected: int = 0,
        errors: int = 0,
        restarts: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO collector_heartbeat
                    (collector_name, status, last_beat_utc, ticks_collected, errors, restarts, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(collector_name) DO UPDATE SET
                    status=excluded.status,
                    last_beat_utc=excluded.last_beat_utc,
                    ticks_collected=excluded.ticks_collected,
                    errors=excluded.errors,
                    restarts=excluded.restarts,
                    metadata_json=excluded.metadata_json
                """,
                (
                    name,
                    status,
                    now,
                    ticks_collected,
                    errors,
                    restarts,
                    json.dumps(metadata or {}),
                ),
            )

    def get_heartbeat(self, name: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM collector_heartbeat WHERE collector_name = ?", (name,)
            ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["metadata"] = json.loads(d.pop("metadata_json") or "{}")
        return d

    def all_heartbeats(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM collector_heartbeat ORDER BY collector_name").fetchall()
        out = []
        for row in rows:
            d = dict(row)
            d["metadata"] = json.loads(d.pop("metadata_json") or "{}")
            out.append(d)
        return out

    def set_checkpoint(self, collector: str, key: str, value: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO collector_checkpoint (collector_name, key, value, updated_utc)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(collector_name, key) DO UPDATE SET
                    value=excluded.value, updated_utc=excluded.updated_utc
                """,
                (collector, key, value, now),
            )

    def get_checkpoint(self, collector: str, key: str, default: str = "") -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM collector_checkpoint WHERE collector_name=? AND key=?",
                (collector, key),
            ).fetchone()
        return row["value"] if row else default

    def register_tick(self, symbol: str, timestamp_ms: int, file_path: str) -> bool:
        """Return False if duplicate."""
        with self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO tick_index (symbol, timestamp_ms, file_path) VALUES (?, ?, ?)",
                    (symbol, timestamp_ms, file_path),
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def tick_exists(self, symbol: str, timestamp_ms: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM tick_index WHERE symbol=? AND timestamp_ms=?",
                (symbol, timestamp_ms),
            ).fetchone()
        return row is not None

    def enqueue_gap(self, symbol: str, gap_start_ms: int, gap_end_ms: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO gap_queue (symbol, gap_start_ms, gap_end_ms, status, created_utc)
                VALUES (?, ?, ?, 'pending', ?)
                """,
                (symbol, gap_start_ms, gap_end_ms, now),
            )

    def pending_gaps(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM gap_queue WHERE status='pending' ORDER BY id LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def mark_gap_done(self, gap_id: int) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE gap_queue SET status='done' WHERE id=?", (gap_id,))

"""ذخیره معاملات و slippage در SQLite."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PAPER_MAGIC = 234000

PAPER_TRADE_COLUMNS: tuple[str, ...] = (
    "id",
    "ticket",
    "time_open",
    "time_close",
    "symbol",
    "timeframe",
    "direction",
    "entry_price",
    "fill_price",
    "exit_price",
    "sl",
    "tp",
    "lot",
    "spread",
    "commission",
    "swap",
    "magic",
    "regime",
    "engine",
    "confidence",
    "probability",
    "risk_percent",
    "rr",
    "pnl",
    "pnl_r",
    "mae",
    "mfe",
    "duration_sec",
    "duration_bars",
    "exit_reason",
    "checksum",
    "model_checksum",
    "filter_profile",
    "fill_source",
    "status",
)


class TradeJournal:
    def __init__(self, base_dir: str | Path = ".") -> None:
        root = Path(base_dir)
        root.mkdir(parents=True, exist_ok=True)
        self._path = root / "data" / "trade_journal.db"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @property
    def path(self) -> Path:
        return self._path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS executions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    symbol TEXT,
                    timeframe TEXT,
                    direction TEXT,
                    lot REAL,
                    requested_price REAL,
                    fill_price REAL,
                    slippage_pips REAL,
                    sl REAL,
                    tp REAL,
                    ticket INTEGER,
                    success INTEGER,
                    message TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cycle_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    market TEXT,
                    state TEXT,
                    detail TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket INTEGER UNIQUE,
                    time_open TEXT NOT NULL,
                    time_close TEXT,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    fill_price REAL NOT NULL,
                    exit_price REAL,
                    sl REAL,
                    tp REAL,
                    lot REAL NOT NULL,
                    spread REAL,
                    commission REAL DEFAULT 0,
                    swap REAL DEFAULT 0,
                    magic INTEGER DEFAULT 234000,
                    regime TEXT,
                    engine TEXT,
                    confidence REAL,
                    probability REAL,
                    risk_percent REAL,
                    rr REAL,
                    pnl REAL,
                    pnl_r REAL,
                    mae REAL,
                    mfe REAL,
                    duration_sec INTEGER,
                    duration_bars INTEGER,
                    exit_reason TEXT,
                    checksum TEXT,
                    model_checksum TEXT,
                    filter_profile TEXT,
                    fill_source TEXT,
                    status TEXT NOT NULL DEFAULT 'open'
                )
                """
            )
            conn.commit()

    def log_execution(
        self,
        *,
        mode: str,
        symbol: str,
        timeframe: str,
        direction: str,
        lot: float,
        requested_price: float,
        fill_price: float | None,
        slippage_pips: float | None,
        sl: float | None,
        tp: float | None,
        ticket: int | None,
        success: bool,
        message: str = "",
    ) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO executions (
                    ts, mode, symbol, timeframe, direction, lot,
                    requested_price, fill_price, slippage_pips, sl, tp,
                    ticket, success, message
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    ts,
                    mode,
                    symbol,
                    timeframe,
                    direction,
                    lot,
                    requested_price,
                    fill_price,
                    slippage_pips,
                    sl,
                    tp,
                    ticket,
                    1 if success else 0,
                    message,
                ),
            )
            conn.commit()

    def open_paper_trade(
        self,
        *,
        ts_open: str,
        symbol: str,
        timeframe: str,
        direction: str,
        entry_price: float,
        fill_price: float,
        sl: float | None,
        tp: float | None,
        lot: float,
        spread: float,
        commission: float,
        swap: float,
        magic: int,
        regime: str,
        engine: str,
        confidence: float,
        probability: float,
        risk_percent: float | None,
        rr: float | None,
        checksum: str,
        model_checksum: str,
        filter_profile: str,
        fill_source: str,
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO paper_trades (
                    ticket, time_open, symbol, timeframe, direction,
                    entry_price, fill_price, sl, tp, lot, spread,
                    commission, swap, magic, regime, engine,
                    confidence, probability, risk_percent, rr,
                    checksum, model_checksum, filter_profile,
                    fill_source, status
                ) VALUES (NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'open')
                """,
                (
                    ts_open,
                    symbol,
                    timeframe,
                    direction,
                    entry_price,
                    fill_price,
                    sl,
                    tp,
                    lot,
                    spread,
                    commission,
                    swap,
                    magic,
                    regime,
                    engine,
                    confidence,
                    probability,
                    risk_percent,
                    rr,
                    checksum,
                    model_checksum,
                    filter_profile,
                    fill_source,
                ),
            )
            trade_id = int(cur.lastrowid)
            ticket = -trade_id
            conn.execute(
                "UPDATE paper_trades SET ticket=? WHERE id=?",
                (ticket, trade_id),
            )
            conn.commit()
            return trade_id

    def close_paper_trade(
        self,
        trade_id: int,
        *,
        ts_close: str,
        exit_price: float,
        exit_reason: str,
        pnl: float,
        pnl_r: float,
        duration_bars: int,
        duration_sec: int,
        mae: float,
        mfe: float,
        rr: float | None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE paper_trades SET
                    time_close=?,
                    exit_price=?,
                    exit_reason=?,
                    pnl=?,
                    pnl_r=?,
                    duration_bars=?,
                    duration_sec=?,
                    mae=?,
                    mfe=?,
                    rr=COALESCE(?, rr),
                    status='closed'
                WHERE id=? AND status='open'
                """,
                (
                    ts_close,
                    exit_price,
                    exit_reason,
                    pnl,
                    pnl_r,
                    duration_bars,
                    duration_sec,
                    mae,
                    mfe,
                    rr,
                    trade_id,
                ),
            )
            conn.commit()

    def get_paper_trade(self, trade_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM paper_trades WHERE id=?",
                (trade_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_open_paper_trade_ids(self) -> list[int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id FROM paper_trades WHERE status='open' ORDER BY id",
            ).fetchall()
        return [int(r["id"]) for r in rows]

    def list_completed_paper_trades(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM paper_trades
                WHERE status='closed'
                ORDER BY time_open
                """,
            ).fetchall()
        return [dict(r) for r in rows]

    def log_cycle(self, market: str, state: str, detail: str = "") -> None:
        ts = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO cycle_events (ts, market, state, detail) VALUES (?,?,?,?)",
                (ts, market, state, detail),
            )
            conn.commit()

    def paper_schema(self) -> dict[str, Any]:
        return {
            "table": "paper_trades",
            "columns": list(PAPER_TRADE_COLUMNS),
            "db_path": str(self._path),
        }

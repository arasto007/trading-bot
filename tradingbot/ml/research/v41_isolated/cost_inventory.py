"""Read-only inventory of possible real cost sources. Research only."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]


def _safe_count(path: Path) -> int:
    if not path.is_dir():
        return 0
    return sum(1 for p in path.rglob("*") if p.is_file())


def inspect_trade_journal(db_path: Path) -> dict[str, Any]:
    if not db_path.is_file() or db_path.stat().st_size <= 0:
        return {"present": False, "path": str(db_path), "size": 0}
    uri = f"file:{db_path.as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    out: dict[str, Any] = {
        "present": True,
        "path": str(db_path),
        "size_bytes": db_path.stat().st_size,
        "tables": tables,
        "counts": {},
    }
    for t in tables:
        try:
            out["counts"][t] = int(cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
        except sqlite3.Error as exc:
            out["counts"][t] = f"error:{exc}"
    if "executions" in tables:
        n = int(out["counts"].get("executions") or 0)
        modes = []
        if n:
            modes = [
                {
                    "mode": r[0],
                    "n": r[1],
                    "success": r[2],
                    "avg_slippage_pips": r[3],
                    "min_slippage_pips": r[4],
                    "max_slippage_pips": r[5],
                    "n_nonzero_slip": r[6],
                }
                for r in cur.execute(
                    """
                    SELECT mode, COUNT(*), SUM(success),
                           AVG(slippage_pips), MIN(slippage_pips), MAX(slippage_pips),
                           SUM(CASE WHEN slippage_pips IS NOT NULL AND slippage_pips != 0 THEN 1 ELSE 0 END)
                    FROM executions GROUP BY mode
                    """
                )
            ]
        symbols = []
        if n:
            symbols = [
                {"symbol": r[0], "n": r[1]}
                for r in cur.execute("SELECT symbol, COUNT(*) FROM executions GROUP BY symbol")
            ]
        samples = []
        if n:
            for r in cur.execute(
                """
                SELECT ts, mode, symbol, requested_price, fill_price, slippage_pips, success, message
                FROM executions ORDER BY id DESC LIMIT 5
                """
            ):
                samples.append(dict(r))
        out["executions"] = {"modes": modes, "symbols": symbols, "recent": samples}
        if n:
            live_rows = [
                dict(r)
                for r in cur.execute(
                    """
                    SELECT ts, symbol, requested_price, fill_price, slippage_pips, lot, direction
                    FROM executions WHERE mode='live' ORDER BY ts
                    """
                )
            ]
            slips = [float(r["slippage_pips"]) for r in live_rows if r.get("slippage_pips") is not None]
            out["executions"]["live_fills"] = {
                "n": len(live_rows),
                "n_with_slippage": len(slips),
                "rows": live_rows,
                "note": "entry slippage vs requested_price only; not round-trip; n too small for v41 cost model",
            }
    if "paper_trades" in tables:
        n = int(out["counts"].get("paper_trades") or 0)
        paper: dict[str, Any] = {"n": n}
        if n:
            cols = [r[1] for r in cur.execute("PRAGMA table_info(paper_trades)")]
            paper["columns"] = cols
            if "spread" in cols:
                paper["spread"] = dict(
                    zip(
                        ("avg", "min", "max", "n_nonnull"),
                        cur.execute(
                            "SELECT AVG(spread), MIN(spread), MAX(spread), SUM(CASE WHEN spread IS NOT NULL THEN 1 ELSE 0 END) FROM paper_trades"
                        ).fetchone(),
                    )
                )
            if "commission" in cols:
                paper["commission"] = dict(
                    zip(
                        ("avg", "min", "max"),
                        cur.execute("SELECT AVG(commission), MIN(commission), MAX(commission) FROM paper_trades").fetchone(),
                    )
                )
            paper["symbols"] = [
                {"symbol": r[0], "n": r[1]}
                for r in cur.execute("SELECT symbol, COUNT(*) FROM paper_trades GROUP BY symbol")
            ]
            paper["engines"] = [
                {"engine": r[0], "n": r[1]}
                for r in cur.execute("SELECT engine, COUNT(*) FROM paper_trades GROUP BY engine")
            ]
        out["paper_trades"] = paper
    con.close()
    return out


def inspect_live_logs(live_dir: Path) -> dict[str, Any]:
    if not live_dir.is_dir():
        return {"present": False}
    files = sorted(live_dir.iterdir(), key=lambda p: p.stat().st_size if p.is_file() else 0, reverse=True)
    names = [{"name": p.name, "bytes": p.stat().st_size if p.is_file() else 0} for p in files if p.is_file()]
    # Peek one kernel/decision line for spread/slippage keys without loading the 500MB file.
    peek: dict[str, Any] = {}
    for candidate in ("decisions.jsonl", "kernel_decisions.jsonl", "fallback_events.jsonl"):
        path = live_dir / candidate
        if not path.is_file() or path.stat().st_size == 0:
            continue
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            line = fh.readline()
        peek[candidate] = {"first_line_len": len(line), "keys": sorted(json.loads(line).keys()) if line.strip().startswith("{") else None}
        if peek[candidate]["keys"]:
            keys = set(peek[candidate]["keys"])
            peek[candidate]["has_spread"] = bool(keys & {"spread", "spread_pips", "bid", "ask", "slippage", "slippage_pips"})
    return {"present": True, "files": names[:25], "peek": peek}


def run_inventory() -> dict[str, Any]:
    from tradingbot.ml.data.paths import events_dir, news_dir, sessions_dir, spread_dir, ticks_dir

    return {
        "phase": "1.5.46",
        "offline_only": True,
        "raw_stores": {
            "spread_files": _safe_count(spread_dir()),
            "tick_files": _safe_count(ticks_dir()),
            "session_files": _safe_count(sessions_dir()),
            "event_files": _safe_count(events_dir()),
            "news_files": _safe_count(news_dir()),
            "spread_dir": str(spread_dir()),
            "tick_dir": str(ticks_dir()),
        },
        "trade_journal": inspect_trade_journal(ROOT / "data" / "trade_journal.db"),
        "trade_journal_empty_root": inspect_trade_journal(ROOT / "trade_journal.db"),
        "phase26c_journal": inspect_trade_journal(
            ROOT / "tradingbot" / "ml" / "research" / "phase26c" / "validation_trade_journal.db"
        ),
        "live_logs": inspect_live_logs(ROOT / "data" / "ml" / "live"),
        "sqlite_other": {
            "position_state.db": (ROOT / "data" / "position_state.db").stat().st_size
            if (ROOT / "data" / "position_state.db").is_file()
            else 0,
            "trading_bot.db": (ROOT / "data" / "trading_bot.db").stat().st_size
            if (ROOT / "data" / "trading_bot.db").is_file()
            else 0,
        },
        "backtest_cache_files": _safe_count(ROOT / "data" / "backtest"),
    }


if __name__ == "__main__":
    print(json.dumps(run_inventory(), indent=2, default=str))

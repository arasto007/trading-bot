#!/usr/bin/env python3
"""Demo proof progress toward real-money readiness (8-week gate)."""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

TARGET_TRADES = 50
TARGET_WEEKS = 8
MIN_PF = 1.0


def _journal_stats() -> dict[str, object]:
    db = ROOT / "data" / "trade_journal.db"
    out: dict[str, object] = {
        "executions_ok": 0,
        "first_trade_utc": None,
        "last_trade_utc": None,
        "gross_profit": 0.0,
        "gross_loss": 0.0,
    }
    if not db.is_file():
        return out
    with sqlite3.connect(db) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT COUNT(DISTINCT ticket)
            FROM executions
            WHERE success = 1 AND mode = 'live'
              AND ticket IS NOT NULL AND ticket > 100000
            """
        )
        row = cur.fetchone()
        if row and row[0]:
            out["executions_ok"] = int(row[0])
            cur.execute(
                """
                SELECT ts FROM executions
                WHERE success = 1 AND mode = 'live'
                  AND ticket IS NOT NULL AND ticket > 100000
                ORDER BY ts ASC LIMIT 1
                """
            )
            first = cur.fetchone()
            cur.execute(
                """
                SELECT ts FROM executions
                WHERE success = 1 AND mode = 'live'
                  AND ticket IS NOT NULL AND ticket > 100000
                ORDER BY ts DESC LIMIT 1
                """
            )
            last = cur.fetchone()
            if first:
                out["first_trade_utc"] = first[0]
            if last:
                out["last_trade_utc"] = last[0]

        cur.execute(
            """
            SELECT pnl FROM paper_trades
            WHERE pnl IS NOT NULL AND status = 'closed'
            """
        )
        pnls = [float(r[0]) for r in cur.fetchall() if r[0] is not None]
    if pnls:
        out["gross_profit"] = sum(p for p in pnls if p > 0)
        out["gross_loss"] = abs(sum(p for p in pnls if p < 0))
    return out


def _watchdog_clean_exits(hours: int = 24) -> int:
    path = ROOT / "logs" / "watchdog.log"
    if not path.is_file():
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    count = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "Unexpected clean exit" not in line:
            continue
        ts_raw = line.split("|", 1)[0].strip()
        try:
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts >= cutoff:
            count += 1
    return count


def main() -> int:
    stats = _journal_stats()
    n = int(stats["executions_ok"])
    gp = float(stats["gross_profit"])
    gl = float(stats["gross_loss"])
    pf = (gp / gl) if gl > 0 else (999.0 if gp > 0 else 0.0)

    first = stats["first_trade_utc"]
    weeks_elapsed = 0.0
    if first:
        try:
            t0 = datetime.fromisoformat(str(first).replace("Z", "+00:00"))
            if t0.tzinfo is None:
                t0 = t0.replace(tzinfo=timezone.utc)
            weeks_elapsed = (datetime.now(timezone.utc) - t0).total_seconds() / (
                7 * 86400
            )
        except ValueError:
            pass

    clean_exits = _watchdog_clean_exits(24)
    checks = {
        "trades_50": n >= TARGET_TRADES,
        "weeks_8": weeks_elapsed >= TARGET_WEEKS,
        "pf_ok": pf >= MIN_PF if (gp > 0 or gl > 0) else n >= 1,
        "stable_uptime": clean_exits == 0,
    }
    passed = sum(1 for v in checks.values() if v)

    report = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "executions_ok": n,
        "target_trades": TARGET_TRADES,
        "weeks_elapsed": round(weeks_elapsed, 2),
        "target_weeks": TARGET_WEEKS,
        "profit_factor": round(pf, 2),
        "unexpected_clean_exits_24h": clean_exits,
        "checks": checks,
        "ready_for_real_money_review": all(checks.values()),
    }
    out_path = ROOT / "logs" / "demo_proof_status.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("=== Demo Proof Status ===")
    print(f"  Trades: {n}/{TARGET_TRADES} {'OK' if checks['trades_50'] else 'pending'}")
    print(f"  Weeks:  {weeks_elapsed:.1f}/{TARGET_WEEKS} {'OK' if checks['weeks_8'] else 'pending'}")
    print(f"  PF:     {pf:.2f} (min {MIN_PF}) {'OK' if checks['pf_ok'] else 'pending'}")
    print(f"  Uptime: unexpected clean exits (24h)={clean_exits} {'OK' if checks['stable_uptime'] else 'WARN'}")
    print(f"  Gates passed: {passed}/4")
    print(f"  Real-money review: {'READY' if report['ready_for_real_money_review'] else 'NOT YET'}")
    print(f"  Report: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

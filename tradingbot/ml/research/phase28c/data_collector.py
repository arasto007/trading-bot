"""Phase 28C — collect live paper trade data from production journal."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.research.phase26a.journal_reader import read_completed_paper_trades, read_paper_executions
from tradingbot.services.exit_mode import resolve_exit_mode
from tradingbot.services.trade_journal import TradeJournal

MIN_TRADES = 200
MIN_DAYS = 14
PREFERRED_DAYS = 30

REQUIRED_ENV = {
    "TRADINGBOT_PAPER": "1",
    "TRADINGBOT_EXIT_MODE": "HYBRID_B",
    "USE_ML_KERNEL": "1",
    "ALLOW_LEGACY_FALLBACK": "0",
}


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(timezone.utc)


def collect_paper_data(base_dir: Path) -> dict[str, Any]:
    journal_path = base_dir / "data" / "trade_journal.db"
    trades = read_completed_paper_trades(base_dir)
    executions = read_paper_executions(base_dir)
    open_ids: list[int] = []
    if journal_path.is_file():
        open_ids = TradeJournal(base_dir).list_open_paper_trade_ids()

    env_status = {k: os.getenv(k, "") for k in REQUIRED_ENV}
    env_ok = all(
        env_status.get("TRADINGBOT_PAPER", "").lower() in ("1", "true", "yes")
        and env_status.get("TRADINGBOT_EXIT_MODE", "").upper() in ("HYBRID_B", "HYBRIDB")
        for _ in [0]
    ) and env_status.get("USE_ML_KERNEL", "").lower() in ("1", "true", "yes")

    period_days = 0.0
    if trades:
        opens = [_parse_ts(t["time_open"]) for t in trades if t.get("time_open")]
        closes = [_parse_ts(t["time_close"]) for t in trades if t.get("time_close")]
        if opens and closes:
            period_days = round((max(closes) - min(opens)).total_seconds() / 86400, 2)

    return {
        "phase": "28C",
        "journal_path": str(journal_path),
        "journal_exists": journal_path.is_file(),
        "completed_trades": len(trades),
        "open_trades": len(open_ids),
        "executions": len(executions),
        "period_days": period_days,
        "min_trades_required": MIN_TRADES,
        "min_days_required": MIN_DAYS,
        "preferred_days": PREFERRED_DAYS,
        "env_status": env_status,
        "env_hybrid_b_paper": env_ok,
        "exit_mode_resolved": resolve_exit_mode().value,
        "trades": trades,
        "execution_rows": executions,
    }

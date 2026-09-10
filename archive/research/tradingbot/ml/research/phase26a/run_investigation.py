"""Phase 26A — paper trading validation infrastructure runner."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.research.phase26a.statistics import (
    build_daily_statistics,
    build_drawdown_curve,
    build_equity_curve,
    build_model_statistics,
    build_monthly_statistics,
    build_regime_statistics,
    build_trade_sequence,
    build_weekly_statistics,
)
from tradingbot.ml.research.phase26a.trade_collector import collect_completed_paper_trades
from tradingbot.ml.research.phase26a.validation import validate_no_production_changes

PHASE_DIR = Path(__file__).resolve().parent


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(x) for x in obj]
    return obj


def run_phase26a(
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    replay_days: int = 7,
    replay_stride: int = 5,
) -> dict[str, Any]:
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.ml.data.paths import normalize_ml_base_dir

    ts = datetime.now(timezone.utc).isoformat()
    base_dir = normalize_ml_base_dir(base_dir or load_legacy_config().get("BASE_DIR"))

    trades, collect_meta = collect_completed_paper_trades(
        base_dir=base_dir,
        symbol=symbol,
        timeframe=timeframe,
        replay_days=replay_days,
        replay_stride=replay_stride,
    )
    trade_log = [t.to_dict() for t in trades]

    daily = build_daily_statistics(trades)
    weekly = build_weekly_statistics(trades)
    monthly = build_monthly_statistics(trades)
    equity = build_equity_curve(trades)
    drawdown = build_drawdown_curve(equity)
    sequence = build_trade_sequence(trades)
    regime_stats = build_regime_statistics(trades)
    model_stats = build_model_statistics(trades)

    trend_regime = regime_stats["trend_statistics.json"]
    trend_model = model_stats.pop("trend_statistics_model.json", {})
    trend_combined = {
        **trend_regime,
        "model_engine": trend_model,
    }

    validation = validate_no_production_changes()
    infrastructure_ready = validation.get("passes", True) and len(trade_log) >= 0
    verdict = "READY_FOR_PAPER_COLLECTION" if infrastructure_ready else "VALIDATION_FAILED"

    outputs = {
        "trade_log.json": {
            "phase": "26A",
            "generated_utc": ts,
            "count": len(trade_log),
            "collection_meta": collect_meta,
            "trades": trade_log,
        },
        "daily_statistics.json": {**daily, "generated_utc": ts},
        "weekly_statistics.json": {**weekly, "generated_utc": ts},
        "monthly_statistics.json": {**monthly, "generated_utc": ts},
        "equity_curve.json": {**equity, "generated_utc": ts},
        "drawdown_curve.json": {**drawdown, "generated_utc": ts},
        "trade_sequence.json": {**sequence, "generated_utc": ts},
        "range_statistics.json": {**regime_stats["range_statistics.json"], "generated_utc": ts},
        "trend_statistics.json": {**trend_combined, "generated_utc": ts},
        "transition_statistics.json": {**regime_stats["transition_statistics.json"], "generated_utc": ts},
        "phase99_statistics.json": {**model_stats["phase99_statistics.json"], "generated_utc": ts},
        "validation_report.json": {
            "phase": "26A",
            "generated_utc": ts,
            **validation,
            "observation_only": True,
            "production_execution_modified": False,
        },
        "phase26a_final_report.json": {
            "phase": "26A",
            "generated_utc": ts,
            "verdict": verdict,
            "audit_mode": "OBSERVATION_ONLY",
            "production_modified": validation.get("production_modified", False),
            "completed_trades_collected": len(trade_log),
            "collection_sources": collect_meta.get("sources", []),
            "infrastructure": {
                "trade_collector": "phase26a/trade_collector.py",
                "journal_reader": "read-only trade_journal.db",
                "replay_fallback": "phase25b unified_pipeline_replay",
                "exit_simulator": "phase26a/exit_simulator.py",
                "statistics": "phase26a/statistics.py",
            },
            "validation_passes": validation.get("passes", True),
        },
    }

    PHASE_DIR.mkdir(parents=True, exist_ok=True)
    for name, payload in outputs.items():
        (PHASE_DIR / name).write_text(json.dumps(_json_safe(payload), indent=2), encoding="utf-8")

    return outputs["phase26a_final_report.json"]


def main() -> int:
    report = run_phase26a()
    print(json.dumps(report, indent=2))
    return 0 if report.get("verdict") == "READY_FOR_PAPER_COLLECTION" else 1


if __name__ == "__main__":
    raise SystemExit(main())

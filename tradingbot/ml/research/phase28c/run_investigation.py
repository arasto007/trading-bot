"""Phase 28C — paper trading live validation runner (read-only observation)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.research.phase28c.data_collector import MIN_TRADES, collect_paper_data
from tradingbot.ml.research.phase28c.metrics import (
    build_backtest_vs_live,
    build_daily_statistics,
    build_execution_quality,
    build_performance_metrics,
    determine_verdict,
    load_backtest_baseline,
)
from tradingbot.ml.research.phase28c.validators import (
    build_failure_monitoring,
    build_journal_integrity,
    validate_entry_parity,
    validate_hybrid_exit,
)

PROJECT_ROOT = Path(__file__).resolve().parents[4]
PHASE_DIR = Path(__file__).resolve().parent
PHASE27F_CACHE = PHASE_DIR.parent / "phase27f" / "_cache" / "replay_records.json"


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(x) for x in obj]
    if isinstance(obj, float) and (obj != obj or obj in (float("inf"), float("-inf"))):
        return str(obj)
    return obj


def _write(name: str, payload: dict[str, Any]) -> None:
    (PHASE_DIR / name).write_text(json.dumps(_json_safe(payload), indent=2), encoding="utf-8")


def _load_replay_index() -> dict[str, dict[str, Any]]:
    if not PHASE27F_CACHE.is_file():
        return {}
    records = json.loads(PHASE27F_CACHE.read_text(encoding="utf-8"))
    index: dict[str, dict[str, Any]] = {}
    for rec in records:
        if not rec.get("execution_success"):
            continue
        ts = str(rec.get("timestamp") or "")[:19]
        index[f"XAUUSD:M5:{ts}"] = rec
    return index


def _load_candles(base_dir: Path, symbol: str, timeframe: str) -> pd.DataFrame:
    raw = CandleStore(base_dir).load(symbol, timeframe)
    if raw is None or raw.empty:
        return pd.DataFrame()
    frame = raw.copy()
    if not isinstance(frame.index, pd.DatetimeIndex):
        if "time" in frame.columns:
            frame = frame.set_index("time")
    frame.index = pd.DatetimeIndex(pd.to_datetime(frame.index, utc=True))
    return frame.sort_index()


def run_phase28c(*, base_dir: str | Path | None = None) -> dict[str, Any]:
    ts = datetime.now(timezone.utc).isoformat()
    root = Path(base_dir or PROJECT_ROOT)
    PHASE_DIR.mkdir(parents=True, exist_ok=True)

    collected = collect_paper_data(root)
    trades = collected.pop("trades")
    executions = collected.pop("execution_rows")

    hybrid_validations: list[dict[str, Any]] = []
    entry_parities: list[dict[str, Any]] = []
    replay_index = _load_replay_index()

    if trades:
        candles_cache: dict[str, pd.DataFrame] = {}
        for trade in trades:
            sym = str(trade.get("symbol") or "XAUUSD")
            tf = str(trade.get("timeframe") or "M5")
            key = f"{sym}:{tf}"
            if key not in candles_cache:
                candles_cache[key] = _load_candles(root, sym, tf)
            frame = candles_cache[key]
            if not frame.empty:
                hybrid_validations.append(validate_hybrid_exit(trade, frame))
            entry_parities.append(validate_entry_parity(trade, replay_index))

    journal_integrity = build_journal_integrity(trades, open_count=collected.get("open_trades", 0))
    failure_monitoring = build_failure_monitoring(trades, hybrid_validations, journal_integrity)
    performance = build_performance_metrics(trades)
    execution_quality = build_execution_quality(trades, executions)
    daily_stats = build_daily_statistics(trades)
    baseline = load_backtest_baseline()
    backtest_vs_live = build_backtest_vs_live(performance, baseline)
    performance_comparison = {
        "phase": "28C",
        "live": performance,
        "backtest_baseline": baseline,
        "backtest_vs_live": backtest_vs_live,
        "generated_utc": ts,
    }

    verdict, blockers = determine_verdict(
        trade_count=len(trades),
        period_days=float(collected.get("period_days") or 0),
        failure_monitoring=failure_monitoring,
        backtest_vs_live=backtest_vs_live,
        hybrid_validations=hybrid_validations,
    )

    paper_trade_log = {
        "phase": "28C",
        "trade_count": len(trades),
        "trades": trades,
        "collection_meta": collected,
        "generated_utc": ts,
    }

    hybrid_exit_validation = {
        "phase": "28C",
        "validations": hybrid_validations,
        "valid_count": sum(1 for h in hybrid_validations if h.get("hybrid_valid")),
        "partial_close_count": sum(1 for h in hybrid_validations if h.get("partial_close_expected")),
        "entry_parities": entry_parities,
        "generated_utc": ts,
    }

    final = {
        "phase": "28C",
        "verdict": verdict,
        "audit_mode": "READ_ONLY",
        "production_modified": False,
        "observation_only": True,
        "trade_count": len(trades),
        "min_trades_required": MIN_TRADES,
        "period_days": collected.get("period_days"),
        "journal_exists": collected.get("journal_exists"),
        "env_hybrid_b_paper": collected.get("env_hybrid_b_paper"),
        "blockers": blockers,
        "next_step": (
            "Run paper trading with TRADINGBOT_PAPER=1 TRADINGBOT_EXIT_MODE=HYBRID_B for 14-30 days"
            if verdict == "INSUFFICIENT_SAMPLE"
            else "Review failure_monitoring and backtest_vs_live"
        ),
        "conclusion": f"Phase 28C verdict: {verdict}. Trades observed: {len(trades)}.",
        "generated_utc": ts,
    }

    outputs = {
        "paper_trade_log.json": paper_trade_log,
        "execution_quality.json": {**execution_quality, "generated_utc": ts},
        "hybrid_exit_validation.json": hybrid_exit_validation,
        "daily_statistics.json": {**daily_stats, "generated_utc": ts},
        "performance_comparison.json": performance_comparison,
        "backtest_vs_live.json": {**backtest_vs_live, "generated_utc": ts},
        "failure_monitoring.json": {**failure_monitoring, "generated_utc": ts},
        "journal_integrity.json": {**journal_integrity, "generated_utc": ts},
        "phase28c_final_report.json": final,
    }
    for name, payload in outputs.items():
        _write(name, payload)

    return final


def main() -> int:
    report = run_phase28c()
    print(json.dumps(report, indent=2))
    return 0 if report.get("verdict") == "HYBRID_B_VALIDATED_FOR_LIVE" else 1


if __name__ == "__main__":
    raise SystemExit(main())

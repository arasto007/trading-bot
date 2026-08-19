"""Phase 28D — fresh 30-day production backtest ($200, Hybrid B)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.adapters.legacy_loader import load_legacy_config
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.research.phase25b.unified_pipeline_replay import run_unified_pipeline_replay
from tradingbot.ml.research.phase28d.cache import clear_replay_caches
from tradingbot.ml.research.phase28d.metrics import (
    INITIAL_BALANCE,
    build_backtest_summary,
    build_daily_statistics,
    build_direction_analysis,
    build_engine_analysis,
    build_equity_curves,
    build_execution_quality,
    build_final_report,
    build_hybrid_exit_statistics,
    build_monthly_statistics,
    build_performance_metrics,
    build_pipeline_verification,
    build_regime_analysis,
    build_risk_analysis,
    build_session_analysis,
    build_trade_statistics,
    build_weekly_statistics,
    determine_verdict,
)
from tradingbot.accounting.metrics import compute_performance_metrics as accounting_performance_metrics
from tradingbot.ml.research.phase28d.trade_builder import trades_from_replay_meta
from tradingbot.ml.research.regime_router.phase99_feature_validation import normalize_candles_for_builder

PROJECT_ROOT = Path(__file__).resolve().parents[4]
PHASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = PHASE_DIR / "_cache"

WARMUP_BARS = 300
WINDOW_DAYS = 30


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


def _generate_reports(
    records: list[dict[str, Any]],
    meta: dict[str, Any],
    *,
    ts: str,
    root: Path,
) -> dict[str, Any]:
    from tradingbot.ml.data.stores.candle_store import CandleStore

    raw = CandleStore(root).load("XAUUSD", "M5")
    window = prepare_calibration_candles(raw, days=WINDOW_DAYS) if raw is not None else None
    if window is not None:
        window = normalize_candles_for_builder(window)

    trades = trades_from_replay_meta(meta) if meta else []
    if not trades and meta and meta.get("accounting"):
        trades = list((meta.get("accounting") or {}).get("trades") or [])
    print(f"[phase28d] completed trades: {len(trades)}")

    perf = build_performance_metrics(trades, initial=INITIAL_BALANCE)
    trade_stats = build_trade_statistics(trades)
    curves = build_equity_curves(trades, initial=INITIAL_BALANCE)
    pipeline = build_pipeline_verification(records)

    verdict, explanation = determine_verdict(perf, trades)
    final = build_final_report(verdict=verdict, explanation=explanation, perf=perf, trade_stats=trade_stats, meta=meta)
    final["generated_utc"] = ts
    final["pipeline_verification"] = pipeline

    outputs = {
        "backtest_summary.json": {**build_backtest_summary(perf, trade_stats, meta), "generated_utc": ts},
        "trade_log.json": {"phase": "28D", "trades": trades, "trade_count": len(trades), "generated_utc": ts},
        "daily_statistics.json": {**build_daily_statistics(trades), "generated_utc": ts},
        "weekly_statistics.json": {**build_weekly_statistics(trades), "generated_utc": ts},
        "monthly_statistics.json": {**build_monthly_statistics(trades, perf), "generated_utc": ts},
        "direction_analysis.json": {**build_direction_analysis(trades), "generated_utc": ts},
        "session_analysis.json": {**build_session_analysis(trades), "generated_utc": ts},
        "regime_analysis.json": {**build_regime_analysis(trades), "generated_utc": ts},
        "engine_analysis.json": {**build_engine_analysis(trades), "generated_utc": ts},
        "risk_analysis.json": {**build_risk_analysis(trades, meta), "generated_utc": ts},
        "execution_quality.json": {**build_execution_quality(trades, records), "generated_utc": ts},
        "equity_curve.json": {"phase": "28D", "curve": curves["equity_curve"], "generated_utc": ts},
        "balance_curve.json": {"phase": "28D", "curve": curves["balance_curve"], "generated_utc": ts},
        "drawdown_curve.json": {"phase": "28D", "curve": curves["drawdown_curve"], "generated_utc": ts},
        "trade_sequence.json": {"phase": "28D", "sequence": curves["trade_sequence"], "generated_utc": ts},
        "hybrid_exit_statistics.json": {**build_hybrid_exit_statistics(trades), "generated_utc": ts},
        "performance_metrics.json": {**perf, "trade_statistics": trade_stats, "generated_utc": ts},
        "phase28d_final_report.json": final,
    }
    for name, payload in outputs.items():
        _write(name, payload)
    return final


def run_phase28d(*, base_dir: str | Path | None = None, force_replay: bool = False) -> dict[str, Any]:
    ts = datetime.now(timezone.utc).isoformat()
    root = Path(base_dir or PROJECT_ROOT)
    PHASE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    removed = clear_replay_caches() if force_replay or not (CACHE_DIR / "replay_records.json").is_file() else []
    if removed:
        print(f"[phase28d] cleared {len(removed)} cache files")

    cache_records = CACHE_DIR / "replay_records.json"
    cache_meta = CACHE_DIR / "replay_meta.json"
    if not force_replay and cache_records.is_file() and cache_meta.is_file():
        print("[phase28d] using fresh replay cache from prior run")
        records = json.loads(cache_records.read_text(encoding="utf-8"))
        meta = json.loads(cache_meta.read_text(encoding="utf-8"))
        return _generate_reports(records, meta, ts=ts, root=root)

    os.environ["TRADINGBOT_PAPER"] = "1"
    os.environ["TRADINGBOT_EXIT_MODE"] = "HYBRID_B"
    os.environ["USE_ML_KERNEL"] = "1"
    os.environ["ALLOW_LEGACY_FALLBACK"] = "0"

    legacy = load_legacy_config()
    legacy["BASE_DIR"] = str(root)
    legacy["initial_balance"] = INITIAL_BALANCE

    print("[phase28d] running fresh 30-day production replay (HYBRID_B, $200)...")
    records, meta = run_unified_pipeline_replay(
        base_dir=str(root),
        symbol="XAUUSD",
        timeframe="M5",
        tail_only=None,
        days=WINDOW_DAYS,
        stride=1,
        warmup_bars=WARMUP_BARS,
        use_forming_bar_adapter=True,
        legacy_config=legacy,
        exit_mode="HYBRID_B",
    )
    meta["initial_balance"] = INITIAL_BALANCE
    meta["exit_mode"] = "HYBRID_B"
    meta["caches_cleared"] = removed
    meta["generated_utc"] = ts

    (CACHE_DIR / "replay_records.json").write_text(json.dumps(records), encoding="utf-8")
    meta_light = {k: v for k, v in meta.items() if k not in ("portfolio_timeline", "position_lifecycle")}
    (CACHE_DIR / "replay_meta.json").write_text(json.dumps(meta_light), encoding="utf-8")

    return _generate_reports(records, meta_light, ts=ts, root=root)


def main() -> int:
    report = run_phase28d()
    print(json.dumps(report, indent=2))
    return 0 if report.get("verdict") == "PROFITABLE" else 1


if __name__ == "__main__":
    raise SystemExit(main())

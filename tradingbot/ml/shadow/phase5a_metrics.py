"""Phase 5A — ML Kernel certification metrics (shadow analysis only)."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.shadow.phase49a_metrics import (
    _bucket_metrics,
    _precision,
    build_trade_records,
    load_shadow_events,
)
from tradingbot.ml.shadow.phase5a_drift import analyze_drift

MIN_SAMPLE = 100
PF_GATE = 1.2
EXPECTANCY_GATE = 0.15
PRECISION_GATE = 60.0


def _pf_num(pf: Any) -> float:
    if pf in ("inf", float("inf")):
        return 999.0
    return float(pf)


def classify_bucket(record: dict[str, Any]) -> str:
    ml_dir = str(record.get("ml_prediction_direction", "HOLD")).upper()
    live_dir = str(record.get("live_engine_direction", record.get("direction", "HOLD"))).upper()
    if ml_dir in ("BUY", "SELL") and ml_dir == live_dir:
        return "agree"
    if ml_dir in ("BUY", "SELL") and ml_dir != live_dir:
        return "disagree"
    return "neutral"


def load_shadow_trade_records(
    *,
    events: list[dict[str, Any]] | None = None,
    allow_replay_backfill: bool = True,
    df: Any | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """
    Load closed shadow_trade_record rows.

    Returns (records, data_source) where data_source is live_shadow | shadow_replay.
    """
    rows = events if events is not None else load_shadow_events()
    records = build_trade_records(rows)
    live_records = [r for r in records if r.get("event") == "shadow_trade_record" or "final_trade_R" in r]
    if len(live_records) >= MIN_SAMPLE:
        return live_records, "live_shadow"

    if not allow_replay_backfill:
        return live_records, "live_shadow"

    if df is None:
        from tradingbot.backtest.config import BacktestConfig
        from tradingbot.backtest.data_source import BacktestMarketData

        cfg = BacktestConfig(symbols=["XAUUSD"], timeframe="M5", days=95, warmup=500, use_cache=True)
        md = BacktestMarketData(cfg)
        md.load()
        df = md.frame("XAUUSD")

    from tradingbot.ml.shadow.phase5a_shadow_replay import build_replay_shadow_trade_records

    replay = build_replay_shadow_trade_records(df)
    if len(replay) >= len(live_records):
        return replay, "shadow_replay"
    return live_records, "live_shadow"


def compute_phase5a_metrics(
    records: list[dict[str, Any]] | None = None,
    *,
    allow_replay_backfill: bool = True,
    df: Any | None = None,
) -> dict[str, Any]:
    if records is None:
        records, data_source = load_shadow_trade_records(
            allow_replay_backfill=allow_replay_backfill,
            df=df,
        )
    else:
        data_source = "provided"

    agree = [r for r in records if classify_bucket(r) == "agree"]
    disagree = [r for r in records if classify_bucket(r) == "disagree"]
    neutral = [r for r in records if classify_bucket(r) == "neutral"]

    live_m = _bucket_metrics(records)
    agree_m = _bucket_metrics(agree)
    disagree_m = _bucket_metrics(disagree)
    neutral_m = _bucket_metrics(neutral)

    precision_buy = _precision(records, "BUY")
    precision_sell = _precision(records, "SELL")

    drift = analyze_drift(records)

    sample = len(records)
    agree_pf = _pf_num(agree_m["pf"])
    live_pf = _pf_num(live_m["pf"])
    disagree_pf = _pf_num(disagree_m["pf"])

    certified = (
        sample >= MIN_SAMPLE
        and agree_pf > PF_GATE
        and float(agree_m["expectancy_r"]) > EXPECTANCY_GATE
        and precision_buy > PRECISION_GATE
        and precision_sell > PRECISION_GATE
        and disagree_pf < live_pf
        and not drift.get("drift_detected", True)
    )

    # Rejection distribution for quality engine style reporting
    buckets = {"agree": len(agree), "disagree": len(disagree), "neutral": len(neutral)}
    total_b = sum(buckets.values()) or 1
    top_bucket_pct = round(max(buckets.values()) / total_b * 100, 2)

    return {
        "sample_size": sample,
        "data_source": data_source,
        "live_pf": live_m["pf"],
        "live_expectancy_r": live_m["expectancy_r"],
        "live_max_dd_r": _max_dd(records),
        "buckets": {
            "ml_agrees_with_pa": {**agree_m, "precision_buy_pct": _precision(agree, "BUY"), "precision_sell_pct": _precision(agree, "SELL")},
            "ml_disagrees_with_pa": disagree_m,
            "ml_neutral": neutral_m,
        },
        "bucket_counts": buckets,
        "bucket_concentration_pct": top_bucket_pct,
        "precision_buy_pct": precision_buy,
        "precision_sell_pct": precision_sell,
        "drift": drift,
        "drift_detected": drift.get("drift_detected", True),
        "min_sample": MIN_SAMPLE,
        "ml_kernel_live_ready": certified,
        "keep_shadow_mode": not certified,
        "trade_records": records,
    }


def _max_dd(records: list[dict[str, Any]]) -> float:
    eq = peak = mdd = 0.0
    for r in records:
        val = float(r.get("final_trade_R", 0))
        eq += val
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    return round(mdd, 2)


def format_phase5a_result(metrics: dict[str, Any]) -> str:
    agree = metrics.get("buckets", {}).get("ml_agrees_with_pa", {})
    disagree = metrics.get("buckets", {}).get("ml_disagrees_with_pa", {})
    drift = metrics.get("drift_detected", True)
    ready = metrics.get("ml_kernel_live_ready")
    lines = [
        "PHASE_5A_RESULT",
        f"SAMPLE_SIZE={metrics.get('sample_size', 0)}",
        f"AGREE_PF={agree.get('pf', 0)}",
        f"AGREE_EXPECTANCY_R={agree.get('expectancy_r', 0)}",
        f"DISAGREE_PF={disagree.get('pf', 0)}",
        f"PRECISION_BUY={metrics.get('precision_buy_pct', 0)}",
        f"PRECISION_SELL={metrics.get('precision_sell_pct', 0)}",
        f"DRIFT_DETECTED={'YES' if drift else 'NO'}",
        f"ML_KERNEL_LIVE_READY={'YES' if ready else 'NO'}",
        f"KEEP_SHADOW_MODE={'NO' if ready else 'YES'}",
    ]
    return "\n".join(lines)

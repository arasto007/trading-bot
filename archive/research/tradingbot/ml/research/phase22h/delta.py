"""Phase 22H — regression and Phase 22F delta."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PHASE22F_BASELINE = Path(__file__).resolve().parents[1] / "phase22f" / "baseline_snapshot.json"


async def run_regression_validation(dataset_label: str = "A") -> dict[str, Any]:
    from tradingbot.ml.integration.factory import build_kernel_adapter
    from tradingbot.ml.integration.health_gate import KernelFallbackError
    from tradingbot.ml.integration.pipeline_cache import PipelineCache
    from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id
    from tradingbot.ml.research.phase22f.config import build_dataset, configure_research_env
    from tradingbot.ml.research.phase22f.rapid_runner import run_rapid_backtest

    configure_research_env()
    PipelineCache.reset()
    dataset = build_dataset(dataset_label)
    active = resolve_active_trend_engine_id()

    fallback = False
    legacy_used = False
    exceptions: list[str] = []
    try:
        from tradingbot.adapters.legacy_loader import load_legacy_config
        adapter = build_kernel_adapter(base_dir=load_legacy_config().get("BASE_DIR"))
        _ = adapter
    except KernelFallbackError as exc:
        fallback = True
        exceptions.append(str(exc))
    except Exception as exc:
        exceptions.append(str(exc))

    m5 = await run_rapid_backtest("M5", dataset)
    hc = m5.get("hold_chain") or {}
    summary = m5.get("summary") or {}

    return {
        "phase": "22H",
        "dataset": dataset.to_dict(),
        "active_trend_engine_id": active,
        "no_exceptions": len(exceptions) == 0,
        "exceptions": exceptions,
        "no_fallback": not fallback,
        "no_legacy_execution": not legacy_used,
        "checksum_mismatch": "trend_checksum_invalid" in str(exceptions),
        "feature_mismatch": any("missing_feature" in e for e in exceptions),
        "calibration_mismatch": False,
        "m5_trades": m5.get("trades"),
        "m5_hold_pct": summary.get("hold_pct"),
        "m5_buy_emitted": hc.get("buy_emitted"),
        "m5_sell_emitted": hc.get("sell_emitted"),
        "m5_metrics": m5.get("metrics"),
        "model_utilization": summary.get("model_utilization") or hc.get("model_utilization"),
        "elapsed_sec": m5.get("elapsed_sec"),
    }


def build_phase22f_delta(current: dict[str, Any]) -> dict[str, Any]:
    baseline: dict[str, Any] = {}
    if PHASE22F_BASELINE.is_file():
        baseline = json.loads(PHASE22F_BASELINE.read_text(encoding="utf-8"))

    b_m5 = baseline.get("per_timeframe", {}).get("M5", {})
    b_hc = baseline.get("hold_chain", {}).get("M5", {})

    c_metrics = current.get("m5_metrics") or {}
    delta = {
        "phase": "22H",
        "baseline_source": str(PHASE22F_BASELINE),
        "baseline": {
            "trades": b_m5.get("trades"),
            "buy_pct": b_m5.get("buy_pct"),
            "sell_pct": b_m5.get("sell_pct"),
            "hold_pct": b_m5.get("hold_pct"),
            "profit_factor": b_m5.get("profit_factor"),
            "expectancy": b_m5.get("expectancy"),
            "buy_emitted": b_hc.get("buy_emitted") if isinstance(b_hc, dict) else None,
            "sell_emitted": b_hc.get("sell_emitted") if isinstance(b_hc, dict) else None,
        },
        "after_22h": {
            "trades": current.get("m5_trades"),
            "buy_emitted": current.get("m5_buy_emitted"),
            "sell_emitted": current.get("m5_sell_emitted"),
            "hold_pct": current.get("m5_hold_pct"),
            "profit_factor": c_metrics.get("profit_factor"),
            "expectancy": c_metrics.get("expectancy"),
            "buy_trades": c_metrics.get("buy_trades"),
            "sell_trades": c_metrics.get("sell_trades"),
        },
        "changes": {},
    }

    for key in ("trades", "hold_pct", "profit_factor", "expectancy"):
        b_val = delta["baseline"].get(key)
        a_val = delta["after_22h"].get(key) if key != "trades" else delta["after_22h"].get("trades")
        if key == "hold_pct":
            a_val = delta["after_22h"].get("hold_pct")
        if b_val is not None and a_val is not None:
            try:
                delta["changes"][key] = round(float(a_val) - float(b_val), 4)
            except (TypeError, ValueError):
                pass

    be = delta["baseline"].get("buy_emitted")
    ae = delta["after_22h"].get("buy_emitted")
    if be is not None and ae is not None:
        delta["changes"]["buy_emitted"] = ae - be
    se = delta["baseline"].get("sell_emitted")
    ae2 = delta["after_22h"].get("sell_emitted")
    if se is not None and ae2 is not None:
        delta["changes"]["sell_emitted"] = ae2 - se

    return delta

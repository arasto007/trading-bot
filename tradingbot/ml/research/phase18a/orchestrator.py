"""Phase 18A — live shadow validation orchestrator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.research.phase18a.config import DEFAULT_DAYS, DEFAULT_STRIDE, DEFAULT_WARMUP, reports_dir
from tradingbot.ml.research.phase18a.divergence import cluster_divergences
from tradingbot.ml.research.phase18a.regime_validation import build_regime_split_validation
from tradingbot.ml.research.phase18a.safety import evaluate_bundle_safety
from tradingbot.ml.research.phase18a.shadow_runner import run_shadow_comparison
from tradingbot.ml.research.phase18a.statistics import build_shadow_statistics
from tradingbot.ml.research.phase18a.verdict import build_checks, build_final_report, determine_verdict


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def run_phase18a_shadow_validation(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = DEFAULT_DAYS,
    stride: int = DEFAULT_STRIDE,
    warmup: int = DEFAULT_WARMUP,
    base_dir: str | None = None,
    run_stride1: bool = True,
) -> dict[str, Any]:
    out = reports_dir(base_dir)
    out.mkdir(parents=True, exist_ok=True)

    candles = CandleStore(base_dir).load(symbol, timeframe)
    dataset = DatasetStore(base_dir).load_v2(symbol, timeframe)
    if candles is None or candles.empty:
        raise FileNotFoundError("candles_unavailable")
    if dataset is None or dataset.empty:
        raise FileNotFoundError("dataset_unavailable")

    safety = evaluate_bundle_safety(base_dir=base_dir)
    if not safety.get("passed"):
        final = {
            "phase": "18A",
            "verdict": "SHADOW_FAILED",
            "reason": "bundle_safety_failed",
            "safety": safety,
        }
        _write_json(out / "phase18a_final_report.json", final)
        return {"verdict": "SHADOW_FAILED", "reports_dir": str(out), "final_report": final}

    print(f"phase18a: shadow comparison stride={stride} days={days} ...", flush=True)
    primary = run_shadow_comparison(
        candles, dataset,
        base_dir=base_dir, symbol=symbol, timeframe=timeframe,
        days=days, stride=stride, warmup=warmup,
    )

    stride1_run = None
    if run_stride1 and stride != 1:
        print("phase18a: stability check stride=1 ...", flush=True)
        stride1_run = run_shadow_comparison(
            candles, dataset,
            base_dir=base_dir, symbol=symbol, timeframe=timeframe,
            days=days, stride=1, warmup=warmup,
        )

    stats = build_shadow_statistics(primary=primary, stride1=stride1_run)
    regime = build_regime_split_validation(primary)
    latency = primary["latency"].to_dict()
    comparator = primary["comparator"]

    # Required reports
    _write_json(out / "shadow_trade_log.json", primary["logger"].to_dict())
    _write_json(out / "v40_vs_v41_decision_diff.json", comparator.decision_diff_report())
    _write_json(out / "agreement_matrix.json", comparator.agreement_matrix())
    _write_json(out / "divergence_clusters.json", cluster_divergences(comparator.diffs))
    _write_json(out / "equity_curve_v40.json", primary["equity_v40"].to_dict())
    _write_json(out / "equity_curve_v41.json", primary["equity_v41"].to_dict())
    _write_json(out / "latency_profile.json", latency)
    _write_json(out / "regime_split_validation.json", regime)

    required = (
        "shadow_trade_log.json",
        "v40_vs_v41_decision_diff.json",
        "agreement_matrix.json",
        "divergence_clusters.json",
        "equity_curve_v40.json",
        "equity_curve_v41.json",
        "latency_profile.json",
        "regime_split_validation.json",
    )
    reports_present = all((out / name).is_file() for name in required)

    checks = build_checks(
        stats=stats,
        safety=safety,
        regime=regime,
        reports_present=reports_present,
    )
    verdict = determine_verdict(checks)
    final = build_final_report(
        verdict=verdict,
        checks=checks,
        stats=stats,
        safety=safety,
        regime=regime,
        latency=latency,
    )
    # Post-run safety: confirm bundles unchanged
    safety_after = evaluate_bundle_safety(base_dir=base_dir)
    final["safety_after"] = safety_after
    final["checksums_unchanged"] = (
        safety.get("v40_checksum", {}).get("bundle_sha256")
        == safety_after.get("v40_checksum", {}).get("bundle_sha256")
        and safety.get("v41_checksum", {}).get("bundle_sha256")
        == safety_after.get("v41_checksum", {}).get("bundle_sha256")
    )
    _write_json(out / "phase18a_final_report.json", final)

    return {
        "verdict": verdict,
        "reports_dir": str(out),
        "final_report": final,
        "checks": checks,
        "stats": stats,
    }

"""Phase 13.2 — regime research report writers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import phase13_2_reports_dir


def write_reports(
    *,
    regime_report: dict[str, Any],
    confusion: dict[str, Any],
    feature_importance: dict[str, Any],
    model_comparison: dict[str, Any],
    base_dir: str | Path | None = None,
) -> dict[str, str]:
    out = phase13_2_reports_dir(base_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {
        "regime_report": _write(out / "regime_report.json", regime_report),
        "regime_confusion_matrix": _write(out / "regime_confusion_matrix.json", confusion),
        "regime_feature_importance": _write(out / "regime_feature_importance.json", feature_importance),
        "regime_model_comparison": _write(out / "regime_model_comparison.json", model_comparison),
    }
    return {k: str(v) for k, v in paths.items()}


def build_regime_report(
    *,
    symbol: str,
    timeframe: str,
    seed: int,
    dataset_fingerprint: str,
    fingerprint_unchanged: bool,
    feature_rows: int,
    baseline: dict[str, Any],
    best_model: str,
    validation_summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "phase": "13.2",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "timeframe": timeframe,
        "seed": seed,
        "dataset_fingerprint": dataset_fingerprint,
        "fingerprint_unchanged": fingerprint_unchanged,
        "feature_rows": feature_rows,
        "regime_labels": ["RANGE", "TREND", "HIGH_VOLATILITY", "NO_TRADE"],
        "rule_baseline": baseline,
        "best_model": best_model,
        "validation": validation_summary,
        "range_detection": _regime_check(baseline, "RANGE"),
        "trend_detection": _regime_check(baseline, "TREND"),
        "high_volatility_detection": _regime_check(baseline, "HIGH_VOLATILITY"),
        "no_trade_detection": _regime_check(baseline, "NO_TRADE"),
        "connected_to_live_trading": False,
        "phase9_9_modified": False,
    }


def _regime_check(baseline: dict[str, Any], regime: str) -> dict[str, Any]:
    dist = baseline.get("distribution", {})
    count = int(dist.get(regime, 0))
    total = max(1, int(baseline.get("total_samples", 1)))
    return {
        "regime": regime,
        "samples": count,
        "pct": round(count / total, 4),
        "validated": count > 0,
    }


def _write(path: Path, payload: dict[str, Any]) -> Path:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path

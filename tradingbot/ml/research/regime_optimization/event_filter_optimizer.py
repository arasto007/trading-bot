"""Phase 9.6 — event filter optimization research."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.data.paths import event_filter_report_path
from tradingbot.ml.research.regime_optimization.regime_utils import (
    EVENT_SCHEMES,
    apply_event_filter,
    trading_metrics_from_labels,
)


def run_event_filter_optimization(df: pd.DataFrame) -> dict[str, Any]:
    """Evaluate event filter schemes A–E on resolved-label rows."""
    results: list[dict[str, Any]] = []
    for scheme_id, _events in EVENT_SCHEMES.items():
        subset = apply_event_filter(df, scheme_id)
        if subset.empty:
            continue
        metrics = trading_metrics_from_labels(subset["label"].astype(int).to_numpy())
        results.append(
            {
                "scheme": scheme_id,
                "event_filter": list(_events) if _events else "all",
                "samples": len(subset),
                **metrics,
            }
        )

    ranked = sorted(results, key=lambda r: (-r["expectancy"], -r["profit_factor_proxy"]))
    return {
        "phase": "9.6",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "schemes_tested": list(EVENT_SCHEMES.keys()),
        "results": results,
        "best_scheme": ranked[0]["scheme"] if ranked else None,
        "ranked_by_expectancy": [r["scheme"] for r in ranked],
    }


def save_event_filter_report(df: pd.DataFrame, base_dir: str | Path | None = None) -> Path:
    report = run_event_filter_optimization(df)
    path = event_filter_report_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path

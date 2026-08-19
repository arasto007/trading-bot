"""Phase 9.6 — market regime detection and analysis."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.data.paths import regime_analysis_report_path
from tradingbot.ml.dataset.schema import Label
from tradingbot.ml.research.regime_optimization.regime_utils import (
    REGIMES,
    assign_market_regime,
    trading_metrics_from_labels,
)

EVENT_TYPES = ("order_block", "choch", "liquidity_sweep", "fvg", "bos", "session_transition")


def run_regime_analysis(df: pd.DataFrame) -> dict[str, Any]:
    """Classify regimes and measure edge per regime and event."""
    work = df.copy()
    work["market_regime"] = assign_market_regime(work)
    y = work["label"].astype(int).to_numpy()

    by_regime: list[dict[str, Any]] = []
    for regime in REGIMES:
        mask = work["market_regime"] == regime
        subset = work.loc[mask]
        if subset.empty:
            continue
        metrics = trading_metrics_from_labels(subset["label"].astype(int).to_numpy())
        best_event = "none"
        best_wr = 0.0
        for event in EVENT_TYPES:
            ev = subset.loc[subset["event_type"] == event]
            if len(ev) < 5:
                continue
            wr = float((ev["label"] == int(Label.TP_FIRST)).mean())
            if wr > best_wr:
                best_wr = wr
                best_event = event
        by_regime.append(
            {
                "regime": regime,
                "sample_count": len(subset),
                "win_rate": metrics["win_rate"],
                "expectancy": metrics["expectancy"],
                "profit_factor_proxy": metrics["profit_factor_proxy"],
                "best_event": best_event,
                "best_event_win_rate": round(best_wr, 4),
            }
        )

    ranked = sorted(by_regime, key=lambda r: (-r["expectancy"], -r["win_rate"]))
    return {
        "phase": "9.6",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "regimes": list(REGIMES),
        "by_regime": by_regime,
        "best_regime": ranked[0]["regime"] if ranked else None,
        "worst_regime": ranked[-1]["regime"] if ranked else None,
    }


def save_regime_analysis_report(df: pd.DataFrame, base_dir: str | Path | None = None) -> Path:
    report = run_regime_analysis(df)
    path = regime_analysis_report_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path

"""Phase 11.5 — read-only model comparison (no production changes)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import (
    phase9_6_model_metadata_path,
    phase9_6_optimization_report_path,
    phase9_9_metadata_path,
    paper_trading_final_report_path,
)


def compare_models(
    *,
    paper_run_id: str = "phase11_v1",
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    p99_meta = _load_json(phase9_9_metadata_path(base_dir))
    p96_report = _load_json(phase9_6_optimization_report_path(base_dir))
    p96_meta = _load_json(phase9_6_model_metadata_path(base_dir))
    p11 = _load_json(paper_trading_final_report_path(paper_run_id, base_dir))

    p11_perf = (p11 or {}).get("performance", {}).get("trading", {})
    p96_perf = (p96_report or {}).get("metrics", {}).get("trading", {})

    models = [
        {
            "name": "phase9_9_logistic",
            "type": "LogisticRegression",
            "production": True,
            "frozen": True,
            "comparable": True,
            "walk_forward_expectancy": p11_perf.get("expectancy_r"),
            "profit_factor": p11_perf.get("profit_factor"),
            "win_rate": p11_perf.get("win_rate"),
            "max_drawdown": p11_perf.get("max_drawdown"),
            "source": "phase11_paper_30d",
            "dataset_fingerprint": p99_meta.get("dataset_fingerprint"),
            "robustness_score": p99_meta.get("robustness_score"),
        },
        {
            "name": "phase9_6_xgboost",
            "type": "XGBoost",
            "production": False,
            "frozen": True,
            "comparable": False,
            "note": "Historical regime-optimization backtest — not re-run on Phase 11 paper window",
            "walk_forward_expectancy": p96_perf.get("expectancy"),
            "profit_factor": p96_perf.get("profit_factor"),
            "win_rate": p96_perf.get("win_rate"),
            "max_drawdown": p96_perf.get("drawdown"),
            "source": "phase9_6_optimization_report",
            "dataset_fingerprint": (p96_report or {}).get("dataset", {}).get("fingerprint"),
            "metadata": p96_meta,
        },
        {
            "name": "baseline_legacy",
            "type": "priceaction_only",
            "production": False,
            "comparable": False,
            "note": "Kernel legacy strategy without ML lift — not directly comparable",
        },
    ]

    comparable = [m for m in models if m.get("comparable") and m.get("profit_factor") is not None]
    winner = max(
        comparable,
        key=lambda x: float(x.get("profit_factor", 0)),
        default=models[0],
    )
    p11_pf = float(p11_perf.get("profit_factor", 0) or 0)

    return {
        "models": models,
        "phase9_9_still_best": winner.get("name") == "phase9_9_logistic" and p11_pf >= 1.0,
        "winner_among_comparable": winner.get("name"),
        "recommendation": (
            "Keep Phase 9.9 frozen for Phase 12"
            if winner.get("name") == "phase9_9_logistic" and p11_pf >= 1.0
            else "Phase 9.9 paper PF below 1.0 — review thresholds before Phase 12"
            if p11_pf < 1.0
            else f"Research suggests reviewing {winner.get('name')} — no production change applied"
        ),
        "artifacts_readonly": True,
    }


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))

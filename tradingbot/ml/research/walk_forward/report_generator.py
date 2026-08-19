"""Phase 9.8 — walk-forward report persistence."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import (
    phase9_8_robustness_report_path,
    phase9_8_walk_forward_report_path,
    phase9_8_window_results_path,
)
from tradingbot.ml.research.walk_forward.walk_forward_metrics import aggregate_window_metrics, summarize_for_report


def save_reports(
    *,
    symbol: str,
    timeframe: str,
    seed: int,
    windows: list[dict[str, Any]],
    aggregate: dict[str, Any],
    robustness: dict[str, Any],
    integrity: dict[str, Any],
    configuration: dict[str, Any],
    base_dir: str | Path | None = None,
) -> dict[str, Path]:
    reports_root = phase9_8_walk_forward_report_path(base_dir).parent
    reports_root.mkdir(parents=True, exist_ok=True)

    active = [w for w in windows if not w.get("skipped")]
    final_verdict = "PASS" if len(active) >= 4 and integrity.get("status") == "PASS" else "FAIL"

    main_report = {
        "phase": "9.8",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol.upper(),
        "timeframe": timeframe.upper(),
        "seed": seed,
        "configuration": configuration,
        "integrity": integrity,
        "windows": summarize_for_report(active, aggregate),
        "mean_metrics": aggregate.get("mean_metrics", {}),
        "stability_score": aggregate.get("stability_score", {}),
        "robustness_score": robustness.get("robustness_score", 0.0),
        "overfitting_risk": robustness.get("overfitting_risk", "HIGH"),
        "final_verdict": final_verdict,
        "final_decision": robustness.get("final_decision", "NEEDS MORE RESEARCH"),
        "shuffle": False,
    }

    window_results = {
        "phase": "9.8",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "window_count": len(windows),
        "active_windows": len(active),
        "windows": windows,
        "aggregate": aggregate,
    }

    robustness_report = {
        "phase": "9.8",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        **robustness,
        "final_verdict": final_verdict,
    }

    paths = {
        "walk_forward": phase9_8_walk_forward_report_path(base_dir),
        "window_results": phase9_8_window_results_path(base_dir),
        "robustness": phase9_8_robustness_report_path(base_dir),
    }
    paths["walk_forward"].write_text(json.dumps(main_report, indent=2, ensure_ascii=False), encoding="utf-8")
    paths["window_results"].write_text(json.dumps(window_results, indent=2, ensure_ascii=False), encoding="utf-8")
    paths["robustness"].write_text(json.dumps(robustness_report, indent=2, ensure_ascii=False), encoding="utf-8")
    return paths


def load_walk_forward_report(base_dir: str | Path | None = None) -> dict[str, Any]:
    path = phase9_8_walk_forward_report_path(base_dir)
    if not path.is_file():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))

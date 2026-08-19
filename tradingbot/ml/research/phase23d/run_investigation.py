#!/usr/bin/env python3
"""Phase 23D — execution filter validation report (read-only)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

OUT = Path(__file__).resolve().parent


def _write(name: str, payload: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  saved {name}", flush=True)


def main() -> int:
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.ml.data.paths import normalize_ml_base_dir
    from tradingbot.ml.research.phase23d.filter_validation_research import run_investigation

    now = datetime.now(timezone.utc).isoformat()
    base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
    result = run_investigation(base_dir=base_dir)

    for key, fname in (
        ("filter_history", "filter_history.json"),
        ("filter_ownership", "filter_ownership.json"),
        ("original_validation", "original_validation.json"),
        ("empirical_filter_analysis", "empirical_filter_analysis.json"),
        ("counterfactual_analysis", "counterfactual_analysis.json"),
        ("false_block_analysis", "false_block_analysis.json"),
        ("regime_analysis", "regime_analysis.json"),
        ("dependency_analysis", "dependency_analysis.json"),
        ("root_cause_report", "root_cause_report.json"),
        ("repair_design", "repair_design.json"),
    ):
        _write(fname, {**result[key], "generated_utc": now})

    emp = result["empirical_filter_analysis"]
    cf = result["counterfactual_analysis"]
    final = {
        "phase": "23D",
        "title": "Execution Filter Validation & Scientific Evaluation",
        "generated_utc": now,
        "verdict": result["verdict"],
        "range_pipeline_actionable_tail": emp.get("tail_300_bars", {}).get("pipeline_actionable_range_signals"),
        "filter_blocked_tail": emp.get("tail_300_bars", {}).get("filter_blocked"),
        "counterfactual_tail_delta_pf": cf.get("tail_300_bars", {}).get("delta_pf"),
        "false_blocks_tail": result["false_block_analysis"].get("tail_300_bars", {}).get(
            "false_blocks_winner_would_have_traded"
        ),
        "summary": result["root_cause_report"].get("summary"),
    }
    _write("phase23d_final_report.json", final)
    print(json.dumps({"verdict": result["verdict"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Phase 22AI — acceptance patch regression + freeze bridge prototype."""

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
    from tradingbot.ml.research.phase22ai.acceptance_regression import run_investigation

    now = datetime.now(timezone.utc).isoformat()
    base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))

    print("Running Phase 22AI acceptance patch + freeze bridge prototype...", flush=True)
    result = run_investigation(base_dir=base_dir)

    deliverables = (
        ("acceptance_patch_diff", "acceptance_patch_diff.json"),
        ("candidate_before_after", "candidate_before_after.json"),
        ("freeze_contract_validation", "freeze_contract_validation.json"),
        ("authority_check", "authority_check.json"),
    )
    for key, fname in deliverables:
        payload = {**result[key], "generated_utc": now, "production_modified": False}
        _write(fname, payload)

    final = {
        "phase": "22AI",
        "title": "Acceptance Patch + Freeze Bridge Prototype",
        "generated_utc": now,
        "production_modified": False,
        "runtime_modified": False,
        "artifact_replaced": False,
        "verdict": result["verdict"],
        "summary": (
            "Numeric mean_auc_gap acceptance patch applied in report_generator.py (fail-closed). "
            f"Regression: {result['candidate_before_after']['before']['accepted_count']} → "
            f"{result['candidate_before_after']['after']['accepted_count']} accepted candidates. "
            "Freeze bridge prototype emits FreezeContract JSON only with acceptance guards."
        ),
        "patch_target": "tradingbot/ml/research/robustness_optimizer/report_generator.py",
        "freeze_bridge": "tradingbot/ml/research/robustness_optimizer/freeze_bridge.py",
        "new_pass_candidates": result["candidate_before_after"]["new_pass_candidates"],
        "accepted_contract_count": result["freeze_contract_validation"]["contracts_built"],
        "authority_chain_valid": result["authority_check"]["authority_chain_valid"],
    }
    _write("phase22ai_final_report.json", final)

    print(json.dumps({"verdict": result["verdict"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

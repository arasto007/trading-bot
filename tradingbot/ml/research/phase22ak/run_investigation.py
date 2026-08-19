#!/usr/bin/env python3
"""Phase 22AK — controlled end-to-end model freeze execution."""

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
    from tradingbot.ml.research.phase22ak.freeze_execution import run_freeze_execution

    now = datetime.now(timezone.utc).isoformat()
    base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
    result = run_freeze_execution(base_dir=base_dir, run_optimizer=True)

    for key, fname in (
        ("optimizer_execution_report", "optimizer_execution_report.json"),
        ("winner_resolution_report", "winner_resolution_report.json"),
        ("freeze_execution_report", "freeze_execution_report.json"),
        ("artifact_before_after", "artifact_before_after.json"),
        ("runtime_validation", "runtime_validation.json"),
        ("backup_validation", "backup_validation.json"),
    ):
        _write(fname, {**result[key], "generated_utc": now})

    final = {
        "phase": "22AK",
        "title": "Controlled End-to-End Model Freeze Execution",
        "generated_utc": now,
        "verdict": result["verdict"],
        "old_candidate": result["artifact_before_after"].get("old_frozen_candidate"),
        "new_candidate": result["artifact_before_after"].get("new_frozen_candidate"),
        "production_winner": result["winner_resolution_report"].get("production_winner_experiment_id"),
        "backup_location": result["backup_validation"].get("backup_path"),
        "summary": (
            "Full Phase 9.9 optimizer executed with ACCEPTANCE_PASS_HIGHEST_COMPOSITE authority. "
            "Artifacts backed up, contract-driven freeze applied, runtime bundle validated."
        ),
    }
    _write("phase22ak_final_report.json", final)
    print(json.dumps({"verdict": result["verdict"]}, indent=2))
    return 0 if result["verdict"] == "MODEL_FROZEN_SUCCESSFULLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Phase 22AE — freeze decision forensics (repository only)."""

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
    from tradingbot.ml.research.phase22ae.freeze_forensics import run_investigation

    now = datetime.now(timezone.utc).isoformat()
    base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))

    print("Running Phase 22AE freeze decision forensics...", flush=True)
    result = run_investigation(base_dir=base_dir)

    mapping = (
        ("freeze_trace", "freeze_trace.json"),
        ("default_config_trace", "default_config_trace.json"),
        ("optimizer_connection", "optimizer_connection.json"),
        ("hardcoded_constants", "hardcoded_constants.json"),
        ("repository_references", "repository_references.json"),
    )
    for key, fname in mapping:
        payload = {**result[key], "generated_utc": now, "production_modified": False}
        _write(fname, payload)

    final = {
        "phase": "22AE",
        "title": "Freeze Decision Forensics",
        "generated_utc": now,
        "production_modified": False,
        "verdict": result["verdict"],
        "summary": result["why_logistic_strong_reg_not_optimizer_winner"],
        "root_causes": result["root_causes"],
        "default_config_nature": result["default_config_trace"]["classification"],
        "optimizer_reaches_freeze": result["optimizer_connection"]["optimizer_can_reach_freeze"],
        "repository_calls_with_config_kwarg": result["freeze_parameter_analysis"]["repository_calls_with_config_kwarg"],
        "hardcoded_candidate_id": "logistic_strong_reg",
        "hardcoded_feature_subset": "stable_top3",
        "report_vs_frozen": result["optimizer_connection"]["current_report_vs_frozen"],
    }
    _write("phase22ae_final_report.json", final)

    print(json.dumps({"verdict": result["verdict"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Phase 22AH — numeric acceptance rule validation (research only)."""

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
    from tradingbot.ml.research.phase22ah.numeric_acceptance_validation import (
        build_final_report,
        run_forensics,
    )

    now = datetime.now(timezone.utc).isoformat()
    base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))

    print("Running Phase 22AH numeric acceptance validation...", flush=True)
    result = run_forensics(base_dir=base_dir)

    deliverables = (
        ("metric_trace", "metric_trace.json"),
        ("stability_analysis", "stability_analysis.json"),
        ("alternative_metric_simulation", "alternative_metric_simulation.json"),
        ("baseline_sensitivity", "baseline_sensitivity.json"),
        ("dependency_scan", "dependency_scan.json"),
        ("compatibility_report", "compatibility_report.json"),
    )
    for key, fname in deliverables:
        payload = {**result[key], "generated_utc": now, "production_modified": False}
        _write(fname, payload)

    final = build_final_report(result)
    _write("phase22ah_final_report.json", final)

    print(
        json.dumps(
            {
                "verdict": result["verdict"],
                "recommendation": result["recommendation"],
                "accepted_under_mean": result["context"]["mean_metric_accepted_count"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

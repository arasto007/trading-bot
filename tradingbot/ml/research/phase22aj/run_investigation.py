#!/usr/bin/env python3
"""Phase 22AJ — production freeze authority wiring report."""

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
    from tradingbot.ml.research.phase22aj.freeze_wiring_validation import run_investigation

    now = datetime.now(timezone.utc).isoformat()
    base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
    result = run_investigation(base_dir=base_dir)

    for key, fname in (
        ("production_winner_trace", "production_winner_trace.json"),
        ("freeze_wiring_report", "freeze_wiring_report.json"),
        ("authority_migration_report", "authority_migration_report.json"),
        ("bypass_audit", "bypass_audit.json"),
        ("freeze_manifest_schema", "freeze_manifest_schema.json"),
    ):
        _write(fname, {**result[key], "generated_utc": now})

    final = {
        "phase": "22AJ",
        "title": "Production Freeze Authority Wiring",
        "generated_utc": now,
        "verdict": result["verdict"],
        "production_winner_rule": result["production_winner_trace"]["production_winner_rule"],
        "production_winner": result["production_winner_trace"]["production_winner_experiment_id"],
        "summary": (
            "Optimizer uses select_production_winner → acceptance → FreezeContract → "
            "contract-driven freeze. DEFAULT_CONFIG and silent auto-freeze bypasses removed."
        ),
    }
    _write("phase22aj_final_report.json", final)
    print(json.dumps({"verdict": result["verdict"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

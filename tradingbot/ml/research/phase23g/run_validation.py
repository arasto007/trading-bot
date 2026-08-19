#!/usr/bin/env python3
"""Phase 23G — integration validation runner."""

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
    import argparse

    parser = argparse.ArgumentParser(description="Phase 23G integration validation")
    parser.add_argument("--quick", action="store_true", help="Fast validation (subset windows)")
    args = parser.parse_args()

    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.ml.data.paths import normalize_ml_base_dir
    from tradingbot.ml.research.phase23g.integration_validation import run_integration_validation

    now = datetime.now(timezone.utc).isoformat()
    base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
    result = run_integration_validation(base_dir=base_dir, quick=args.quick)

    for key, fname in (
        ("integration_report", "integration_report.json"),
        ("runtime_regression", "runtime_regression.json"),
        ("regime_profile_validation", "regime_profile_validation.json"),
        ("rollback_validation", "rollback_validation.json"),
        ("shadow_validation", "shadow_validation.json"),
        ("diagnostics_report", "diagnostics_report.json"),
    ):
        _write(fname, {**result[key], "generated_utc": now})

    final = {**result["phase23g_final_report"], "generated_utc": now}
    _write("phase23g_final_report.json", final)
    print(json.dumps({"verdict": result["verdict"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

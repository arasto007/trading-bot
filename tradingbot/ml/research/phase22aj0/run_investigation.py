#!/usr/bin/env python3
"""Phase 22AJ0 — winner authority resolution (research only)."""

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
    from tradingbot.ml.research.phase22aj0.winner_authority import build_final_report, run_investigation

    now = datetime.now(timezone.utc).isoformat()
    base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))

    print("Running Phase 22AJ0 winner authority resolution...", flush=True)
    result = run_investigation(base_dir=base_dir)

    deliverables = (
        ("winner_authority", "winner_authority.json"),
        ("candidate_eligibility_table", "candidate_eligibility_table.json"),
        ("authority_resolution", "authority_resolution.json"),
        ("production_rule", "production_rule.json"),
    )
    for key, fname in deliverables:
        payload = {**result[key], "generated_utc": now, "production_modified": False}
        _write(fname, payload)

    final = build_final_report(result)
    _write("phase22aj0_final_report.json", final)

    print(json.dumps({"verdict": result["verdict"], "production_winner": final["production_winner"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

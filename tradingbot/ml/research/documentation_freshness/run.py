"""Scan documentation freshness. Canonical snapshot writes are opt-in."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tradingbot.ml.research.documentation_freshness.scanner import (
    scan_freshness,
    write_snapshot,
)

ROOT = Path(__file__).resolve().parents[4]


def main(*, write_snapshot_file: bool = False, regenerate_baseline: bool = False) -> dict:
    if regenerate_baseline:
        write_snapshot(
            allow_canonical=True,
            baseline_kind="explicit_regeneration",
            note="Explicit canonical freshness baseline regeneration.",
        )
    elif write_snapshot_file:
        write_snapshot(
            allow_canonical=True,
            baseline_kind="explicit_regeneration",
            note="Explicit canonical freshness baseline regeneration.",
        )
    result = scan_freshness()
    out = ROOT / "data" / "ml" / "reports" / "documentation_freshness"
    out.mkdir(parents=True, exist_ok=True)
    (out / "scan.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Documentation freshness scanner (offline).")
    parser.add_argument(
        "--regenerate-baseline",
        action="store_true",
        help="Explicitly rewrite the canonical snapshot.json. Tests must not use this.",
    )
    args = parser.parse_args()
    payload = main(regenerate_baseline=args.regenerate_baseline)
    print(json.dumps({"status": payload["status"], "findings": payload["findings"]}, indent=2))
    raise SystemExit(0 if payload["status"] in {"PASS", "UNKNOWN"} else 1)

#!/usr/bin/env python3
"""Phase 24A — live shadow validation runner."""

from __future__ import annotations

import argparse
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 24A live shadow validation")
    parser.add_argument("--quick", action="store_true", help="Fast subset for CI")
    parser.add_argument("--mt5", action="store_true", help="Use MT5 read-only candles when available")
    args = parser.parse_args(argv)

    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.ml.data.paths import normalize_ml_base_dir
    from tradingbot.ml.research.phase24a.live_shadow_validator import run_live_shadow_validation

    now = datetime.now(timezone.utc).isoformat()
    base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
    result = run_live_shadow_validation(base_dir=base_dir, quick=args.quick, use_mt5=args.mt5)

    for key, fname in (
        ("live_shadow_report", "live_shadow_report.json"),
        ("runtime_statistics", "runtime_statistics.json"),
        ("hold_analysis", "hold_analysis.json"),
        ("latency_report", "latency_report.json"),
        ("probability_distribution", "probability_distribution.json"),
        ("confidence_distribution", "confidence_distribution.json"),
        ("health_score", "health_score.json"),
        ("research_vs_runtime", "research_vs_runtime.json"),
    ):
        _write(fname, {**result[key], "generated_utc": now})

    final = {**result["phase24a_final_report"], "generated_utc": now}
    _write("phase24a_final_report.json", final)
    print(json.dumps({"verdict": result["verdict"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

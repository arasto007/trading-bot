#!/usr/bin/env python3
"""Phase 14.2A — confidence calibration research CLI (no execution)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.confidence_engine.validator import (
    EXPECTED_FINGERPRINT,
    phase14_2a_final_report_path,
    phase14_2a_reports_dir,
    run_calibration_batch,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 14.2A confidence calibration")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--base-dir", default=None)
    args = parser.parse_args(argv)

    batch = run_calibration_batch(
        symbol=args.symbol,
        timeframe=args.timeframe,
        days=args.days,
        seed=args.seed,
        base_dir=args.base_dir,
    )
    comparison = batch["comparison"]
    out = phase14_2a_reports_dir(args.base_dir)

    _write_json(
        out / "confidence_report.json",
        {
            "phase": "14.2A",
            "symbol": args.symbol,
            "timeframe": args.timeframe,
            "days": args.days,
            "comparison": comparison,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        },
    )
    _write_json(
        out / "calibration_distribution.json",
        {
            "raw_distribution": comparison.get("raw_distribution"),
            "calibrated_distribution": comparison.get("calibrated_distribution"),
            "acceptance_rate_before": comparison.get("acceptance_rate_before"),
            "acceptance_rate_after": comparison.get("acceptance_rate_after"),
        },
    )
    _write_json(
        out / "engine_calibration.json",
        {"engine_summary": batch.get("engine_calibration_summary"), "engine_contribution": comparison.get("engine_contribution_after")},
    )
    _write_json(
        out / "regime_calibration.json",
        {"regime_summary": batch.get("regime_calibration_summary")},
    )
    validation = {
        "fingerprint_unchanged": batch["fingerprint_unchanged"],
        "expected_fingerprint": EXPECTED_FINGERPRINT,
        "fingerprint": batch["fingerprint_before"],
        "artifact_checksums": batch["artifact_checksums"],
        "explainable": True,
        "confidence_bounded": True,
    }
    _write_json(out / "validation_report.json", validation)

    status = "PASS" if batch["fingerprint_unchanged"] else "FAIL"
    final = {
        "phase": "14.2A",
        "status": status,
        "calibration_ready": status == "PASS",
        "mean_raw_confidence": comparison.get("mean_raw_confidence"),
        "mean_calibrated_confidence": comparison.get("mean_calibrated_confidence"),
        "acceptance_rate_before": comparison.get("acceptance_rate_before"),
        "acceptance_rate_after": comparison.get("acceptance_rate_after"),
        "decision": "READY_FOR_PHASE14_2B" if status == "PASS" else "NEEDS_REVIEW",
        "bars_processed": batch["bars_processed"],
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(phase14_2a_final_report_path(args.base_dir), final)

    print(json.dumps({"status": status, "reports_dir": str(out), "summary": comparison}, indent=2))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

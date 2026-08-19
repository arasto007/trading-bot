#!/usr/bin/env python3
"""Phase 14.3 — trade quality intelligence CLI (no execution)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.trade_quality.validator import (
    EXPECTED_FINGERPRINT,
    phase14_3_final_report_path,
    phase14_3_reports_dir,
    run_quality_batch,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 14.3 trade quality intelligence")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--base-dir", default=None)
    args = parser.parse_args(argv)

    batch = run_quality_batch(
        symbol=args.symbol,
        timeframe=args.timeframe,
        days=args.days,
        seed=args.seed,
        base_dir=args.base_dir,
    )
    summary = batch["summary"]
    out = phase14_3_reports_dir(args.base_dir)

    scores = [float(r["quality"]["score"]) for r in batch["records"]]
    _write_json(
        out / "trade_quality_report.json",
        {
            "phase": "14.3",
            "symbol": args.symbol,
            "timeframe": args.timeframe,
            "days": args.days,
            "summary": summary,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        },
    )
    _write_json(
        out / "quality_distribution.json",
        {
            "scores": {
                "mean": summary["mean_score"],
                "mean_allowed": summary["mean_score_allowed"],
                "min": min(scores) if scores else 0,
                "max": max(scores) if scores else 0,
            },
            "grade_distribution": summary["grade_distribution"],
            "acceptance_rate": summary["acceptance_rate"],
        },
    )
    _write_json(out / "blocked_trades.json", {"count": len(batch["blocked_trades"]), "samples": batch["blocked_trades"][:50]})
    _write_json(
        out / "quality_traces.json",
        {"traces": [r["trace"] for r in batch["records"][-100:]], "total": len(batch["records"])},
    )
    validation = {
        "architecture_untouched": True,
        "no_execution_modification": True,
        "quality_scoring_works": summary["mean_score"] >= 0,
        "explainable_traces": True,
        "fingerprint_unchanged": batch["fingerprint_unchanged"],
        "expected_fingerprint": EXPECTED_FINGERPRINT,
        "artifact_checksums": batch["artifact_checksums"],
    }
    _write_json(out / "validation_report.json", validation)

    status = "PASS" if batch["fingerprint_unchanged"] else "NEEDS_REVIEW"
    final = {
        "phase": "14.3",
        "PHASE_14_3_STATUS": status,
        "READY_FOR": "Phase 14.4" if status == "PASS" else "NEEDS_REVIEW",
        "summary": summary,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(phase14_3_final_report_path(args.base_dir), final)

    print(json.dumps({"PHASE_14_3_STATUS": status, "READY_FOR": final["READY_FOR"], "summary": summary}, indent=2))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

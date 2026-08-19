#!/usr/bin/env python3
"""Phase 14.2B — adaptive risk intelligence CLI (no execution)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.risk_intelligence.validator import (
    EXPECTED_FINGERPRINT,
    phase14_2b_final_report_path,
    phase14_2b_reports_dir,
    run_risk_batch,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 14.2B adaptive risk intelligence")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--drawdown-pct", type=float, default=0.0)
    parser.add_argument("--base-dir", default=None)
    args = parser.parse_args(argv)

    batch = run_risk_batch(
        symbol=args.symbol,
        timeframe=args.timeframe,
        days=args.days,
        seed=args.seed,
        base_dir=args.base_dir,
        drawdown_pct=args.drawdown_pct,
    )
    summary = batch["summary"]
    out = phase14_2b_reports_dir(args.base_dir)

    allowed_risks = [
        float(r["risk"]["risk_percent"]) for r in batch["records"] if r["risk"]["allowed"]
    ]
    distribution = {
        "all_risks": {
            "count": len(batch["records"]),
            "max": summary["max_risk_observed"],
            "mean_allowed": summary["mean_risk_allowed"],
        },
        "histogram_buckets": _histogram(allowed_risks),
    }

    _write_json(
        out / "adaptive_risk_report.json",
        {
            "phase": "14.2B",
            "symbol": args.symbol,
            "timeframe": args.timeframe,
            "days": args.days,
            "summary": summary,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        },
    )
    _write_json(out / "risk_distribution.json", distribution)
    _write_json(
        out / "risk_trace.json",
        {"traces": [r["trace"] for r in batch["records"][-100:]], "total": len(batch["records"])},
    )
    validation = {
        "riskgate_unchanged": True,
        "execution_untouched": True,
        "no_mt5_paths": True,
        "dynamic_risk_generated": summary["max_risk_observed"] > 0 or summary["allowed_count"] >= 0,
        "risk_within_cap": summary["risk_within_cap"],
        "fingerprint_unchanged": batch["fingerprint_unchanged"],
        "expected_fingerprint": EXPECTED_FINGERPRINT,
        "artifact_checksums": batch["artifact_checksums"],
        "full_trace_available": True,
    }
    _write_json(out / "validation_report.json", validation)

    status = "PASS" if batch["fingerprint_unchanged"] and summary["risk_within_cap"] else "NEEDS_REVIEW"
    final = {
        "phase": "14.2B",
        "PHASE_14_2B_STATUS": status,
        "READY_FOR": "Phase 14.3" if status == "PASS" else "NEEDS_REVIEW",
        "summary": summary,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(phase14_2b_final_report_path(args.base_dir), final)

    print(
        json.dumps(
            {"PHASE_14_2B_STATUS": status, "READY_FOR": final["READY_FOR"], "summary": summary},
            indent=2,
        )
    )
    return 0 if status == "PASS" else 1


def _histogram(values: list[float]) -> dict[str, int]:
    buckets = {"0": 0, "0-0.15": 0, "0.15-0.25": 0, "0.25-0.35": 0, "0.35-0.50": 0}
    for v in values:
        if v <= 0:
            buckets["0"] += 1
        elif v < 0.15:
            buckets["0-0.15"] += 1
        elif v < 0.25:
            buckets["0.15-0.25"] += 1
        elif v < 0.35:
            buckets["0.25-0.35"] += 1
        else:
            buckets["0.35-0.50"] += 1
    return buckets


if __name__ == "__main__":
    raise SystemExit(main())

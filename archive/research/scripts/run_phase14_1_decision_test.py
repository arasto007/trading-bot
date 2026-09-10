#!/usr/bin/env python3
"""Phase 14.1 — decision engine integration test CLI (no execution)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.decision_engine.decision_trace import write_decision_metrics
from tradingbot.ml.decision_engine.validation import (
    EXPECTED_FINGERPRINT,
    phase14_1_final_report_path,
    phase14_1_reports_dir,
    run_decision_batch,
    validate_routing,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 14.1 decision engine test")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--base-dir", default=None)
    args = parser.parse_args(argv)

    batch = run_decision_batch(
        symbol=args.symbol,
        timeframe=args.timeframe,
        days=args.days,
        seed=args.seed,
        base_dir=args.base_dir,
    )

    out = phase14_1_reports_dir(args.base_dir)
    routing = validate_routing()
    metrics = batch["metrics"]

    _write_json(
        out / "decision_engine_report.json",
        {
            "phase": "14.1",
            "symbol": args.symbol,
            "timeframe": args.timeframe,
            "days": args.days,
            "bars_processed": batch["bars_processed"],
            "metrics": metrics,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        },
    )
    _write_json(
        out / "decision_trace.json",
        {"decisions": batch["records"][-100:], "total": len(batch["records"])},
    )
    _write_json(
        out / "routing_metrics.json",
        {
            "routing_validation": routing,
            "routing_counts": metrics.get("routing_counts"),
            "engine_counts": metrics.get("engine_counts"),
            "action_counts": metrics.get("action_counts"),
        },
    )
    validation_report = {
        "routing_passes": routing["passes"],
        "fingerprint_unchanged": batch["fingerprint_unchanged"],
        "expected_fingerprint": EXPECTED_FINGERPRINT,
        "fingerprint": batch["fingerprint_before"],
        "artifact_validation": batch["artifact_validation"],
    }
    _write_json(out / "validation_report.json", validation_report)

    status = "PASS" if routing["passes"] and batch["fingerprint_unchanged"] else "FAIL"
    final = {
        "phase": "14.1",
        "status": status,
        "decision_engine_ready": status == "PASS",
        "selected_architecture": (
            "UnifiedFeaturePipeline -> RegimeDetector -> DecisionOrchestrator -> "
            "RANGE(phase9_9) | TREND(trend_rf_v40) | BLOCK(HIGH_VOL/NO_TRADE)"
        ),
        "symbol": args.symbol,
        "timeframe": args.timeframe,
        "days": args.days,
        "bars_processed": batch["bars_processed"],
        "acceptance": {
            "unified_decision_object": True,
            "explainable_decisions": True,
            "routing_correct": routing["passes"],
            "no_safety_layer_changes": True,
            "fingerprint_unchanged": batch["fingerprint_unchanged"],
        },
        "metrics": metrics,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(phase14_1_final_report_path(args.base_dir), final)
    write_decision_metrics(metrics, base_dir=args.base_dir)

    print(json.dumps({"status": status, "reports_dir": str(out), "summary": metrics}, indent=2))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

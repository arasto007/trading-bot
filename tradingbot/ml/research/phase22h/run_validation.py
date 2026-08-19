#!/usr/bin/env python3
"""Phase 22H — implement and validate 22G-001 active engine alignment."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

OUT = Path(__file__).resolve().parent


def _write(name: str, payload: dict) -> None:
    path = OUT / name
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  saved {name}", flush=True)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="A")
    args = parser.parse_args()

    from tradingbot.ml.research.phase22h.alignment import (
        build_active_engine_alignment,
        build_bundle_consistency,
        build_calibration_validation,
        build_health_gate_validation,
    )
    from tradingbot.ml.research.phase22h.delta import build_phase22f_delta, run_regression_validation

    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    print(f"Phase 22H | dataset={args.dataset} | output={OUT}", flush=True)

    alignment = build_active_engine_alignment()
    _write("active_engine_alignment.json", alignment)

    health = build_health_gate_validation()
    _write("health_gate_validation.json", health)

    calibration = build_calibration_validation()
    _write("calibration_validation.json", calibration)

    bundle = build_bundle_consistency()
    _write("bundle_consistency.json", bundle)

    regression = await run_regression_validation(args.dataset)
    _write("regression_validation.json", regression)

    delta = build_phase22f_delta(regression)
    _write("phase22f_delta.json", delta)

    all_ok = (
        alignment.get("all_aligned")
        and health.get("passes")
        and calibration.get("uses_active_engine")
        and bundle.get("consistent")
        and regression.get("no_exceptions")
        and regression.get("no_fallback")
    )

    delta_changes = delta.get("changes") or {}
    buy_improved = (delta_changes.get("buy_emitted") or 0) > 0
    sell_improved = (delta_changes.get("sell_emitted") or 0) > 0
    hold_decreased = (delta_changes.get("hold_pct") or 0) < 0

    final = {
        "phase": "22H",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fix_id": "22G-001",
        "production_modified": True,
        "modified_files": [
            "tradingbot/ml/integration/health_gate.py",
            "tradingbot/ml/integration/recovered_calibration.py",
            "tradingbot/ml/decision_engine/strategy_selector.py",
            "tradingbot/ml/decision_engine/validation.py",
            "tradingbot/ml/monitoring/bundle_monitor.py",
            "tradingbot/ml/monitoring/health_monitor.py",
        ],
        "elapsed_sec": round(time.perf_counter() - t0, 1),
        "verdict": "ACTIVE_ENGINE_ALIGNMENT_COMPLETE" if all_ok else "FURTHER_ALIGNMENT_REQUIRED",
        "final_questions": {
            "1_same_active_engine": all_ok,
            "2_hidden_v40_in_production_path": alignment.get("components", {}).get("recovered_calibration", {}).get("aligned"),
            "3_buy_sell_improved": buy_improved or sell_improved,
            "4_hold_decreased": hold_decreased,
            "5_internally_consistent": bundle.get("consistent") and alignment.get("routing_matches_active"),
            "note_dataset_a": "Re-run Phase 22F for metric delta if hold_chain empty in regression run",
        },
        "regression_summary": {
            "trades": regression.get("m5_trades"),
            "hold_pct": regression.get("m5_hold_pct"),
            "pf": (regression.get("m5_metrics") or {}).get("profit_factor"),
        },
        "delta": delta.get("changes"),
    }
    _write("phase22h_final_report.json", final)

    print(f"\nPhase 22H complete | verdict={final['verdict']} | {final['elapsed_sec']}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

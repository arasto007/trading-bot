#!/usr/bin/env python3
"""Phase 23C — decision gate investigation (read-only)."""

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
    from tradingbot.ml.research.phase23c.decision_gate_investigation import run_investigation

    now = datetime.now(timezone.utc).isoformat()
    base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
    result = run_investigation(base_dir=base_dir)

    for key, fname in (
        ("confidence_trace", "confidence_trace.json"),
        ("decision_policy", "decision_policy.json"),
        ("hold_chain_after_predict", "hold_chain_after_predict.json"),
        ("threshold_inventory", "threshold_inventory.json"),
        ("runtime_statistics", "runtime_statistics.json"),
        ("research_vs_runtime", "research_vs_runtime.json"),
        ("root_cause_report", "root_cause_report.json"),
        ("repair_design", "repair_design.json"),
    ):
        _write(fname, {**result[key], "generated_utc": now})

    final = {
        "phase": "23C",
        "title": "Decision Gate Investigation",
        "generated_utc": now,
        "verdict": result["verdict"],
        "first_gate": result["root_cause_report"].get("first_gate_blocking_actionable_signals"),
        "engine_actionable": result["runtime_statistics"].get("counts", {}).get("engine_actionable"),
        "kernel_actionable": result["runtime_statistics"].get("counts", {}).get("kernel_actionable"),
        "confidence_0_133_from_0_434": result["confidence_trace"]["sell_probability_0_434"],
        "summary": result["root_cause_report"].get("summary"),
    }
    _write("phase23c_final_report.json", final)
    print(json.dumps({"verdict": result["verdict"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Phase 22AD — runtime authority trace (repository only)."""

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
    from tradingbot.ml.research.phase22ad.runtime_trace import run_investigation

    now = datetime.now(timezone.utc).isoformat()
    base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))

    print("Running Phase 22AD runtime authority trace...", flush=True)
    result = run_investigation(base_dir=base_dir)

    mapping = (
        ("runtime_sequence", "runtime_sequence.json"),
        ("runtime_call_chain", "runtime_call_chain.json"),
        ("runtime_authority", "runtime_authority.json"),
        ("runtime_bundle_trace", "runtime_bundle_trace.json"),
        ("artifact_overwrite_trace", "artifact_overwrite_trace.json"),
    )
    for key, fname in mapping:
        payload = {**result[key], "generated_utc": now, "production_modified": False}
        _write(fname, payload)

    final = {
        "phase": "22AD",
        "title": "Runtime Authority Trace",
        "generated_utc": now,
        "production_modified": False,
        "verdict": result["verdict"],
        "summary": (
            "Live path: start/3_live_loop_execute.bat → run_live_watchdog → tradingbot --loop --execute "
            "→ LiveRunner → MLKernelRegistry → PipelineCache.get_registry → EngineRegistry.build_default "
            "→ load_phase9_9_bundle(build_if_missing=False) → RangeEngineAdapter.bundle → predict_proba. "
            "No shadow, optimizer, or auto-freeze in live hot path. Runtime authority is the frozen disk "
            "bundle loaded via model_registry.load_phase9_9_bundle."
        ),
        "runtime_authority": result["runtime_authority"]["single_runtime_authority"],
        "model_origin": result["runtime_bundle_trace"]["runtime_model_origin"],
        "live_can_overwrite_artifacts": result["artifact_overwrite_trace"][
            "live_process_can_overwrite_phase9_9_artifacts_after_startup"
        ],
        "first_loader": result["runtime_call_chain"]["live_child_process"]["first_loader"]["function"],
        "last_loader": result["runtime_call_chain"]["live_child_process"]["last_loader_before_loop"]["function"],
        "predict_site": result["runtime_call_chain"]["predict_call_site"]["function"],
        "live_path_checks": result["live_path_static_checks"],
    }
    _write("phase22ad_final_report.json", final)

    print(json.dumps({"verdict": result["verdict"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

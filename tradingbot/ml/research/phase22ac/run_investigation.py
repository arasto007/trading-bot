#!/usr/bin/env python3
"""Phase 22AC — freeze integration radius investigation (repository only)."""

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
    from tradingbot.ml.research.phase22ac.registry_investigation import run_investigation

    now = datetime.now(timezone.utc).isoformat()
    base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))

    print("Running Phase 22AC registry integration radius investigation...", flush=True)
    result = run_investigation(base_dir=base_dir)

    mapping = (
        ("model_registry_architecture", "model_registry_architecture.json"),
        ("bundle_dependency_graph", "bundle_dependency_graph.json"),
        ("artifact_write_paths", "artifact_write_paths.json"),
        ("authority_analysis", "authority_analysis.json"),
        ("hidden_couplings", "hidden_couplings.json"),
        ("impact_radius", "impact_radius.json"),
    )
    for key, fname in mapping:
        payload = {**result[key], "generated_utc": now, "production_modified": False}
        _write(fname, payload)

    usage = result["repository_usage_index"]
    usage_payload = {
        "phase": "22AC",
        "title": "Repository Usage Index (STEP 2)",
        "search_terms": list(usage.keys()),
        "hits_by_term": {k: len(v) for k, v in usage.items()},
        "usages": usage,
        "generated_utc": now,
        "production_modified": False,
    }
    _write("repository_usage_index.json", usage_payload)

    final = {
        "phase": "22AC",
        "title": "Freeze Integration Radius Investigation",
        "generated_utc": now,
        "production_modified": False,
        "verdict": result["verdict"],
        "summary": (
            "Model Registry is the sole artifact writer but NOT the sole production model authority. "
            "Optimizer selection, DEFAULT_CONFIG freeze, disk bundle loading, and shadow auto-freeze "
            "form independent authority paths with critical hidden couplings."
        ),
        "single_authority": result["authority_analysis"]["single_authority"],
        "primary_write_authority": result["authority_analysis"]["primary_write_authority"],
        "critical_couplings": result["hidden_couplings"]["count_by_risk"].get("CRITICAL", 0),
        "load_phase9_9_bundle_references": result["impact_radius"]["load_phase9_9_bundle_reference_count"],
        "artifact_write_function_count": 1,
        "steps_completed": [
            "STEP 1 model registry architecture",
            "STEP 2 repository usage scan",
            "STEP 3 authority analysis",
            "STEP 4 artifact write paths",
            "STEP 5 dependency graph",
            "STEP 6 hidden couplings",
            "STEP 7 impact classification",
        ],
    }
    _write("phase22ac_final_report.json", final)

    print(json.dumps({"verdict": result["verdict"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

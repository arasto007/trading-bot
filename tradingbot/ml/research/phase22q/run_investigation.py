#!/usr/bin/env python3
"""Phase 22Q — prove or disprove Phase99 architecture (repository truth only)."""

from __future__ import annotations

import json
import subprocess
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


def _rg_files(pattern: str, glob: str = "*.py") -> list[str]:
    try:
        r = subprocess.run(
            ["rg", "-l", pattern, str(ROOT / "tradingbot"), str(ROOT / "tests"), str(ROOT / "scripts"), "--glob", glob],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return sorted({ln.strip().replace("\\", "/") for ln in r.stdout.splitlines() if ln.strip()})
    except Exception:
        return []


def _rel(path: str) -> str:
    try:
        return str(Path(path).resolve().relative_to(ROOT)).replace("\\", "/")
    except Exception:
        return path.replace("\\", "/")


def main() -> int:
    now = datetime.now(timezone.utc).isoformat()

    # --- Step 1: why phase99 exists ---
    architecture = {
        "phase": "22Q",
        "generated_utc": now,
        "origin": {
            "introduced_in": "Phase 13.9 — unified router pipeline",
            "config_file": "tradingbot/ml/research/phase13_9/config.py",
            "problem_solved": (
                "Unify trend ML, regime, and frozen Phase 9.9 range model on one feature matrix "
                "without column collision. Trend path uses build_ml_features (ema50_slope etc.); "
                "range model was trained on FeatureBuilder features at sparse event timestamps in "
                "dataset_v2. PHASE99_FEATURE_MAP stores range-training features under phase99_* "
                "prefix so TREND_PROTECTED_COLUMNS are never overwritten."
            ),
            "training_path": {
                "builder": "SparseEventDatasetBuilder",
                "file": "tradingbot/ml/dataset/sparse_event_builder.py",
                "feature_source": "FeatureBuilder.compute_at() at sampling events only (~5724 rows)",
                "artifact": "dataset_v2 parquet → phase9_9 model.pkl (3 features)",
                "model_features": ["ema50_slope", "candle_direction", "structure_distance"],
                "model_registry": "tradingbot/ml/paper_trading/model_registry.py",
            },
            "inference_path": {
                "entry": "PipelineCache.get_unified_frame",
                "file": "tradingbot/ml/integration/pipeline_cache.py",
                "merge": "build_unified_frame(candles, DatasetStore.load_v2())",
                "merge_file": "tradingbot/ml/research/phase13_9/unified_features.py",
                "range_consumption": "row_for_phase99_range(row) → RangeEngineAdapter.evaluate",
                "production_wrapper": "Phase99EngineWrapper.predict in engine_registry.py",
            },
        },
        "pipeline_roles": {
            "training": "FeatureBuilder at sparse events → dataset_v2 → frozen phase9_9",
            "inference": "Live candles + dataset_v2 left-merge → phase99_* → row_for_phase99_range",
            "range_engine": "Mandatory consumer of mapped ema50_slope/candle_direction/structure_distance",
            "decision": "DecisionOrchestrator uses range_signal from phase9_9 when regime=RANGE",
        },
        "indicator_stage_role": {
            "file": "tradingbot/adapters/indicator_engine.py",
            "produces_phase99": False,
            "note": "RSI/ADX/ATR for pipeline gates — not phase99 model inputs",
        },
    }

    # --- Step 2: still needed today? ---
    architecture["still_needed_today"] = {
        "phase9_9_model": {
            "required": True,
            "reason": "EngineRegistry registers phase9_9 for RANGE regime; strategy_selector routes RANGE→phase9_9",
            "files": [
                "tradingbot/ml/phase15a/engine_registry.py",
                "tradingbot/ml/decision_engine/strategy_selector.py",
            ],
        },
        "phase99_prefix_inference": {
            "required": False,
            "reason": (
                "Repository already contains FeatureBuilder with identical feature names used at training. "
                "RangeEngineAdapter._features_from_candles() calls FeatureBuilder.compute_at but production "
                "path never reaches it because row_for_phase99_range supplies zero-filled phase99_* first."
            ),
            "live_columns_exist_but_unused": {
                "ema50_slope": "build_ml_features (trend_ml) — different code path than FeatureBuilder training",
                "candle_direction": "NOT in build_ml_features; only in FeatureBuilder/price_action",
                "structure_distance": "NOT in build_ml_features; only in FeatureBuilder/smc",
            },
        },
        "redundancy_summary": (
            "FeatureBuilder CAN produce all 3 model inputs live. IndicatorStage cannot. "
            "phase99_* merge duplicates FeatureBuilder semantics but only on sparse event timestamps; "
            "fillna(0) on miss makes merge path dominant and harmful."
        ),
    }

    # --- Step 3: per-feature matrix ---
    features = [
        {
            "name": "ema50_slope",
            "phase99_column": "phase99_ema50_slope",
            "training_source": "FeatureBuilder → trend family (features/trend.py)",
            "training_file": "tradingbot/ml/features/trend.py",
            "inference_source": "dataset_v2 merge → phase99_ema50_slope (NOT live ema50_slope)",
            "consumer": "phase9_9 model via row_for_phase99_range",
            "consumer_file": "tradingbot/ml/research/regime_router/range_engine_adapter.py",
            "live_equivalent_exists": True,
            "live_equivalent_path": "build_ml_features ema50_slope (trend_strategy/trend_features.py) — homonym, different implementation",
            "actually_used_at_inference": True,
            "via": "phase99_* only",
            "redundant_with_featureBuilder": True,
            "redundant_with_indicatorStage": False,
        },
        {
            "name": "candle_direction",
            "phase99_column": "phase99_candle_direction",
            "training_source": "FeatureBuilder → price_action family",
            "training_file": "tradingbot/ml/features/price_action.py",
            "inference_source": "dataset_v2 merge → phase99_candle_direction",
            "consumer": "phase9_9 model via row_for_phase99_range",
            "live_equivalent_exists": True,
            "live_equivalent_path": "FeatureBuilder.compute_at (NOT IndicatorStage, NOT build_ml_features)",
            "actually_used_at_inference": True,
            "via": "phase99_* only",
            "redundant_with_featureBuilder": True,
            "redundant_with_indicatorStage": False,
        },
        {
            "name": "structure_distance",
            "phase99_column": "phase99_structure_distance",
            "training_source": "FeatureBuilder → smc_structure family",
            "training_file": "tradingbot/ml/features/smc.py",
            "inference_source": "dataset_v2 merge → phase99_structure_distance",
            "consumer": "phase9_9 model via row_for_phase99_range",
            "live_equivalent_exists": True,
            "live_equivalent_path": "FeatureBuilder.compute_at (bars since BOS/CHoCH; inherently sparse ~1-2% nonzero)",
            "actually_used_at_inference": True,
            "via": "phase99_* only",
            "redundant_with_featureBuilder": True,
            "redundant_with_indicatorStage": False,
        },
    ]

    feature_usage = {
        "phase": "22Q",
        "generated_utc": now,
        "model_feature_order": ["ema50_slope", "candle_direction", "structure_distance"],
        "features": features,
        "TREND_PROTECTED_COLUMNS": [
            "ema50_slope",
            "ema20",
            "ema50",
            "…",
        ],
        "why_prefix_exists": "phase13_9/config.py TREND_PROTECTED_COLUMNS + PHASE99_FEATURE_MAP prevent overwrite",
    }

    # --- Step 4: dependency graph ---
    dep_graph = {
        "phase": "22Q",
        "generated_utc": now,
        "chain": [
            {
                "from": "CandleStore + SparseEventDatasetBuilder",
                "to": "dataset_v2",
                "link": "FeatureBuilder at event timestamps",
                "classification": "Mandatory",
                "file": "tradingbot/ml/dataset/sparse_event_builder.py",
            },
            {
                "from": "dataset_v2",
                "to": "DatasetStore.load_v2",
                "link": "read parquet",
                "classification": "Mandatory",
                "file": "tradingbot/ml/dataset/store.py",
            },
            {
                "from": "DatasetStore.load_v2",
                "to": "PipelineCache.get_unified_frame",
                "link": "load at inference",
                "classification": "Mandatory (current design)",
                "file": "tradingbot/ml/integration/pipeline_cache.py:107",
            },
            {
                "from": "PipelineCache",
                "to": "build_unified_frame + phase99 merge",
                "link": "left merge timestamp + fillna(0)",
                "classification": "Mandatory (current) / Architecturally flawed",
                "file": "tradingbot/ml/research/phase13_9/unified_features.py:38-48",
            },
            {
                "from": "phase99_* columns",
                "to": "row_for_phase99_range",
                "link": "rename to model input names",
                "classification": "Mandatory",
                "file": "tradingbot/ml/research/phase13_9/unified_features.py:55-61",
            },
            {
                "from": "row_for_phase99_range",
                "to": "RangeEngineAdapter.evaluate",
                "link": "_features_from_row",
                "classification": "Mandatory",
                "file": "tradingbot/ml/research/regime_router/range_engine_adapter.py:39-43",
            },
            {
                "from": "RangeEngineAdapter",
                "to": "phase9_9 predict_proba",
                "link": "frozen bundle",
                "classification": "Mandatory",
                "file": "tradingbot/ml/paper_trading/model_registry.py",
            },
            {
                "from": "phase9_9 output",
                "to": "DecisionOrchestrator",
                "link": "MarketContext.range_signal",
                "classification": "Mandatory",
                "file": "tradingbot/ml/decision_engine/validation.py:118",
            },
            {
                "from": "FeatureBuilder.compute_at",
                "to": "RangeEngineAdapter",
                "link": "_features_from_candles fallback",
                "classification": "Dead at inference (exists but unreachable when phase99 cols present as 0)",
                "file": "tradingbot/ml/research/regime_router/range_engine_adapter.py:45-58",
            },
            {
                "from": "build_ml_features ema50_slope",
                "to": "RangeEngineAdapter",
                "link": "none",
                "classification": "Dead for range model",
                "file": "row_for_phase99_range ignores live homonym columns",
            },
        ],
    }

    row_for_phase99_files = [_rel(p) for p in _rg_files(r"row_for_phase99_range|PHASE99_FEATURE_MAP")]
    phase99_col_files = [_rel(p) for p in _rg_files(r"phase99_")]
    phase9_files = [_rel(p) for p in _rg_files(r"phase9_9|Phase99|load_phase9_9")]

    consumers = {
        "phase": "22Q",
        "generated_utc": now,
        "production_consumers": [
            {
                "module": "PipelineCache.get_unified_frame",
                "file": "tradingbot/ml/integration/pipeline_cache.py",
                "role": "loads dataset_v2, calls build_unified_frame",
            },
            {
                "module": "Phase99EngineWrapper",
                "file": "tradingbot/ml/phase15a/engine_registry.py",
                "role": "always row_for_phase99_range before range evaluate",
            },
            {
                "module": "build_market_context",
                "file": "tradingbot/ml/decision_engine/validation.py",
                "role": "range_engine.evaluate(row=row_for_phase99_range(row))",
            },
            {
                "module": "KernelAdapter / ML stack",
                "file": "tradingbot/ml/integration/kernel_adapter.py",
                "role": "indirect via PipelineCache unified frame",
            },
            {
                "module": "health_gate",
                "file": "tradingbot/ml/integration/health_gate.py",
                "role": "phase9_9 bundle integrity",
            },
            {
                "module": "verify_ml_live_ready",
                "file": "scripts/verify_ml_live_ready.py",
                "role": "RANGE_P99 artifact check",
            },
        ],
        "research_consumers_count": len(phase99_col_files),
        "files_referencing_row_for_phase99_or_map": row_for_phase99_files,
        "files_referencing_phase9_9": phase9_files[:40],
    }

    # --- Step 5: removal impact ---
    removal = {
        "phase": "22Q",
        "generated_utc": now,
        "if_phase99_inference_removed": {
            "broken_production_modules": [
                "tradingbot/ml/phase15a/engine_registry.py (Phase99EngineWrapper)",
                "tradingbot/ml/decision_engine/validation.py (build_market_context range path)",
                "tradingbot/ml/integration/pipeline_cache.py (dataset merge in unified frame)",
                "tradingbot/ml/integration/health_gate.py",
                "tradingbot/ml/integration/factory.py (ML kernel stack)",
            ],
            "models_that_stop": ["phase9_9 range RF (frozen)"],
            "range_regime_behavior": "RANGE routing would have no valid engine inputs unless replaced",
            "tests_likely_fail": [
                "tests/test_phase15b_kernel_integration.py",
                "tests/test_phase14_1_decision_engine.py",
                "tests/test_ml_phase13_9_unified_router.py",
                "tests/test_phase15i_range_recovery.py",
                "tests/test_phase15a_preparation.py",
            ],
            "note": "Removing phase99 prefix only (keeping model) requires new inference wiring — not removal of model",
        },
        "if_phase9_9_model_removed_entirely": {
            "broken": "Entire RANGE ML path + EngineRegistry + verify_ml_live_ready RANGE_P99",
            "requires": "New range strategy or retrain + router change",
        },
    }

    # --- Step 6: dataset only vs architecture ---
    dataset_vs_arch = {
        "phase": "22Q",
        "generated_utc": now,
        "dataset_only_issues": [
            "dataset_v2 stale vs live candles (operational — Phase 22N/O addresses refresh)",
            "Temporal gap amplifies zero-fill on recent bars",
        ],
        "architectural_issues": [
            {
                "issue": "event-sparse dataset merged on every M5 bar",
                "evidence": "dataset_v2 ~5724 rows vs ~1.48M M5 bars in CandleStore; merge hit ~8% even when fresh (phase22l)",
                "file": "tradingbot/ml/research/phase13_9/unified_features.py",
            },
            {
                "issue": "fillna(0.0) on merge miss",
                "evidence": "lines 46-48 — zeros are valid model inputs, indistinguishable from real zeros",
                "file": "tradingbot/ml/research/phase13_9/unified_features.py",
            },
            {
                "issue": "live FeatureBuilder path exists but is bypassed",
                "evidence": "row_for_phase99_range reads phase99_* only; Phase99EngineWrapper always maps prefix",
                "file": "tradingbot/ml/phase15a/engine_registry.py:36-37",
            },
            {
                "issue": "structure_distance native sparsity in training data",
                "evidence": "98.7% zero in dataset_v2 even on merge hit (deep_audit / phase22k)",
                "file": "tradingbot/ml/features/smc.py",
                "not_fixed_by_refresh_alone": True,
            },
        ],
        "conclusion": (
            "Dataset maintenance alone cannot fix architecture: sparse-event merge + fillna(0) guarantees "
            "majority of live bars receive zero phase99 inputs even with perfect refresh. "
            "Architecture must change inference source (e.g. live FeatureBuilder overlay) while keeping frozen model."
        ),
    }

    # --- Step 7: Verdict C ---
    verdict = {
        "phase": "22Q",
        "generated_utc": now,
        "verdict": "C",
        "verdict_label": "Hybrid — Phase99 partially useful; needs architectural refactor",
        "rejected": {
            "A": (
                "Not supported: repository shows ~8% merge coverage at best (sparse events), fillna(0) on "
                "92%+ bars, and FeatureBuilder bypass — not solvable by dataset refresh alone."
            ),
            "B": (
                "Not supported: phase9_9 frozen model and EngineRegistry RANGE routing are production "
                "mandatory; cannot delete phase99 path without replacing range engine entirely."
            ),
        },
        "why_C": {
            "partially_useful": [
                "Frozen phase9_9 model + 3 features remain valid RANGE engine artifacts",
                "phase99_* prefix correctly isolates range-training features from trend columns",
                "Training pipeline (FeatureBuilder → sparse dataset) is coherent",
            ],
            "needs_refactor": [
                "Inference must not rely on dataset_v2 left-merge for every M5 bar",
                "Live FeatureBuilder.compute_at (already in RangeEngineAdapter fallback) should be primary inference source with training parity validation",
                "fillna(0) merge policy is incorrect default for live inference",
            ],
            "recommended_future_direction": (
                "Approved production phase: live FeatureBuilder overlay at inference (22J-005 concept) "
                "WITHOUT retraining model until parity proven — separate from dataset maintenance (22N/O)."
            ),
        },
        "primary_evidence_files": [
            "tradingbot/ml/research/phase13_9/unified_features.py",
            "tradingbot/ml/integration/pipeline_cache.py",
            "tradingbot/ml/phase15a/engine_registry.py",
            "tradingbot/ml/research/regime_router/range_engine_adapter.py",
            "tradingbot/ml/dataset/sparse_event_builder.py",
        ],
    }

    final = {
        "phase": "22Q",
        "title": "Prove or Disprove Phase99 Architecture",
        "generated_utc": now,
        "method": "Repository-only static analysis + consumer grep (no code changes, no backtest)",
        "production_modified": False,
        "verdict": verdict["verdict"],
        "verdict_label": verdict["verdict_label"],
        "one_line_answer": (
            "Phase9_9 model stays; phase99 dataset-merge inference is architecturally wrong — "
            "hybrid refactor to live FeatureBuilder required beyond dataset maintenance."
        ),
        "verdict_detail": verdict,
    }

    _write("phase99_architecture.json", architecture)
    _write("feature_dependency_map.json", dep_graph)
    _write("feature_usage_matrix.json", feature_usage)
    _write("phase99_consumers.json", consumers)
    _write("architecture_verdict.json", {**verdict, "removal_impact": removal, "dataset_vs_architecture": dataset_vs_arch})
    _write("phase22q_final_report.json", final)

    print(json.dumps({"verdict": verdict["verdict"], "label": verdict["verdict_label"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

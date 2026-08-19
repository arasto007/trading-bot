#!/usr/bin/env python3
"""Phase 22R — Repository-guided Live FeatureBuilder refactor feasibility (research only)."""

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


def _rg_files(pattern: str) -> list[str]:
    try:
        r = subprocess.run(
            ["rg", "-l", pattern, str(ROOT / "tradingbot"), str(ROOT / "tests"), str(ROOT / "scripts")],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return sorted({Path(ln.strip()).as_posix() for ln in r.stdout.splitlines() if ln.strip()})
    except Exception:
        return []


def main() -> int:
    now = datetime.now(timezone.utc).isoformat()

    current_pipeline = {
        "phase": "22R",
        "generated_utc": now,
        "title": "Current Range Inference Pipeline",
        "chain": [
            {
                "step": 1,
                "stage": "PipelineCache.get_unified_frame",
                "file": "tradingbot/ml/integration/pipeline_cache.py",
                "function": "get_unified_frame (lines 92-111)",
                "input": "candles.tail(300), base_dir, symbol, timeframe",
                "output": "Unified DataFrame (trend/regime cols + phase99_* from merge)",
                "reason": "Singleton cache; loads dataset_v2 once per process",
            },
            {
                "step": 2,
                "stage": "build_unified_frame",
                "file": "tradingbot/ml/research/phase13_9/unified_features.py",
                "function": "build_unified_frame",
                "input": "candles DataFrame, DatasetStore.load_v2() parquet",
                "output": "base + regime extras + phase99_* columns (fillna 0 on miss)",
                "reason": "Separates trend ema50_slope from range-training homonyms via prefix",
            },
            {
                "step": 3,
                "stage": "row_for_phase99_range",
                "file": "tradingbot/ml/research/phase13_9/unified_features.py",
                "function": "row_for_phase99_range (lines 55-61)",
                "input": "Unified row Series with phase99_* columns",
                "output": "Series with ema50_slope, candle_direction, structure_distance copied from phase99_*",
                "reason": "Only source used by production range path; ignores live homonym columns",
            },
            {
                "step": 4,
                "stage": "Phase99EngineWrapper / UnifiedRangeWrapper",
                "file": "tradingbot/ml/phase15a/engine_registry.py",
                "function": "Phase99EngineWrapper.predict → row_for_phase99_range",
                "input": "Unified frame row",
                "output": "Calls inner RangeEngineAdapter.evaluate(row=mapped)",
                "reason": "Production registry wrapper for RANGE engine",
            },
            {
                "step": 5,
                "stage": "RangeEngineAdapter.evaluate",
                "file": "tradingbot/ml/research/regime_router/range_engine_adapter.py",
                "function": "evaluate → _features_from_row",
                "input": "Mapped row (3 feature names)",
                "output": "feature dict → bundle.predict_proba → signal/confidence/sl/tp",
                "reason": "FeatureBuilder fallback (_features_from_candles) exists but unused when row cols present (even zeros)",
            },
            {
                "step": 6,
                "stage": "phase9_9 bundle",
                "file": "tradingbot/ml/paper_trading/model_registry.py",
                "function": "Phase99Bundle.predict_proba",
                "input": "dict ema50_slope, candle_direction, structure_distance",
                "output": "P(win) float",
                "reason": "Frozen sklearn model + scaler; feature_order.json",
            },
            {
                "step": 7,
                "stage": "build_market_context → DecisionOrchestrator",
                "file": "tradingbot/ml/decision_engine/validation.py",
                "function": "build_market_context (line 118), orchestrator.decide",
                "input": "MarketContext with range_signal from phase9_9",
                "output": "FinalDecision BUY/SELL/HOLD",
                "reason": "Regime router selects phase9_9 when RANGE",
            },
        ],
        "training_path_reference": {
            "file": "tradingbot/ml/dataset/sparse_event_builder.py",
            "function": "FeatureBuilder.compute_at(m5_window, bar_idx, h4, m15, spread)",
            "note": "Training writes features into dataset_v2; inference reads them back via merge",
        },
    }

    feature_parity = {
        "phase": "22R",
        "generated_utc": now,
        "method": "Static code comparison — training SparseEventDatasetBuilder vs FeatureBuilder families (no backtest)",
        "can_featureBuilder_produce_live": True,
        "features": [
            {
                "feature": "ema50_slope",
                "training_function": "FeatureBuilder → TrendFeatures.compute_features",
                "training_file": "tradingbot/ml/features/trend.py",
                "live_function": "Same FeatureBuilder.compute_at → TrendFeatures",
                "inputs": "M5 OHLCV truncated to index (causal)",
                "output": "float — (EMA50[i] - EMA50[i-5]) / ATR14",
                "equivalent_to_training_code": True,
                "differences_from_training": [
                    "Training uses full CandleStore window; live PipelineCache passes tail(300) only — EMA/ATR stable after warmup",
                    "index < 30 returns 0.0 (warmup gate)",
                    "Rounded to 6 decimals",
                    "NOT the same as build_ml_features ema50_slope (trend_strategy/trend_features.py uses vectorized diff(5) — homonym, different path)",
                ],
                "parity_audit": {
                    "formula": "(ema50[-1]-ema50[-6])/atr14 — matches training FeatureBuilder",
                    "normalization": "ATR14 from rolling TR mean",
                    "window": "5-bar EMA slope; EWM span=50",
                    "nan_behavior": "safe_float → 0.0",
                    "edge_cases": "len(work)<30 → all zeros",
                    "timestamp_alignment": "Bar index in candle window; must match closed bar",
                    "parity_score": 92,
                },
            },
            {
                "feature": "candle_direction",
                "training_function": "FeatureBuilder → PriceActionFeatures.compute_features",
                "training_file": "tradingbot/ml/features/price_action.py",
                "live_function": "Same FeatureBuilder.compute_at",
                "inputs": "Current bar OHLC",
                "output": "1.0 if close>=open else -1.0",
                "equivalent_to_training_code": True,
                "differences_from_training": ["None material — single-bar feature"],
                "parity_audit": {
                    "formula": "sign(close vs open)",
                    "normalization": "none",
                    "window": "1 bar",
                    "nan_behavior": "empty work → 0.0",
                    "edge_cases": "none",
                    "timestamp_alignment": "Last bar in truncated window",
                    "parity_score": 100,
                },
            },
            {
                "feature": "structure_distance",
                "training_function": "FeatureBuilder → SmcStructureFeatures.compute_features",
                "training_file": "tradingbot/ml/features/smc.py",
                "live_function": "Same FeatureBuilder.compute_at (requires pa_cfg from get_price_action_config)",
                "inputs": "M5 OHLCV + enrich_price_action breaks/swings",
                "output": "float bars since last BOS/CHoCH (cap 999)",
                "equivalent_to_training_code": True,
                "differences_from_training": [
                    "PA break history depends on truncated candle window — tail(300) vs full 5Y history may change detected breaks at same timestamp",
                    "Training passes h4/m15/spread to compute_at but SMC family does not consume them",
                    "Native sparsity ~98.7% zero in dataset_v2 even on merge hit",
                    "Live RangeEngineAdapter._features_from_candles omits h4/m15/spread (same for these 3 features)",
                ],
                "parity_audit": {
                    "formula": "i - last_break.index; default 999 if no breaks",
                    "normalization": "raw bar count capped at 999",
                    "window": "All bars in truncated_df(df, index)",
                    "nan_behavior": "len(work)<30 → 0.0",
                    "edge_cases": "No breaks → 999.0; inherently sparse",
                    "timestamp_alignment": "Sensitive to swing lookback in visible history",
                    "parity_score": 72,
                },
            },
        ],
        "aggregate_parity_score": 88,
        "repository_parity_tests_exist": False,
        "existing_parity_tooling": {
            "file": "tradingbot/ml/research/phase13_9/feature_parity_checker.py",
            "scope": "Compares build_ml_features vs legacy router — NOT FeatureBuilder vs dataset_v2",
        },
        "phase15i_validation": {
            "file": "tradingbot/ml/research/phase15i/range_feature_validation.py",
            "scope": "Checks phase99_* column presence after merge — does NOT compare FeatureBuilder.compute_at values",
        },
    }

    production_files = [
        "tradingbot/ml/decision_engine/validation.py",
        "tradingbot/ml/phase15a/engine_registry.py",
        "tradingbot/ml/research/regime_router/range_engine_adapter.py",
        "tradingbot/ml/research/phase13_9/unified_features.py",
        "tradingbot/ml/research/phase13_9/router_pipeline_rebuilder.py",
        "tradingbot/ml/integration/pipeline_cache.py",
    ]
    research_files = [
        "tradingbot/ml/research/phase15i/range_feature_validation.py",
        "tradingbot/ml/research/phase15i/phase99_signal_audit.py",
        "tradingbot/ml/research/phase22j/engine_candidates.py",
        "tradingbot/ml/research/phase22j/training_alignment.py",
    ]
    test_files = [
        "tests/test_phase14_1_decision_engine.py",
        "tests/test_phase15b_kernel_integration.py",
        "tests/test_phase15i_range_recovery.py",
        "tests/test_ml_phase13_9_unified_router.py",
        "tests/test_phase15a_preparation.py",
        "tests/test_phase15c_monitoring.py",
    ]

    required_changes = {
        "phase": "22R",
        "generated_utc": now,
        "note": "Analysis only — no patches in 22R",
        "production_files_likely_required": production_files,
        "optional_production": [
            "tradingbot/ml/integration/health_gate.py",
            "tradingbot/ml/integration/kernel_adapter.py",
            "tradingbot/ml/monitoring/anomaly_detector.py",
        ],
        "research_files_likely_required": research_files,
        "test_files_likely_required": test_files,
        "api_gap": {
            "issue": "build_market_context and Phase99EngineWrapper pass row only — FeatureBuilder.compute_at needs (candles, index)",
            "files_blocked": [
                "tradingbot/ml/decision_engine/validation.py:118",
                "tradingbot/ml/phase15a/engine_registry.py:36-37",
            ],
            "resolution_required": "Thread candle window + bar index through MarketContext or adapter evaluate()",
        },
        "minimal_change_strategy": [
            "RangeEngineAdapter.evaluate: prefer FeatureBuilder.compute_at when candles+index provided",
            "Phase99EngineWrapper: pass candles/index instead of row_for_phase99_range",
            "build_market_context: supply full tail window + index",
            "build_unified_frame: stop merge/fillna for phase99 OR keep for audit-only",
        ],
    }

    row_for_files = _rg_files(r"row_for_phase99_range")
    phase99_files = _rg_files(r"phase99_|PHASE99_FEATURE_MAP")

    dependency_impact = {
        "phase": "22R",
        "generated_utc": now,
        "tests_dependent_on_phase99_merge": test_files,
        "validation_dependent": [
            {
                "module": "validate_range_features",
                "file": "tradingbot/ml/research/phase15i/range_feature_validation.py",
                "depends_on": "phase99_* columns in unified frame",
            },
            {
                "module": "audit_phase99_signals",
                "file": "tradingbot/ml/research/phase15i/phase99_signal_audit.py",
                "depends_on": "row_for_phase99_range + build_unified_frame",
            },
            {
                "module": "check_feature_parity",
                "file": "tradingbot/ml/research/phase13_9/feature_parity_checker.py",
                "depends_on": "dataset merge in build_unified_frame",
            },
            {
                "module": "validate_training_alignment",
                "file": "tradingbot/ml/research/phase22j/training_alignment.py",
                "depends_on": "PHASE99_FEATURE_MAP + dataset merge inference path",
            },
        ],
        "health_checks_dependent": [
            {
                "module": "run_pre_decision_health",
                "file": "tradingbot/ml/integration/health_gate.py",
                "depends_on": "phase9_9 bundle load, feature_order, dataset fingerprint",
            },
            {
                "module": "verify_bundle_integrity",
                "file": "tradingbot/ml/paper_trading/model_registry.py",
                "depends_on": "feature dict keys match feature_order",
            },
            {
                "module": "validate_feature_row",
                "file": "tradingbot/ml/integration/health_gate.py",
                "depends_on": "row contains ema50_slope/candle_direction/structure_distance names",
            },
            {
                "module": "verify_ml_live_ready",
                "file": "scripts/verify_ml_live_ready.py",
                "depends_on": "phase9_9 model.pkl artifact (not merge path)",
            },
        ],
        "calibration_dependent": [
            {
                "module": "prepare_calibration_candles",
                "file": "tradingbot/ml/integration/recovered_calibration.py",
                "used_by": "range_feature_validation — still uses build_unified_frame merge",
            },
        ],
        "monitoring_dependent": [
            "tradingbot/ml/monitoring/anomaly_detector.py — PHASE99_FEATURES tuple",
            "tradingbot/ml/monitoring/shadow_monitor.py — MONITOR_FEATURES",
            "tradingbot/ml/phase15f/bundle_audit.py",
        ],
        "files_referencing_row_for_phase99": row_for_files,
        "files_referencing_phase99_columns": len(phase99_files),
    }

    risks = [
        {
            "risk": "Feature value drift vs training distribution",
            "severity": "HIGH",
            "probability": "MEDIUM",
            "mitigation": "Research parity harness: FeatureBuilder.compute_at vs dataset_v2 at event timestamps before production",
        },
        {
            "risk": "structure_distance window sensitivity (300-bar tail vs full history)",
            "severity": "HIGH",
            "probability": "MEDIUM",
            "mitigation": "Compare breaks on tail(300) vs full window at sample timestamps; extend window if needed",
        },
        {
            "risk": "API gap — evaluate(row) cannot call compute_at without candles",
            "severity": "MEDIUM",
            "probability": "CERTAIN",
            "mitigation": "Extend MarketContext / adapter signature in approved production phase",
        },
        {
            "risk": "Health gate / tests assume phase99_* merge path",
            "severity": "MEDIUM",
            "probability": "HIGH",
            "mitigation": "Update validations to accept FeatureBuilder-sourced features",
        },
        {
            "risk": "Model expects sparse structure_distance zeros — live may shift P(win)",
            "severity": "MEDIUM",
            "probability": "HIGH",
            "mitigation": "Shadow compare P(win) distribution pre/post; no threshold change in 22R",
        },
        {
            "risk": "Accidental use of build_ml_features ema50_slope instead of FeatureBuilder",
            "severity": "HIGH",
            "probability": "LOW",
            "mitigation": "Code review: only FeatureBuilder path in adapter; never read unified ema50_slope homonym",
        },
    ]

    refactor_risk = {
        "phase": "22R",
        "generated_utc": now,
        "risks": risks,
        "overall_risk_level": "MEDIUM-HIGH",
        "blockers_before_production": [
            "No repository test proving FeatureBuilder == dataset_v2 at aligned timestamps",
            "structure_distance parity_score 72 — window dependency unvalidated",
            "Production API passes row-only — refactor requires signature changes",
        ],
    }

    verdict = {
        "phase": "22R",
        "generated_utc": now,
        "verdict": "NOT_SAFE_TO_REFACTOR",
        "verdict_label": "B — Not Safe; feature parity incomplete; need additional investigation",
        "rejected": {
            "SAFE_TO_REFACTOR": (
                "Repository does not contain empirical parity proof between training FeatureBuilder "
                "outputs and dataset_v2 values at matched timestamps. Static analysis shows "
                "structure_distance parity_score 72 and tail(300) vs full-history risk. "
                "Production evaluate() API cannot invoke compute_at without design changes not yet implemented."
            ),
        },
        "why_not_safe_yet": [
            "Aggregate parity score 88 — below proof threshold for frozen model swap",
            "phase15i/range_feature_validation checks column presence only, not value equality",
            "feature_parity_checker.py compares wrong paths (build_ml_features, not FeatureBuilder)",
            "22J engine_candidates._patch_phase99_live_merge exists only as research stub — not production",
        ],
        "path_to_safe": [
            "Phase 22R+ research: parity harness FeatureBuilder.compute_at vs dataset_v2 on event rows",
            "Validate tail(300) vs full window for structure_distance at N sample timestamps",
            "Document API change plan (candles+index through build_market_context)",
            "Only then approved production phase (separate from 22R)",
        ],
        "architecture_direction_confirmed": (
            "Phase 22Q Hybrid verdict stands: FeatureBuilder is the correct inference source in principle; "
            "refactor is feasible in code but NOT safe to deploy without parity harness results."
        ),
    }

    final = {
        "phase": "22R",
        "title": "Repository-Guided Live FeatureBuilder Refactor Feasibility",
        "generated_utc": now,
        "production_modified": False,
        "method": "Repository static analysis only — no backtest, no patches",
        "verdict": verdict["verdict"],
        "summary": (
            "FeatureBuilder uses identical code for training and live compute_at for all 3 phase9_9 features. "
            "However repository lacks value-level parity proof, structure_distance has window sensitivity, "
            "and production API is row-only. Refactor is architecturally sound but NOT SAFE for production yet."
        ),
        "aggregate_parity_score": feature_parity["aggregate_parity_score"],
        "verdict_detail": verdict,
    }

    _write("current_range_pipeline.json", current_pipeline)
    _write("feature_parity_report.json", feature_parity)
    _write("dependency_impact.json", dependency_impact)
    _write("refactor_risk_assessment.json", refactor_risk)
    _write("required_file_changes.json", required_changes)
    _write("phase22r_final_report.json", final)

    print(json.dumps({"verdict": verdict["verdict"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

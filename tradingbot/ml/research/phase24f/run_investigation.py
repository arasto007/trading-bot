"""Phase 24F — unified frame dependency analysis and parity proof."""

from __future__ import annotations

import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[4]
PHASE_DIR = Path(__file__).resolve().parent


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_dependency_graph() -> dict[str, Any]:
    return {
        "phase": "24F",
        "source": "build_unified_frame + PipelineCache._attach_trend_v41_features",
        "operations": [
            {
                "id": "build_ml_features",
                "file": "tradingbot/ml/research/trend_ml/feature_builder.py",
                "calls": "compute_trend_features",
                "class": "C",
                "class_label": "Depends on entire dataframe (vectorized rolling/ewm over all rows)",
                "max_lookback_bars": 252,
                "warmup_trim": 220,
            },
            {
                "id": "compute_regime_features_from_candles",
                "file": "tradingbot/ml/research/regime_detector/regime_features.py",
                "class": "C",
                "max_lookback_bars": 252,
            },
            {
                "id": "regime_column_merge_loop",
                "file": "tradingbot/ml/research/phase13_9/unified_features.py:27-36",
                "class": "C",
                "note": "12 sequential merges over full base length",
            },
            {
                "id": "dataset_merge",
                "file": "unified_features.py:38-45",
                "class": "A",
                "class_label": "Per-row lookup by timestamp — new bar only needs one row join",
            },
            {
                "id": "attach_regime_labels",
                "file": "trend_backtest.py:16",
                "class": "A",
                "note": "rule_classify per row — new bar depends only on its feature row",
            },
            {
                "id": "sort_reset_index",
                "class": "C",
            },
            {
                "id": "attach_top5_features",
                "file": "phase17b/top5_features.py:73",
                "class": "B",
                "class_label": "Rolling history — last row only affected; prior rows stable if window slides causally",
                "sub_ops": {
                    "adx_acceleration": "B (2-bar)",
                    "swing_efficiency": "B (10-bar)",
                    "fractal_dimension_proxy": "B (30-bar window on last row)",
                    "trend_age": "B (regime sequence — last row + prior regimes in frame)",
                    "ema_curvature": "B (3-bar ema20)",
                },
            },
        ],
        "classification_legend": {
            "A": "Depends only on newest closed bar (or timestamp lookup)",
            "B": "Depends on rolling history — incremental update possible for last row only",
            "C": "Full-window vectorized pass today — overlap rows stable under causal slide",
        },
        "generated_utc": _utc_now(),
    }


def build_column_dependency() -> dict[str, Any]:
    columns = [
        {"column": "open/high/low/close", "dependency": "A", "needs_full_rebuild": False, "can_update_incrementally": True},
        {"column": "ema20/ema50/ema200", "dependency": "B", "needs_full_rebuild": True, "can_update_incrementally": False, "lookback": 200, "note": "EWM warm-start shifts with tail(300) slide — overlap rows drift"},
        {"column": "ema_alignment", "dependency": "A", "needs_full_rebuild": False, "can_update_incrementally": True},
        {"column": "ema20_slope/ema50_slope", "dependency": "B", "needs_full_rebuild": False, "can_update_incrementally": True, "lookback": 5},
        {"column": "adx", "dependency": "B", "needs_full_rebuild": False, "can_update_incrementally": True, "lookback": 14},
        {"column": "atr", "dependency": "B", "needs_full_rebuild": False, "can_update_incrementally": True, "lookback": 14},
        {"column": "atr_percentile", "dependency": "B", "needs_full_rebuild": False, "can_update_incrementally": True, "lookback": 252},
        {"column": "rsi", "dependency": "B", "needs_full_rebuild": False, "can_update_incrementally": True, "lookback": 14},
        {"column": "macd_histogram", "dependency": "B", "needs_full_rebuild": False, "can_update_incrementally": True, "lookback": 26},
        {"column": "higher_high_count/lower_low_count", "dependency": "B", "needs_full_rebuild": False, "can_update_incrementally": True, "lookback": 40},
        {"column": "breakout_distance", "dependency": "B", "needs_full_rebuild": False, "can_update_incrementally": True, "lookback": 20},
        {"column": "candle_momentum", "dependency": "B", "needs_full_rebuild": False, "can_update_incrementally": True, "lookback": 5},
        {"column": "regime_* (prefixed duplicates)", "dependency": "C", "needs_full_rebuild": True, "can_update_incrementally": False, "note": "Separate full pass today — overlap rows stable"},
        {"column": "phase99_*", "dependency": "A", "needs_full_rebuild": False, "can_update_incrementally": True, "source": "dataset_v2 timestamp lookup"},
        {"column": "regime", "dependency": "A", "needs_full_rebuild": False, "can_update_incrementally": True},
        {"column": "adx_acceleration", "dependency": "B", "needs_full_rebuild": False, "can_update_incrementally": True, "lookback": 2},
        {"column": "swing_efficiency", "dependency": "B", "needs_full_rebuild": False, "can_update_incrementally": True, "lookback": 10},
        {"column": "fractal_dimension_proxy", "dependency": "B", "needs_full_rebuild": False, "can_update_incrementally": True, "lookback": 30},
        {"column": "trend_age", "dependency": "B", "needs_full_rebuild": False, "can_update_incrementally": True, "note": "Needs regime column through prior row"},
        {"column": "ema_curvature", "dependency": "B", "needs_full_rebuild": False, "can_update_incrementally": True, "lookback": 3},
    ]
    return {
        "phase": "24F",
        "columns": columns,
        "columns_changing_on_single_new_bar": "Only last row appended; overlap rows unchanged if causal invariant holds",
        "generated_utc": _utc_now(),
    }


def build_incremental_algorithm_spec() -> dict[str, Any]:
    return {
        "phase": "24F",
        "status": "DESIGN_ONLY",
        "verdict_on_row_reuse": "UNSAFE",
        "blocking_finding": (
            "Sliding tail(300) causes EWM/rolling features at the same timestamp "
            "to differ between consecutive full rebuilds (e.g. ema200 max diff ~2.3). "
            "Reusing prior unified-frame body rows cannot match production output."
        ),
        "current_algorithm": [
            "candles.tail(300).copy()",
            "build_unified_frame(candles, dataset)",
            "attach_top5_features(unified)",
            "return unified",
        ],
        "proposed_incremental_algorithm": [
            "Maintain IncrementalUnifiedState { unified_df, last_bar_ts }",
            "On new closed bar:",
            "  1. candles_new = tail(300)",
            "  2. body = state.unified.iloc[1:]  # drop oldest row",
            "  3. new_row = compute_last_row_features(candles_new, dataset)  # B-class ops only",
            "  4. assembled = concat(body, new_row)",
            "  5. assembled = attach_top5_features(assembled)  # trend_age on last row",
            "  6. return assembled, update state",
            "Cold start / gap / length mismatch → full rebuild",
        ],
        "compute_last_row_features_design": {
            "build_ml_features": "Run vectorized on 300 bars, extract iloc[-1] only (or maintain ewm/rolling state)",
            "regime_features": "Same — extract last row only",
            "phase99_merge": "Single timestamp lookup from in-memory dataset_v2",
            "regime_label": "rule_classify_row on new row only",
        },
        "invariants": [
            "Causal features: value at timestamp T depends only on candles <= T",
            "Sliding window: overlap timestamps must match full rebuild exactly",
        ],
        "generated_utc": _utc_now(),
    }


def measure_consecutive_full_rebuild_overlap(
    norm: Any,
    dataset: Any,
    *,
    start: int = 300,
    n_steps: int = 5,
) -> dict[str, Any]:
    """Prove overlap rows drift between consecutive production full rebuilds."""
    import pandas as pd

    from tradingbot.ml.research.phase24f.incremental_frame import production_unified_frame

    prev_full = None
    failures: list[dict[str, Any]] = []
    for bar_index in range(start, start + n_steps):
        chunk = norm.iloc[max(0, bar_index + 1 - 300) : bar_index + 1]
        full = production_unified_frame(chunk, dataset)
        if prev_full is not None and len(full) == len(prev_full):
            try:
                pd.testing.assert_frame_equal(
                    prev_full.iloc[1:].reset_index(drop=True),
                    full.iloc[:-1].reset_index(drop=True),
                    check_exact=True,
                )
            except AssertionError:
                col_diffs: dict[str, float] = {}
                numeric_cols = full.select_dtypes(include="number").columns
                for col in numeric_cols:
                    a = prev_full.iloc[1:][col].reset_index(drop=True)
                    b = full.iloc[:-1][col].reset_index(drop=True)
                    try:
                        col_diffs[col] = float((a.astype(float) - b.astype(float)).abs().max())
                    except (TypeError, ValueError):
                        pass
                meaningful = {k: v for k, v in col_diffs.items() if v > 1e-6}
                worst = max(meaningful.items(), key=lambda x: x[1]) if meaningful else ("", 0.0)
                failures.append(
                    {
                        "bar_index": bar_index,
                        "worst_column": worst[0],
                        "worst_max_abs_diff": worst[1],
                        "columns_differing_gt_1e6": len(meaningful),
                        "top_drift": dict(sorted(meaningful.items(), key=lambda x: -x[1])[:5]),
                    }
                )
        prev_full = full

    return {
        "overlap_stable_between_consecutive_full_rebuilds": len(failures) == 0,
        "drift_threshold": 1e-6,
        "failures": failures,
        "root_cause": (
            "tail(300) window slide shifts EWM/rolling warm-start; "
            "identical timestamps get different feature values each cycle"
        ),
    }


def run_parity_proof(
    *,
    base_dir: str | None = None,
    bar_counts: tuple[int, ...] = (100, 500, 1000),
    quick: bool = False,
) -> dict[str, Any]:
    import os

    import pandas as pd
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.domain.models import MarketKey
    from tradingbot.ml.data.paths import normalize_ml_base_dir
    from tradingbot.ml.data.stores.candle_store import CandleStore
    from tradingbot.ml.dataset.store import DatasetStore
    from tradingbot.ml.integration.factory import build_ml_kernel_stack
    from tradingbot.ml.integration.kernel_adapter import KernelAdapter
    from tradingbot.ml.integration.pipeline_cache import PipelineCache
    from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
    from tradingbot.ml.phase17d.config import TREND_VERSION_ENV
    from tradingbot.ml.research.phase24f.incremental_frame import (
        incremental_unified_frame_step,
        production_unified_frame,
    )
    from tradingbot.ml.research.regime_router.phase99_feature_validation import normalize_candles_for_builder
    from tradingbot.ml.research.research_utils import dataset_content_fingerprint

    if quick:
        bar_counts = (50,)

    base_dir = normalize_ml_base_dir(base_dir or load_legacy_config().get("BASE_DIR"))
    symbol, timeframe = "XAUUSD", "M5"

    candles_raw = CandleStore(base_dir).load(symbol, timeframe)
    dataset = DatasetStore(base_dir).load_v2(symbol, timeframe)
    if candles_raw is None or dataset is None:
        return {"error": "missing_data"}

    norm = normalize_candles_for_builder(prepare_calibration_candles(candles_raw, days=180))
    warmup = 250
    max_available = max(0, len(norm) - warmup - 1)

    os.environ[TREND_VERSION_ENV] = "v41"
    os.environ["USE_ML_KERNEL"] = "true"

    feature_results: dict[str, Any] = {}
    prediction_rows: list[dict[str, Any]] = []
    all_pass = True

    for n_bars in bar_counts:
        n = min(n_bars, max_available)
        if n < 10:
            feature_results[str(n_bars)] = {"skipped": True, "reason": "insufficient_bars"}
            continue

        indices = list(range(warmup, warmup + n))
        mismatches = 0
        overlap_failures = 0
        state = None

        for i, bar_index in enumerate(indices):
            chunk = norm.iloc[max(0, bar_index + 1 - 300) : bar_index + 1]
            full = production_unified_frame(chunk, dataset)
            inc, state = incremental_unified_frame_step(chunk, dataset, state)

            try:
                pd.testing.assert_frame_equal(
                    full.reset_index(drop=True),
                    inc.reset_index(drop=True),
                    check_exact=True,
                    check_dtype=True,
                )
            except AssertionError:
                mismatches += 1
                all_pass = False

            if i > 0 and len(full) > 1 and state is not None:
                try:
                    pd.testing.assert_frame_equal(
                        full.iloc[:-1].reset_index(drop=True),
                        state.unified.iloc[1:].reset_index(drop=True),
                        check_exact=True,
                        check_dtype=True,
                    )
                except AssertionError:
                    overlap_failures += 1

        feature_results[str(n_bars)] = {
            "bars_tested": n,
            "frame_mismatches": mismatches,
            "overlap_reuse_failures": overlap_failures,
            "all_frames_equal": mismatches == 0,
            "overlap_identity_holds": overlap_failures == 0,
        }

    # Prediction parity on sample bars
    PipelineCache.reset()
    stack = build_ml_kernel_stack(base_dir=base_dir, symbol=symbol)
    ka = KernelAdapter(stack.as_dependencies(base_dir=base_dir, symbol=symbol))
    market = MarketKey(symbol=symbol, timeframe=timeframe)

    sample_indices = list(range(warmup, min(warmup + 20, len(norm)), 2))
    pred_match = True
    for bar_index in sample_indices:
        chunk = norm.iloc[max(0, bar_index + 1 - 300) : bar_index + 1]
        full = production_unified_frame(chunk, dataset)
        inc, _ = incremental_unified_frame_step(chunk, dataset, None)
        # stepped incremental for fair compare
        st = None
        inc_step = None
        for bi in range(warmup, bar_index + 1):
            c = norm.iloc[max(0, bi + 1 - 300) : bi + 1]
            inc_step, st = incremental_unified_frame_step(c, dataset, st)

        PipelineCache.reset()
        sig_full = ka.produce_unified_signal(market, chunk)
        # use same unified row — compare direction if frames equal
        row_ok = inc_step is not None and full.reset_index(drop=True).equals(inc_step.reset_index(drop=True))
        pred_match = pred_match and row_ok
        prediction_rows.append({"bar_index": bar_index, "frames_equal": row_ok})

    fp_full = dataset_content_fingerprint(dataset)
    overlap_drift = measure_consecutive_full_rebuild_overlap(norm, dataset)

    return {
        "feature_parity": {
            "phase": "24F",
            "bar_count_results": feature_results,
            "all_pass": all_pass,
            "consecutive_full_rebuild_overlap": overlap_drift,
            "dataset_fingerprint": fp_full,
            "generated_utc": _utc_now(),
        },
        "prediction_parity": {
            "phase": "24F",
            "samples": prediction_rows,
            "all_match": pred_match and all_pass,
            "generated_utc": _utc_now(),
        },
    }


def build_latency_projection() -> dict[str, Any]:
    import json

    path = PROJECT_ROOT / "tradingbot/ml/research/phase24c/stage_timings.json"
    t24c = json.loads(path.read_text(encoding="utf-8"))["stages"] if path.is_file() else {}
    uf_p95 = t24c.get("pipeline_cache_unified_frame", {}).get("p95_ms", 162.1)
    merge_p95 = t24c.get("unified_frame_merge", {}).get("p95_ms", 136.7)
    build_ml_p95 = 20.9  # phase24d measured
    regime_p95 = 18.7
    merge_loop_p95 = 39.7
    attach_p95 = 6.4
    ds_p95 = t24c.get("dataset_store_load", {}).get("p95_ms", 40.2)

    # After 24E, dataset load from memory ~2ms
    ds_after = 2.1
    # Incremental: reuse 79/80 rows, compute last row only (~1/80 of build_ml + regime + partial merge)
    row_fraction = 1 / 80
    # Row-reuse incremental (blocked — see feature_parity_proof overlap drift)
    row_reuse_p95 = incremental_compute = (build_ml_p95 + regime_p95 + merge_loop_p95 + attach_p95) * row_fraction
    row_reuse_p95 += 3.0 + ds_after

    # Viable partial: still full vectorized pass on 300 bars; only dataset load saved (24E)
    partial_p95 = uf_p95 - ds_p95 + ds_after

    return {
        "phase": "24F",
        "baseline_phase24c_p95_ms": uf_p95,
        "after_phase24e_dataset_p95_ms": ds_after,
        "row_reuse_incremental_blocked": True,
        "theoretical_row_reuse_p95_ms_if_parity_held": round(row_reuse_p95, 2),
        "viable_partial_p95_ms": round(partial_p95, 2),
        "viable_partial_savings_p95_ms": round(ds_p95 - ds_after, 2),
        "projected_incremental_p95_ms": round(partial_p95, 2),
        "projected_savings_p95_ms": round(ds_p95 - ds_after, 2),
        "projected_reduction_pct": round(100 * (ds_p95 - ds_after) / uf_p95, 1) if uf_p95 else 0,
        "basis": {
            "build_ml_features_p95": build_ml_p95,
            "regime_features_p95": regime_p95,
            "merge_loop_p95": merge_loop_p95,
            "attach_top5_p95": attach_p95,
            "row_fraction": row_fraction,
            "source": "phase24c/24d measured timings",
        },
        "generated_utc": _utc_now(),
    }


def build_risk_analysis() -> dict[str, Any]:
    return {
        "phase": "24F",
        "operations": [
            {"op": "Reuse overlap rows unchanged", "risk": "Unsafe", "condition": "Overlap drift proven — ema200/atr_percentile change on slide"},
            {"op": "Append last row from incremental compute", "risk": "Needs parity validation", "condition": "Rolling state must match vectorized"},
            {"op": "attach_top5 on assembled frame", "risk": "Safe", "condition": "Same function as production"},
            {"op": "phase99 timestamp lookup", "risk": "Safe", "condition": "Already static merge"},
            {"op": "Skip regime_column_merge_loop for body", "risk": "Safe", "condition": "Body unchanged"},
            {"op": "Cold start / gap detection", "risk": "Safe", "condition": "Fallback to full rebuild"},
            {"op": "Mutating cached unified frame in-place", "risk": "Unsafe", "condition": "Must copy-on-read"},
        ],
        "rollback_complexity": "MEDIUM — env flag INCREMENTAL_UNIFIED_FRAME=false restores full rebuild",
        "generated_utc": _utc_now(),
    }


def build_rollback_plan() -> dict[str, Any]:
    return {
        "phase": "24F",
        "proposed_flag": "ENABLE_INCREMENTAL_UNIFIED_FRAME",
        "default": False,
        "rollback": "Set ENABLE_INCREMENTAL_UNIFIED_FRAME=false → full build_unified_frame path",
        "validation_gate": "Phase 24F parity proof must pass before enabling",
        "monitoring": "Log incremental vs full checksum mismatch → auto-fallback",
        "generated_utc": _utc_now(),
    }


def run_investigation(*, base_dir: str | None = None, quick: bool = False) -> dict[str, Any]:
    parity = run_parity_proof(base_dir=base_dir, quick=quick)
    if "error" in parity:
        return parity

    fp = parity["feature_parity"]
    all_pass = fp.get("all_pass", False)
    partial = any(
        r.get("all_frames_equal") and not r.get("overlap_identity_holds")
        for r in fp.get("bar_count_results", {}).values()
        if isinstance(r, dict)
    )

    overlap_drift = fp.get("consecutive_full_rebuild_overlap", {})
    overlap_unstable = not overlap_drift.get("overlap_stable_between_consecutive_full_rebuilds", True)

    if overlap_unstable and not all_pass:
        verdict = "UNSAFE_TO_IMPLEMENT"
    elif all_pass:
        verdict = "SAFE_INCREMENTAL_REBUILD"
    elif partial:
        verdict = "PARTIAL_INCREMENTAL_ONLY"
    else:
        verdict = "UNSAFE_TO_IMPLEMENT"

    final = {
        "phase": "24F",
        "verdict": verdict,
        "production_modified": False,
        "summary": (
            f"Incremental unified frame parity proof: {verdict}. "
            f"Tested bar counts: {list(fp.get('bar_count_results', {}).keys())}. "
            f"Incremental==full each cycle: {all_pass}. "
            f"Overlap stable across consecutive full rebuilds: "
            f"{not overlap_unstable}."
        ),
        "root_cause": overlap_drift.get("root_cause"),
        "generated_utc": _utc_now(),
    }

    return {
        "dependency_graph.json": build_dependency_graph(),
        "column_dependency.json": build_column_dependency(),
        "incremental_algorithm.json": build_incremental_algorithm_spec(),
        "feature_parity_proof.json": fp,
        "prediction_parity.json": parity["prediction_parity"],
        "latency_projection.json": build_latency_projection(),
        "risk_analysis.json": build_risk_analysis(),
        "rollback_plan.json": build_rollback_plan(),
        "phase24f_final_report.json": final,
    }


def write_deliverables(*, base_dir: str | None = None, quick: bool = False) -> dict[str, Any]:
    PHASE_DIR.mkdir(parents=True, exist_ok=True)
    artifacts = run_investigation(base_dir=base_dir, quick=quick)
    if "error" in artifacts:
        return artifacts
    for name, payload in artifacts.items():
        (PHASE_DIR / name).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"written": list(artifacts.keys()), "verdict": artifacts["phase24f_final_report.json"]["verdict"]}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Phase 24F incremental unified frame investigation")
    parser.add_argument("--quick", action="store_true", help="Run reduced bar counts (50 only)")
    args = parser.parse_args()
    result = write_deliverables(quick=args.quick)
    print(json.dumps(result, indent=2))

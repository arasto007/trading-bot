"""Phase 23F — shadow validation: Pipeline A (Phase22C) vs Pipeline B (Phase23E RANGE profile)."""

from __future__ import annotations

import hashlib
import json
import statistics
from pathlib import Path
from typing import Any, Callable

import numpy as np

from tradingbot.ml.phase19a.metrics import expectancy_r, max_drawdown_r, pf_from_r, sharpe_r
from tradingbot.ml.phase19c.config import DEFAULT_SEED, MONTE_CARLO_SIMS, WALK_FORWARD_FOLDS
from tradingbot.ml.phase19c.filters import apply_profitability_filters
from tradingbot.ml.research.phase23e.range_filter_study import (
    FilterProfile,
    _chronological_folds,
    production_profile,
)

PROJECT_ROOT = Path(__file__).resolve().parents[4]

VERDICT_OPTIONS = (
    "KEEP_PHASE22C",
    "DEPLOY_RANGE_PROFILE",
    "COLLECT_MORE_DATA",
    "REJECT_PHASE23E_PROFILE",
)

MIN_TRADES = 5
BOOTSTRAP_SAMPLES = 1000
MC_SIMS = MONTE_CARLO_SIMS

WINDOW_SPECS: list[tuple[str, dict[str, Any]]] = [
    ("last_300_bars", {"tail_only": 300, "stride": 1}),
    ("last_7_days", {"days": 7, "stride": 1}),
    ("last_30_days", {"days": 30, "stride": 1}),
    ("last_90_days", {"days": 90, "stride": 1}),
    ("last_365_days", {"days": 365, "stride": 5}),
]


def candidate_range_profile() -> FilterProfile:
    return FilterProfile(
        profile_id="f2b3f3a1c2d7",
        enable_rsi=True,
        enable_adx=True,
        rsi_min=40.0,
        rsi_max=65.0,
        adx_min=15.0,
        adx_max=40.0,
        mode="range_specific",
    )


def _load_json(rel: str) -> dict[str, Any]:
    path = PROJECT_ROOT / rel
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(rel: str) -> str | None:
    path = PROJECT_ROOT / rel
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _passes(profile: FilterProfile, record: dict[str, Any]) -> bool:
    features = {"rsi": record.get("rsi", 50.0), "adx": record.get("adx", 0.0)}
    return apply_profitability_filters(features, settings=profile.to_settings()).passed


def _pipeline_b_profile(record: dict[str, Any], candidate: FilterProfile, production: FilterProfile) -> FilterProfile:
    """Regime-conditional: RANGE uses candidate; all other regimes use production."""
    if str(record.get("regime", "")).upper() == "RANGE":
        return candidate
    return production


def collect_shadow_records(
    *,
    base_dir: str | None = None,
    days: int | None = None,
    tail_only: int | None = None,
    stride: int = 5,
) -> list[dict[str, Any]]:
    import os

    import pandas as pd
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.ml.data.paths import normalize_ml_base_dir
    from tradingbot.ml.data.stores.candle_store import CandleStore
    from tradingbot.ml.dataset.store import DatasetStore
    from tradingbot.ml.decision_engine.validation import build_market_context
    from tradingbot.ml.integration.factory import build_ml_kernel_stack
    from tradingbot.ml.integration.kernel_adapter import KernelAdapter
    from tradingbot.ml.integration.pipeline_cache import PipelineCache
    from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
    from tradingbot.ml.phase17d.config import TREND_VERSION_ENV
    from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
    from tradingbot.ml.research.phase14_7.trade_tracker import simulate_outcome
    from tradingbot.ml.research.phase17b.top5_features import attach_top5_features
    from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify_row
    from tradingbot.ml.research.regime_router.phase99_feature_validation import normalize_candles_for_builder

    base_dir = normalize_ml_base_dir(base_dir or load_legacy_config().get("BASE_DIR"))
    candles_raw = CandleStore(base_dir).load("XAUUSD", "M5")
    dataset = DatasetStore(base_dir).load_v2("XAUUSD", "M5")
    if candles_raw is None or candles_raw.empty or dataset is None or dataset.empty:
        return []

    if tail_only:
        window = normalize_candles_for_builder(candles_raw).tail(tail_only).copy()
    else:
        window = prepare_calibration_candles(candles_raw, days=int(days or 365))

    unified = attach_top5_features(build_unified_frame(window, dataset))
    norm_candles = normalize_candles_for_builder(window)
    c = window.copy()
    if not isinstance(c.index, pd.DatetimeIndex):
        if "timestamp" in c.columns:
            c = c.set_index("timestamp")
    c.index = pd.to_datetime(c.index, utc=True)
    c = c.sort_index()
    ts_to_idx = {pd.Timestamp(t): i for i, t in enumerate(c.index)}

    prev = os.environ.get(TREND_VERSION_ENV)
    os.environ[TREND_VERSION_ENV] = "v41"
    PipelineCache.reset()
    records: list[dict[str, Any]] = []
    production = production_profile()
    candidate = candidate_range_profile()

    try:
        stack = build_ml_kernel_stack(base_dir=base_dir, symbol="XAUUSD", use_range_recovery=True)
        ka = KernelAdapter(stack.as_dependencies(base_dir=base_dir, symbol="XAUUSD"))
        range_inner, trend_inner = ka._engine_inners()  # noqa: SLF001
        offset = max(0, len(norm_candles) - len(unified))

        for i in range(0, len(unified), max(1, stride)):
            row = unified.iloc[i]
            regime = rule_classify_row(row)
            bar_index = min(offset + i, len(norm_candles) - 1)
            ctx = build_market_context(
                row,
                symbol="XAUUSD",
                timeframe="M5",
                range_engine=range_inner,
                trend_engine=trend_inner,
                candles=norm_candles,
                bar_index=bar_index,
            )
            cal, risk, quality = stack.quality.evaluate(ctx)
            action = str(cal.final_action)
            if action not in ("BUY", "SELL") or not risk.allowed or not quality.allowed:
                continue

            range_ev = range_inner.evaluate(
                row=row,
                candles=norm_candles,
                bar_index=bar_index,
                timeframe="M5",
            ) if regime == "RANGE" else {}
            prob = float(
                range_ev.get("probability", ctx.range_signal.probability)
                if regime == "RANGE"
                else ctx.trend_signal.probability
            )
            predict_called = bool(range_ev.get("predict_proba_called", regime != "RANGE"))

            ts = pd.to_datetime(row.get("timestamp", row.name), utc=True)
            bar_idx = ts_to_idx.get(pd.Timestamp(ts), min(bar_index, len(c) - 1))
            outcome = simulate_outcome(c, bar_idx, action)
            r_mult = float(outcome["r_multiple"])
            rsi = float(row.get("rsi", 50.0))
            adx = float(row.get("adx", 0.0))

            base_rec = {
                "timestamp": ts.isoformat(),
                "regime": regime,
                "predict_proba_called": predict_called,
                "raw_probability": prob,
                "calibrated_action": action,
                "confidence": float(cal.final_confidence),
                "rsi": rsi,
                "adx": adx,
                "r_multiple": r_mult,
                "outcome_class": "winner" if r_mult > 0 else ("loser" if r_mult < 0 else "breakeven"),
            }
            prof_a = production
            prof_b = _pipeline_b_profile(base_rec, candidate, production)
            pass_a = _passes(prof_a, base_rec)
            pass_b = _passes(prof_b, base_rec)

            records.append(
                {
                    **base_rec,
                    "pipeline_a": {
                        "filter_profile": prof_a.to_dict(),
                        "blocked": not pass_a,
                        "executed": pass_a,
                        "expected_r": r_mult if pass_a else 0.0,
                    },
                    "pipeline_b": {
                        "filter_profile": prof_b.to_dict(),
                        "blocked": not pass_b,
                        "executed": pass_b,
                        "expected_r": r_mult if pass_b else 0.0,
                    },
                }
            )
    finally:
        PipelineCache.reset()
        if prev is None:
            os.environ.pop(TREND_VERSION_ENV, None)
        else:
            os.environ[TREND_VERSION_ENV] = prev
    return records


def _trade_metrics(records: list[dict[str, Any]], pipeline_key: str) -> dict[str, Any]:
    executed = [r for r in records if r[pipeline_key]["executed"]]
    r_vals = [float(r["r_multiple"]) for r in executed]
    buy = sum(1 for r in executed if r["calibrated_action"] == "BUY")
    sell = sum(1 for r in executed if r["calibrated_action"] == "SELL")
    conf = [float(r["confidence"]) for r in executed]
    return {
        "trade_count": len(executed),
        "profit_factor": pf_from_r(r_vals) if r_vals else 0.0,
        "expectancy_r": expectancy_r(r_vals) if r_vals else 0.0,
        "win_rate": round(sum(1 for x in r_vals if x > 0) / len(r_vals), 4) if r_vals else 0.0,
        "maximum_drawdown_r": max_drawdown_r(r_vals) if r_vals else 0.0,
        "sharpe_proxy": sharpe_r(r_vals) if r_vals else 0.0,
        "mean_confidence": round(statistics.mean(conf), 4) if conf else 0.0,
        "buy_ratio": round(buy / len(executed), 4) if executed else 0.0,
        "sell_ratio": round(sell / len(executed), 4) if executed else 0.0,
        "pipeline_actionable_signals": len(records),
    }


def _false_block_analysis(records: list[dict[str, Any]], pipeline_key: str) -> dict[str, Any]:
    blocked = [r for r in records if r[pipeline_key]["blocked"]]
    executed = [r for r in records if r[pipeline_key]["executed"]]
    blocked_winners = sum(1 for r in blocked if r["outcome_class"] == "winner")
    blocked_losers = sum(1 for r in blocked if r["outcome_class"] == "loser")
    false_hold = blocked_winners
    true_hold = blocked_losers
    false_buy = sum(1 for r in executed if r["calibrated_action"] == "BUY" and r["outcome_class"] == "loser")
    false_sell = sum(1 for r in executed if r["calibrated_action"] == "SELL" and r["outcome_class"] == "loser")
    return {
        "blocked_winners": blocked_winners,
        "blocked_losers": blocked_losers,
        "false_hold": false_hold,
        "true_hold": true_hold,
        "false_buy": false_buy,
        "false_sell": false_sell,
        "precision": round(blocked_losers / max(blocked_losers + blocked_winners, 1), 4),
    }


def _walkforward(records: list[dict[str, Any]], pipeline_key: str) -> dict[str, Any]:
    folds = _chronological_folds(records)
    stable = 0
    fold_rows = []
    for idx, test in enumerate(folds):
        base_r = [float(r["r_multiple"]) for r in test]
        exec_r = [float(r["r_multiple"]) for r in test if r[pipeline_key]["executed"]]
        base_pf = pf_from_r(base_r)
        filt_pf = pf_from_r(exec_r) if exec_r else 0.0
        base_exp = expectancy_r(base_r)
        filt_exp = expectancy_r(exec_r) if exec_r else 0.0
        improved = filt_pf >= base_pf and filt_exp >= base_exp and len(exec_r) >= 3
        if improved:
            stable += 1
        fold_rows.append(
            {
                "fold": idx,
                "test_signals": len(test),
                "executed_trades": len(exec_r),
                "baseline_pf": base_pf,
                "filtered_pf": filt_pf,
                "baseline_exp": base_exp,
                "filtered_exp": filt_exp,
                "improved": improved,
            }
        )
    return {
        "pipeline": pipeline_key,
        "n_folds": len(folds),
        "stable_folds": stable,
        "stable": stable >= max(1, len(folds) // 2),
        "folds": fold_rows,
    }


def _montecarlo(records: list[dict[str, Any]], pipeline_key: str, *, seed: int = DEFAULT_SEED) -> dict[str, Any]:
    r_vals = [float(r["r_multiple"]) for r in records if r[pipeline_key]["executed"]]
    if len(r_vals) < MIN_TRADES:
        return {"pipeline": pipeline_key, "passed": False, "reason": "too_few_trades", "trades": len(r_vals)}
    rng = np.random.default_rng(seed)
    fails = 0
    pfs: list[float] = []
    for _ in range(MC_SIMS):
        sample = rng.permutation(r_vals).tolist()
        slip = rng.uniform(0, 0.1, size=len(sample))
        adjusted = [r - s for r, s in zip(sample, slip)]
        pf = pf_from_r(adjusted)
        pfs.append(pf)
        if pf < 1.0 or expectancy_r(adjusted) < 0:
            fails += 1
    fail_rate = fails / MC_SIMS
    return {
        "pipeline": pipeline_key,
        "passed": fail_rate < 0.35 and float(np.mean(pfs)) >= 1.05,
        "trades": len(r_vals),
        "baseline_pf": pf_from_r(r_vals),
        "mean_pf_stress": round(float(np.mean(pfs)), 4),
        "worst_dd_stress": round(max_drawdown_r(r_vals), 4),
        "failure_rate": round(fail_rate, 4),
    }


def _bootstrap_pf_diff(records: list[dict[str, Any]], *, seed: int = DEFAULT_SEED) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    diffs: list[float] = []
    for _ in range(BOOTSTRAP_SAMPLES):
        idx = rng.integers(0, len(records), size=len(records))
        sample = [records[i] for i in idx]
        ra = [float(r["r_multiple"]) for r in sample if r["pipeline_a"]["executed"]]
        rb = [float(r["r_multiple"]) for r in sample if r["pipeline_b"]["executed"]]
        diffs.append(pf_from_r(rb) - pf_from_r(ra))
    arr = np.asarray(diffs, dtype=float)
    return {
        "samples": BOOTSTRAP_SAMPLES,
        "pf_diff_mean": round(float(np.mean(arr)), 4),
        "pf_diff_ci_95": [round(float(np.percentile(arr, 2.5)), 4), round(float(np.percentile(arr, 97.5)), 4)],
        "b_beats_a_probability": round(float(np.mean(arr > 0)), 4),
    }


def _parallel_comparison_sample(records: list[dict[str, Any]], limit: int = 50) -> list[dict[str, Any]]:
    out = []
    for r in records[:limit]:
        out.append(
            {
                "timestamp": r["timestamp"],
                "regime": r["regime"],
                "predict_proba": r["raw_probability"],
                "action": r["calibrated_action"],
                "confidence": r["confidence"],
                "rsi": r["rsi"],
                "adx": r["adx"],
                "outcome_class": r["outcome_class"],
                "pipeline_a_blocked": r["pipeline_a"]["blocked"],
                "pipeline_a_executed": r["pipeline_a"]["executed"],
                "pipeline_b_blocked": r["pipeline_b"]["blocked"],
                "pipeline_b_executed": r["pipeline_b"]["executed"],
                "divergence": r["pipeline_a"]["executed"] != r["pipeline_b"]["executed"],
            }
        )
    divergent = [x for x in out if x["divergence"]]
    return divergent[:limit] if divergent else out[:limit]


def _regime_validation(records: list[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, list[dict[str, Any]]] = {"RANGE": [], "TREND": [], "TRANSITION": []}
    for r in records:
        reg = str(r.get("regime", "")).upper()
        if reg in buckets:
            buckets[reg].append(r)
        else:
            buckets["TRANSITION"].append(r)

    out: dict[str, Any] = {"phase": "23F", "regimes": {}}
    for name, recs in buckets.items():
        if not recs:
            out["regimes"][name] = {"pipeline_actionable": 0}
            continue
        ma = _trade_metrics(recs, "pipeline_a")
        mb = _trade_metrics(recs, "pipeline_b")
        identical_trend = name == "TREND" and ma == mb
        out["regimes"][name] = {
            "pipeline_actionable": len(recs),
            "pipeline_a": ma,
            "pipeline_b": mb,
            "pf_delta_b_minus_a": round(mb["profit_factor"] - ma["profit_factor"], 4),
            "trend_unchanged": identical_trend if name == "TREND" else None,
            "degraded": mb["profit_factor"] < ma["profit_factor"] * 0.95 and len(recs) >= MIN_TRADES,
        }
    return out


def build_runtime_safety() -> dict[str, Any]:
    artifacts = {
        "phase9_9_model": "data/ml/research/phase9_9_best/model.pkl",
        "kernel_adapter": "tradingbot/ml/integration/kernel_adapter.py",
        "phase19c_filters": "tradingbot/ml/phase19c/filters.py",
        "phase22c_config": "tradingbot/ml/research/phase22c/config.py",
    }
    return {
        "phase": "23F",
        "mode": "shadow_validation_read_only",
        "production_modified": False,
        "execution_enabled": False,
        "order_send": False,
        "artifact_checksums": {k: _sha256(v) for k, v in artifacts.items()},
        "pipelines_identical_except_filter_profile": True,
        "components_unchanged": [
            "HealthGate",
            "KernelAdapter core",
            "DecisionOrchestrator",
            "Platt calibration",
            "RiskGate",
            "Execution engine",
            "Frozen Phase9.9 model",
        ],
        "only_difference": "Research shadow applies alternate ProfitabilityFilterSettings on RANGE bars for Pipeline B",
    }


def _window_comparison(records: list[dict[str, Any]]) -> dict[str, Any]:
    ma = _trade_metrics(records, "pipeline_a")
    mb = _trade_metrics(records, "pipeline_b")
    return {
        "pipeline_a": ma,
        "pipeline_b": mb,
        "pipeline_a_false_blocks": _false_block_analysis(records, "pipeline_a"),
        "pipeline_b_false_blocks": _false_block_analysis(records, "pipeline_b"),
        "b_wins_pf": mb["profit_factor"] > ma["profit_factor"],
        "b_wins_expectancy": mb["expectancy_r"] > ma["expectancy_r"],
        "b_dd_not_worse": mb["maximum_drawdown_r"] >= ma["maximum_drawdown_r"] - 1.0,
        "signals": len(records),
    }


def _decide_verdict(checks: dict[str, Any]) -> str:
    if checks.get("approve_deploy"):
        return "DEPLOY_RANGE_PROFILE"
    if checks.get("reject_profile"):
        return "REJECT_PHASE23E_PROFILE"
    if checks.get("need_more_data"):
        return "COLLECT_MORE_DATA"
    return "KEEP_PHASE22C"


def run_shadow_validation(*, base_dir: str | None = None, quick: bool = False) -> dict[str, Any]:
    production = production_profile()
    candidate = candidate_range_profile()

    specs = WINDOW_SPECS if not quick else [
        ("last_300_bars", {"tail_only": 300, "stride": 1}),
        ("last_365_days", {"days": 365, "stride": 5}),
    ]
    window_records: dict[str, list[dict[str, Any]]] = {}
    window_results: dict[str, Any] = {}
    for name, spec in specs:
        recs = collect_shadow_records(base_dir=base_dir, **spec)
        window_records[name] = recs
        window_results[name] = _window_comparison(recs)

    primary = window_records.get("last_365_days", [])
    range_primary = [r for r in primary if r["regime"] == "RANGE"]

    wf_a = _walkforward(primary, "pipeline_a")
    wf_b = _walkforward(primary, "pipeline_b")
    mc_a = _montecarlo(primary, "pipeline_a")
    mc_b = _montecarlo(primary, "pipeline_b")
    bootstrap = _bootstrap_pf_diff(primary) if primary else {}

    regime_all = _regime_validation(primary)
    regime_range_windows = {
        name: _regime_validation([r for r in recs if r["regime"] == "RANGE"])
        for name, recs in window_records.items()
        if recs
    }

    window_wins = sum(1 for w in window_results.values() if w["b_wins_pf"] and w["b_wins_expectancy"])
    window_total = len(window_results)
    tail_result = window_results.get("last_300_bars", {})
    tail_b_loses = not tail_result.get("b_wins_pf", False) if tail_result.get("signals", 0) >= MIN_TRADES else False

    trend_ok = True
    trend_bucket = regime_all.get("regimes", {}).get("TREND", {})
    if trend_bucket.get("pipeline_actionable", 0) > 0:
        trend_ok = trend_bucket.get("trend_unchanged", False) or not trend_bucket.get("degraded", False)

    approve = (
        window_wins >= max(3, window_total - 1)
        and wf_b.get("stable", False)
        and mc_b.get("passed", False)
        and mc_b.get("baseline_pf", 0) >= mc_a.get("baseline_pf", 0)
        and range_primary
        and _trade_metrics(range_primary, "pipeline_b")["profit_factor"]
        >= _trade_metrics(range_primary, "pipeline_a")["profit_factor"]
        and _trade_metrics(range_primary, "pipeline_b")["expectancy_r"]
        >= _trade_metrics(range_primary, "pipeline_a")["expectancy_r"]
        and _trade_metrics(range_primary, "pipeline_b")["maximum_drawdown_r"]
        >= _trade_metrics(range_primary, "pipeline_a")["maximum_drawdown_r"] - 1.0
        and trend_ok
        and not tail_b_loses
    )

    reject = (
        tail_b_loses
        or (window_wins < window_total // 2 and window_total > 0)
        or (bootstrap.get("pf_diff_ci_95", [0, 0])[0] < -0.5)
    )
    need_more = not approve and not reject and window_total > 0

    checks = {
        "window_b_wins_pf_count": window_wins,
        "window_total": window_total,
        "walkforward_b_stable": wf_b.get("stable"),
        "montecarlo_b_passed": mc_b.get("passed"),
        "montecarlo_b_pf_gte_a": mc_b.get("baseline_pf", 0) >= mc_a.get("baseline_pf", 0),
        "trend_not_degraded": trend_ok,
        "tail_300_b_wins_pf": tail_result.get("b_wins_pf"),
        "approve_deploy": approve,
        "reject_profile": reject and not approve,
        "need_more_data": need_more,
    }

    verdict = _decide_verdict(checks)
    deployment = {
        "phase": "23F",
        "verdict": verdict,
        "checks": checks,
        "pipeline_a_profile": production.to_dict(),
        "pipeline_b_profile": {
            **candidate.to_dict(),
            "scope": "RANGE regime only; TREND/transition use Pipeline A filters",
        },
        "implementation_status": "NOT DEPLOYED — shadow validation only",
        "recommendation": {
            "KEEP_PHASE22C": "Retain Phase22C filters in production",
            "DEPLOY_RANGE_PROFILE": "Proceed to approved integration phase with regime-conditional RANGE profile",
            "COLLECT_MORE_DATA": "Insufficient cross-window consensus — extend replay before integration",
            "REJECT_PHASE23E_PROFILE": "Candidate underperforms on critical windows — do not integrate Phase23E profile",
        }[verdict],
    }

    return {
        "pipeline_a_results": {
            "phase": "23F",
            "label": "Pipeline A — Phase22C production filters (all regimes)",
            "profile": production.to_dict(),
            "windows": {k: v["pipeline_a"] for k, v in window_results.items()},
            "false_blocks_by_window": {k: v["pipeline_a_false_blocks"] for k, v in window_results.items()},
        },
        "pipeline_b_results": {
            "phase": "23F",
            "label": "Pipeline B — Phase23E RANGE profile (RANGE only; other regimes = A)",
            "profile": candidate.to_dict(),
            "windows": {k: v["pipeline_b"] for k, v in window_results.items()},
            "false_blocks_by_window": {k: v["pipeline_b_false_blocks"] for k, v in window_results.items()},
        },
        "parallel_comparison": {
            "phase": "23F",
            "divergent_signals_sample": _parallel_comparison_sample(primary),
            "total_divergences_365d": sum(
                1 for r in primary if r["pipeline_a"]["executed"] != r["pipeline_b"]["executed"]
            ),
            "total_signals_365d": len(primary),
        },
        "window_validation": {"phase": "23F", "windows": window_results},
        "walkforward_validation": {"phase": "23F", "pipeline_a": wf_a, "pipeline_b": wf_b},
        "monte_carlo_validation": {"phase": "23F", "pipeline_a": mc_a, "pipeline_b": mc_b},
        "bootstrap_validation": {"phase": "23F", **bootstrap},
        "regime_validation": {"phase": "23F", "all_regimes_365d": regime_all, "range_by_window": regime_range_windows},
        "runtime_safety": build_runtime_safety(),
        "deployment_recommendation": deployment,
        "verdict": verdict,
        "_window_records": window_records,
    }

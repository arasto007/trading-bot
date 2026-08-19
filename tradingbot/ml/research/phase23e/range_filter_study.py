"""Phase 23E — scientific grid search for optimal Phase 9.9 RANGE filter profile."""

from __future__ import annotations

import hashlib
import json
import statistics
from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np

from tradingbot.ml.phase19a.metrics import (
    expectancy_r,
    max_drawdown_r,
    pf_from_r,
    sharpe_r,
)
from tradingbot.ml.phase19c.config import DEFAULT_SEED, MONTE_CARLO_SIMS, WALK_FORWARD_FOLDS
from tradingbot.ml.phase19c.filters import ProfitabilityFilterSettings, apply_profitability_filters
from tradingbot.ml.research.phase23d.filter_validation_research import (
    _collect_range_pipeline_signals,
    _phase22c_filter_settings,
)

VERDICT_OPTIONS = (
    "KEEP_CURRENT_FILTERS",
    "MODIFY_RSI_ONLY",
    "MODIFY_ADX_ONLY",
    "CREATE_RANGE_SPECIFIC_FILTER_PROFILE",
    "REMOVE_RSI",
    "REMOVE_ADX",
    "REMOVE_BOTH",
)

MIN_RANGE_TRADES = 10
BOOTSTRAP_SAMPLES = 1000
MC_SIMS = MONTE_CARLO_SIMS


@dataclass(frozen=True)
class FilterProfile:
    profile_id: str
    enable_rsi: bool
    enable_adx: bool
    rsi_min: float
    rsi_max: float
    adx_min: float
    adx_max: float
    mode: str

    def to_settings(self) -> ProfitabilityFilterSettings:
        return ProfitabilityFilterSettings(
            enable_rsi=self.enable_rsi,
            enable_adx=self.enable_adx,
            rsi_min=self.rsi_min,
            rsi_max=self.rsi_max,
            adx_min=self.adx_min,
            adx_max=self.adx_max,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "mode": self.mode,
            "enable_rsi_filter": self.enable_rsi,
            "enable_adx_filter": self.enable_adx,
            "rsi_min": self.rsi_min,
            "rsi_max": self.rsi_max,
            "adx_min": self.adx_min,
            "adx_max": self.adx_max,
        }


def production_profile() -> FilterProfile:
    s = _phase22c_filter_settings()
    return FilterProfile(
        profile_id="production_phase22c",
        enable_rsi=s.enable_rsi,
        enable_adx=s.enable_adx,
        rsi_min=s.rsi_min,
        rsi_max=s.rsi_max,
        adx_min=s.adx_min,
        adx_max=s.adx_max,
        mode="both",
    )


def build_search_space() -> dict[str, Any]:
    rsi_lowers = [0.0, 20.0, 25.0, 30.0, 35.0, 40.0]
    rsi_uppers = [55.0, 60.0, 65.0, 70.0, 80.0, 100.0]
    adx_lowers = [0.0, 5.0, 10.0, 15.0, 20.0, 25.0]
    adx_uppers = [40.0, 45.0, 50.0, 55.0, 60.0, 100.0]
    profiles: list[FilterProfile] = []

    def _pid(mode: str, rsi_min: float, rsi_max: float, adx_min: float, adx_max: float, er: bool, ea: bool) -> str:
        raw = f"{mode}:{er}:{ea}:{rsi_min}:{rsi_max}:{adx_min}:{adx_max}"
        return hashlib.sha256(raw.encode()).hexdigest()[:12]

    profiles.append(
        FilterProfile(
            profile_id="neither",
            enable_rsi=False,
            enable_adx=False,
            rsi_min=0.0,
            rsi_max=100.0,
            adx_min=0.0,
            adx_max=100.0,
            mode="neither",
        )
    )

    for lo in rsi_lowers:
        for hi in rsi_uppers:
            if lo >= hi:
                continue
            profiles.append(
                FilterProfile(
                    profile_id=_pid("rsi_only", lo, hi, 0, 100, True, False),
                    enable_rsi=True,
                    enable_adx=False,
                    rsi_min=lo,
                    rsi_max=hi,
                    adx_min=0.0,
                    adx_max=100.0,
                    mode="rsi_only",
                )
            )

    for lo in adx_lowers:
        for hi in adx_uppers:
            if lo >= hi:
                continue
            profiles.append(
                FilterProfile(
                    profile_id=_pid("adx_only", 0, 100, lo, hi, False, True),
                    enable_rsi=False,
                    enable_adx=True,
                    rsi_min=0.0,
                    rsi_max=100.0,
                    adx_min=lo,
                    adx_max=hi,
                    mode="adx_only",
                )
            )

    for rlo in rsi_lowers:
        for rhi in rsi_uppers:
            if rlo >= rhi:
                continue
            for alo in adx_lowers:
                for ahi in adx_uppers:
                    if alo >= ahi:
                        continue
                    profiles.append(
                        FilterProfile(
                            profile_id=_pid("both", rlo, rhi, alo, ahi, True, True),
                            enable_rsi=True,
                            enable_adx=True,
                            rsi_min=rlo,
                            rsi_max=rhi,
                            adx_min=alo,
                            adx_max=ahi,
                            mode="both",
                        )
                    )

    prod = production_profile()
    if prod.profile_id not in {p.profile_id for p in profiles}:
        profiles.append(prod)

    return {
        "phase": "23E",
        "rsi_lowers": rsi_lowers,
        "rsi_uppers": rsi_uppers,
        "adx_lowers": adx_lowers,
        "adx_uppers": adx_uppers,
        "modes": ["neither", "rsi_only", "adx_only", "both"],
        "total_profiles": len(profiles),
        "production_baseline": prod.to_dict(),
    }


def _passes_filter(record: dict[str, Any], profile: FilterProfile) -> bool:
    features = {"rsi": record.get("rsi", 50.0), "adx": record.get("adx", 0.0)}
    return apply_profitability_filters(features, settings=profile.to_settings()).passed


def _evaluate_profile(records: list[dict[str, Any]], profile: FilterProfile) -> dict[str, Any]:
    passed = [r for r in records if _passes_filter(r, profile)]
    blocked = [r for r in records if not _passes_filter(r, profile)]
    r_vals = [float(r["r_multiple"]) for r in passed]
    buy = sum(1 for r in passed if r.get("calibrated_action") == "BUY")
    sell = sum(1 for r in passed if r.get("calibrated_action") == "SELL")
    true_blocks = sum(1 for r in blocked if r.get("outcome_class") == "loser")
    false_blocks = sum(1 for r in blocked if r.get("outcome_class") == "winner")
    conf = [float(r.get("confidence", 0.0)) for r in passed]
    probs = [float(r.get("raw_probability", 0.5)) for r in passed]
    return {
        **profile.to_dict(),
        "trade_count": len(passed),
        "profit_factor": pf_from_r(r_vals) if r_vals else 0.0,
        "expectancy_r": expectancy_r(r_vals) if r_vals else 0.0,
        "win_rate": round(sum(1 for r in r_vals if r > 0) / len(r_vals), 4) if r_vals else 0.0,
        "sharpe_proxy": sharpe_r(r_vals) if r_vals else 0.0,
        "maximum_drawdown_r": max_drawdown_r(r_vals) if r_vals else 0.0,
        "mean_confidence": round(statistics.mean(conf), 4) if conf else 0.0,
        "mean_probability": round(statistics.mean(probs), 4) if probs else 0.0,
        "false_blocks": false_blocks,
        "true_blocks": true_blocks,
        "blocked_count": len(blocked),
        "buy_count": buy,
        "sell_count": sell,
    }


def run_grid_search(records: list[dict[str, Any]], *, search_meta: dict[str, Any]) -> dict[str, Any]:
    profiles = []
    for mode in ("neither", "rsi_only", "adx_only", "both"):
        pass
    # regenerate profiles list
    space = build_search_space()
    all_profiles: list[FilterProfile] = []
    rsi_lowers = space["rsi_lowers"]
    rsi_uppers = space["rsi_uppers"]
    adx_lowers = space["adx_lowers"]
    adx_uppers = space["adx_uppers"]

    def _pid(mode: str, rsi_min: float, rsi_max: float, adx_min: float, adx_max: float, er: bool, ea: bool) -> str:
        raw = f"{mode}:{er}:{ea}:{rsi_min}:{rsi_max}:{adx_min}:{adx_max}"
        return hashlib.sha256(raw.encode()).hexdigest()[:12]

    all_profiles.append(
        FilterProfile("neither", False, False, 0.0, 100.0, 0.0, 100.0, "neither")
    )
    for lo in rsi_lowers:
        for hi in rsi_uppers:
            if lo < hi:
                all_profiles.append(FilterProfile(_pid("rsi_only", lo, hi, 0, 100, True, False), True, False, lo, hi, 0, 100, "rsi_only"))
    for lo in adx_lowers:
        for hi in adx_uppers:
            if lo < hi:
                all_profiles.append(FilterProfile(_pid("adx_only", 0, 100, lo, hi, False, True), False, True, 0, 100, lo, hi, "adx_only"))
    for rlo in rsi_lowers:
        for rhi in rsi_uppers:
            if rlo >= rhi:
                continue
            for alo in adx_lowers:
                for ahi in adx_uppers:
                    if alo < ahi:
                        all_profiles.append(
                            FilterProfile(_pid("both", rlo, rhi, alo, ahi, True, True), True, True, rlo, rhi, alo, ahi, "both")
                        )
    prod = production_profile()
    if prod.profile_id not in {p.profile_id for p in all_profiles}:
        all_profiles.append(prod)

    results = [_evaluate_profile(records, p) for p in all_profiles]
    viable = [r for r in results if r["trade_count"] >= MIN_RANGE_TRADES]
    ranked = sorted(
        viable,
        key=lambda x: (x["profit_factor"], x["expectancy_r"], x["trade_count"]),
        reverse=True,
    )
    prod_metrics = _evaluate_profile(records, prod)
    return {
        "phase": "23E",
        "cohort": "RANGE pipeline_actionable",
        "records_total": len(records),
        "profiles_evaluated": len(results),
        "profiles_viable_min_trades": len(viable),
        "min_trades_threshold": MIN_RANGE_TRADES,
        "production_baseline_metrics": prod_metrics,
        "top_20": ranked[:20],
        "all_results_count": len(results),
    }


def _chronological_folds(records: list[dict[str, Any]], n_folds: int = WALK_FORWARD_FOLDS) -> list[list[dict[str, Any]]]:
    ordered = sorted(records, key=lambda r: r["timestamp"])
    n = len(ordered)
    if n < n_folds * 5:
        mid = max(1, n // 2)
        return [ordered[mid:]]
    fold_size = max(1, n // (n_folds + 1))
    folds: list[list[dict[str, Any]]] = []
    for i in range(n_folds):
        start = fold_size * (i + 1)
        end = min(n, start + fold_size)
        test = ordered[start:end]
        if test:
            folds.append(test)
    return folds


def run_walkforward_validation(
    records: list[dict[str, Any]],
    profiles: Iterable[FilterProfile],
) -> dict[str, Any]:
    folds = _chronological_folds(records)
    profile_results: list[dict[str, Any]] = []

    for profile in profiles:
        fold_rows: list[dict[str, Any]] = []
        stable = 0
        for idx, test in enumerate(folds):
            baseline_r = [float(r["r_multiple"]) for r in test]
            kept = [r for r in test if _passes_filter(r, profile)]
            kept_r = [float(r["r_multiple"]) for r in kept]
            base_pf = pf_from_r(baseline_r)
            filt_pf = pf_from_r(kept_r) if kept_r else 0.0
            base_exp = expectancy_r(baseline_r)
            filt_exp = expectancy_r(kept_r) if kept_r else 0.0
            improved = filt_pf >= base_pf and filt_exp >= base_exp and len(kept_r) >= 3
            if improved:
                stable += 1
            fold_rows.append(
                {
                    "fold": idx,
                    "test_trades": len(test),
                    "filtered_trades": len(kept),
                    "baseline_pf": base_pf,
                    "filtered_pf": filt_pf,
                    "baseline_exp": base_exp,
                    "filtered_exp": filt_exp,
                    "improved": improved,
                }
            )
        profile_results.append(
            {
                **profile.to_dict(),
                "n_folds": len(folds),
                "stable_folds": stable,
                "stable": stable >= max(1, len(folds) // 2),
                "folds": fold_rows,
            }
        )

    return {"phase": "23E", "method": "Phase19C chronological folds — fixed thresholds", "profiles": profile_results}


def run_monte_carlo_validation(
    records: list[dict[str, Any]],
    profiles: Iterable[FilterProfile],
    *,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    out: list[dict[str, Any]] = []

    for profile in profiles:
        kept = [r for r in records if _passes_filter(r, profile)]
        r_vals = [float(r["r_multiple"]) for r in kept]
        if len(r_vals) < MIN_RANGE_TRADES:
            out.append({**profile.to_dict(), "passed": False, "reason": "too_few_trades", "trades": len(r_vals)})
            continue
        fails = 0
        pfs: list[float] = []
        exps: list[float] = []
        dds: list[float] = []
        for _ in range(MC_SIMS):
            sample = rng.permutation(r_vals).tolist()
            slip = rng.uniform(0, 0.1, size=len(sample))
            adjusted = [r - s for r, s in zip(sample, slip)]
            pf = pf_from_r(adjusted)
            exp = expectancy_r(adjusted)
            dd = max_drawdown_r(adjusted)
            pfs.append(pf)
            exps.append(exp)
            dds.append(dd)
            if pf < 1.0 or exp < 0:
                fails += 1
        fail_rate = fails / MC_SIMS
        out.append(
            {
                **profile.to_dict(),
                "passed": fail_rate < 0.35 and float(np.mean(pfs)) >= 1.05,
                "trades": len(r_vals),
                "baseline_pf": pf_from_r(r_vals),
                "baseline_exp": expectancy_r(r_vals),
                "baseline_dd": max_drawdown_r(r_vals),
                "mean_pf_stress": round(float(np.mean(pfs)), 4),
                "mean_exp_stress": round(float(np.mean(exps)), 4),
                "worst_dd_stress": round(float(np.min(dds)), 4),
                "failure_rate": round(fail_rate, 4),
                "trade_stability": round(len(r_vals) / max(len(records), 1), 4),
            }
        )

    return {"phase": "23E", "n_sims": MC_SIMS, "profiles": out}


def run_statistical_validation(
    records: list[dict[str, Any]],
    candidate: FilterProfile,
    baseline: FilterProfile,
    *,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    cand_r = [float(r["r_multiple"]) for r in records if _passes_filter(r, candidate)]
    base_r = [float(r["r_multiple"]) for r in records if _passes_filter(r, baseline)]
    pf_c = pf_from_r(cand_r)
    pf_b = pf_from_r(base_r)
    exp_c = expectancy_r(cand_r)
    exp_b = expectancy_r(base_r)

    # paired bootstrap on per-record accepted R (0 if filtered out)
    diffs: list[float] = []
    for _ in range(BOOTSTRAP_SAMPLES):
        idx = rng.integers(0, len(records), size=len(records))
        sample = [records[i] for i in idx]
        cr = [float(r["r_multiple"]) for r in sample if _passes_filter(r, candidate)]
        br = [float(r["r_multiple"]) for r in sample if _passes_filter(r, baseline)]
        diffs.append(pf_from_r(cr) - pf_from_r(br))

    diffs_arr = np.asarray(diffs, dtype=float)
    ci_low, ci_high = float(np.percentile(diffs_arr, 2.5)), float(np.percentile(diffs_arr, 97.5))
    significant = ci_low > 0.0

    pooled = cand_r + base_r
    if len(pooled) >= 2 and len(cand_r) >= 2 and len(base_r) >= 2:
        mean_c = float(np.mean(cand_r))
        mean_b = float(np.mean(base_r))
        sp = float(np.sqrt(((len(cand_r) - 1) * np.var(cand_r) + (len(base_r) - 1) * np.var(base_r)) / max(len(cand_r) + len(base_r) - 2, 1)))
        effect_size = round((mean_c - mean_b) / sp, 4) if sp > 1e-12 else 0.0
    else:
        effect_size = 0.0

    return {
        "phase": "23E",
        "paired_bootstrap_samples": BOOTSTRAP_SAMPLES,
        "production_pf": pf_b,
        "candidate_pf": pf_c,
        "production_expectancy": exp_b,
        "candidate_expectancy": exp_c,
        "pf_delta": round(pf_c - pf_b, 4),
        "expectancy_delta": round(exp_c - exp_b, 4),
        "bootstrap_pf_diff_ci_95": [round(ci_low, 4), round(ci_high, 4)],
        "statistically_significant_improvement": significant,
        "cohens_d_effect_size": effect_size,
        "candidate_profile": candidate.to_dict(),
        "baseline_profile": baseline.to_dict(),
    }


def _collect_all_regime_pipeline_signals(*, base_dir: str | None = None, days: int = 365, stride: int = 5) -> list[dict[str, Any]]:
    """Collect pipeline-actionable records for all regimes (research replay)."""
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

    window = prepare_calibration_candles(candles_raw, days=days)
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
            ts = pd.to_datetime(row.get("timestamp", row.name), utc=True)
            bar_idx = ts_to_idx.get(pd.Timestamp(ts), min(bar_index, len(c) - 1))
            outcome = simulate_outcome(c, bar_idx, action)
            r_mult = float(outcome["r_multiple"])
            records.append(
                {
                    "timestamp": ts.isoformat(),
                    "regime": regime,
                    "calibrated_action": action,
                    "confidence": float(cal.final_confidence),
                    "rsi": float(row.get("rsi", 50.0)),
                    "adx": float(row.get("adx", 0.0)),
                    "raw_probability": float(ctx.range_signal.probability if regime == "RANGE" else ctx.trend_signal.probability),
                    "r_multiple": r_mult,
                    "outcome_class": "winner" if r_mult > 0 else ("loser" if r_mult < 0 else "breakeven"),
                }
            )
    finally:
        PipelineCache.reset()
        if prev is None:
            os.environ.pop(TREND_VERSION_ENV, None)
        else:
            os.environ[TREND_VERSION_ENV] = prev
    return records


def run_regime_validation(
    all_records: list[dict[str, Any]],
    candidate: FilterProfile,
    baseline: FilterProfile,
) -> dict[str, Any]:
    buckets = {"RANGE": [], "TREND": [], "TRANSITION": []}
    for r in all_records:
        reg = str(r.get("regime", "")).upper()
        if reg in ("HIGH_VOLATILITY", "NO_TRADE"):
            buckets["TRANSITION"].append(r)
        elif reg in buckets:
            buckets[reg].append(r)
        else:
            buckets["TRANSITION"].append(r)

    def _regime_metrics(recs: list[dict[str, Any]], profile: FilterProfile) -> dict[str, Any]:
        ev = _evaluate_profile(recs, profile)
        return {
            "trade_count": ev["trade_count"],
            "profit_factor": ev["profit_factor"],
            "expectancy_r": ev["expectancy_r"],
            "maximum_drawdown_r": ev["maximum_drawdown_r"],
        }

    out: dict[str, Any] = {"phase": "23E", "regimes": {}}
    for name, recs in buckets.items():
        if not recs:
            out["regimes"][name] = {"count": 0}
            continue
        base_m = _regime_metrics(recs, baseline)
        cand_m = _regime_metrics(recs, candidate)
        out["regimes"][name] = {
            "pipeline_actionable_signals": len(recs),
            "production_filter": base_m,
            "candidate_filter": cand_m,
            "pf_delta_candidate_minus_production": round(cand_m["profit_factor"] - base_m["profit_factor"], 4),
            "degradation_outside_range": name != "RANGE" and cand_m["profit_factor"] < base_m["profit_factor"] * 0.9,
        }
    return out


def run_safety_analysis(records: list[dict[str, Any]], profiles: list[FilterProfile]) -> dict[str, Any]:
    rows = []
    for profile in profiles:
        ev = _evaluate_profile(records, profile)
        blocked = [r for r in records if not _passes_filter(r, profile)]
        passed = [r for r in records if _passes_filter(r, profile)]
        rows.append(
            {
                **profile.to_dict(),
                "false_positives_blocked_winners": ev["false_blocks"],
                "false_negatives_passed_losers": sum(1 for r in passed if r.get("outcome_class") == "loser"),
                "true_blocks_blocked_losers": ev["true_blocks"],
                "precision": round(ev["true_blocks"] / max(ev["true_blocks"] + ev["false_blocks"], 1), 4),
                "recall": round(ev["true_blocks"] / max(sum(1 for r in records if r.get("outcome_class") == "loser"), 1), 4),
                "risk_increase_proxy": round(max(0.0, -ev["maximum_drawdown_r"]), 4),
                "blocked_count": len(blocked),
            }
        )
    return {"phase": "23E", "profiles": rows}


def _profile_from_dict(d: dict[str, Any]) -> FilterProfile:
    return FilterProfile(
        profile_id=str(d.get("profile_id", "unknown")),
        enable_rsi=bool(d.get("enable_rsi_filter", d.get("enable_rsi", True))),
        enable_adx=bool(d.get("enable_adx_filter", d.get("enable_adx", True))),
        rsi_min=float(d.get("rsi_min", 40)),
        rsi_max=float(d.get("rsi_max", 60)),
        adx_min=float(d.get("adx_min", 15)),
        adx_max=float(d.get("adx_max", 50)),
        mode=str(d.get("mode", "both")),
    )


def select_winner(
    *,
    grid: dict[str, Any],
    walkforward: dict[str, Any],
    montecarlo: dict[str, Any],
    stats: dict[str, Any],
    regime: dict[str, Any],
    range_records: list[dict[str, Any]],
) -> dict[str, Any]:
    prod = production_profile()
    prod_m = grid["production_baseline_metrics"]
    wf_by_id = {p["profile_id"]: p for p in walkforward["profiles"]}
    mc_by_id = {p["profile_id"]: p for p in montecarlo["profiles"]}

    candidates: list[dict[str, Any]] = []
    for row in grid.get("top_20", []):
        pid = row["profile_id"]
        wf = wf_by_id.get(pid, {})
        mc = mc_by_id.get(pid, {})
        profile = _profile_from_dict(row)
        passes = (
            row["profit_factor"] > prod_m["profit_factor"]
            and row["expectancy_r"] > prod_m["expectancy_r"]
            and wf.get("stable", False)
            and mc.get("passed", False)
            and row["maximum_drawdown_r"] >= prod_m["maximum_drawdown_r"] - 2.0
            and row["mean_probability"] >= prod_m["mean_probability"] * 0.85
        )
        candidates.append({**row, "passes_all_criteria": passes, "walkforward_stable": wf.get("stable"), "montecarlo_passed": mc.get("passed")})

    winners = [c for c in candidates if c["passes_all_criteria"]]
    if winners:
        winner_row = winners[0]
    else:
        winner_row = grid["top_20"][0] if grid.get("top_20") else prod_m

    winner_profile = _profile_from_dict(winner_row)
    return {
        "phase": "23E",
        "winner_profile": winner_profile.to_dict(),
        "winner_metrics": winner_row,
        "strict_criteria_pass": bool(winners),
        "candidates_passing_all": len(winners),
        "production_baseline": prod_m,
    }


def map_production_recommendation(winner: FilterProfile, baseline: FilterProfile) -> tuple[str, dict[str, Any]]:
    if (
        winner.enable_rsi == baseline.enable_rsi
        and winner.enable_adx == baseline.enable_adx
        and abs(winner.rsi_min - baseline.rsi_min) < 1e-6
        and abs(winner.rsi_max - baseline.rsi_max) < 1e-6
        and abs(winner.adx_min - baseline.adx_min) < 1e-6
        and abs(winner.adx_max - baseline.adx_max) < 1e-6
    ):
        verdict = "KEEP_CURRENT_FILTERS"
    elif not winner.enable_rsi and not winner.enable_adx:
        verdict = "REMOVE_BOTH"
    elif not winner.enable_rsi and winner.enable_adx:
        verdict = "REMOVE_RSI"
    elif winner.enable_rsi and not winner.enable_adx:
        verdict = "REMOVE_ADX"
    elif winner.enable_rsi and winner.enable_adx and (
        abs(winner.adx_min - baseline.adx_min) < 1e-6 and abs(winner.adx_max - baseline.adx_max) < 1e-6
    ):
        verdict = "MODIFY_RSI_ONLY"
    elif winner.enable_rsi and winner.enable_adx and (
        abs(winner.rsi_min - baseline.rsi_min) < 1e-6 and abs(winner.rsi_max - baseline.rsi_max) < 1e-6
    ):
        verdict = "MODIFY_ADX_ONLY"
    else:
        verdict = "CREATE_RANGE_SPECIFIC_FILTER_PROFILE"

    return verdict, {
        "phase": "23E",
        "verdict": verdict,
        "recommended_profile": winner.to_dict(),
        "production_baseline": baseline.to_dict(),
        "implementation_status": "NOT IMPLEMENTED — research recommendation only",
        "rationale": f"Optimal RANGE grid-search winner mapped to {verdict}",
    }


def build_repair_plan(*, recommendation: dict[str, Any]) -> dict[str, Any]:
    verdict = recommendation.get("verdict", "CREATE_RANGE_SPECIFIC_FILTER_PROFILE")
    return {
        "phase": "23E",
        "target_verdict": verdict,
        "migration": "Approved integration phase: regime-conditional filter profile in KernelAdapter for RANGE only",
        "rollback": "Restore Phase22C env defaults; ENABLE_RSI/ADX flags unchanged for TREND path",
        "tests": [
            "test_phase23e winner reproduces grid metrics",
            "test_phase23b feature pipeline unchanged",
            "test_phase23d false-block rate improved on RANGE tail",
            "hold_chain kernel_actionable >= production baseline",
        ],
        "runtime_safety": [
            "No live filter change in Phase 23E",
            "Shadow replay 7d before production toggle",
            "HealthGate + RiskGate regression suite",
        ],
        "implementation_status": "DESIGN ONLY",
    }


def run_study(*, base_dir: str | None = None) -> dict[str, Any]:
    search_space = build_search_space()
    range_records = _collect_range_pipeline_signals(base_dir=base_dir, days=365, stride=5)
    all_records = _collect_all_regime_pipeline_signals(base_dir=base_dir, days=365, stride=5)

    grid = run_grid_search(range_records, search_meta=search_space)
    prod = production_profile()

    top_profiles = [_profile_from_dict(r) for r in grid.get("top_20", [])]
    if prod not in top_profiles:
        top_profiles.append(prod)

    walkforward = run_walkforward_validation(range_records, top_profiles)
    montecarlo = run_monte_carlo_validation(range_records, top_profiles)

    best_row = grid["top_20"][0] if grid.get("top_20") else grid["production_baseline_metrics"]
    candidate = _profile_from_dict(best_row)
    stats = run_statistical_validation(range_records, candidate, prod)
    regime = run_regime_validation(all_records, candidate, prod)
    safety = run_safety_analysis(range_records, top_profiles)
    winner = select_winner(
        grid=grid,
        walkforward=walkforward,
        montecarlo=montecarlo,
        stats=stats,
        regime=regime,
        range_records=range_records,
    )
    winner_profile = _profile_from_dict(winner["winner_profile"])
    verdict, recommendation = map_production_recommendation(winner_profile, prod)
    repair_plan = build_repair_plan(recommendation=recommendation)

    return {
        "search_space": search_space,
        "grid_search_results": grid,
        "walkforward_results": walkforward,
        "monte_carlo_results": montecarlo,
        "statistical_validation": stats,
        "regime_validation": regime,
        "safety_analysis": safety,
        "winner_profile": winner,
        "production_recommendation": recommendation,
        "repair_plan": repair_plan,
        "verdict": verdict,
    }

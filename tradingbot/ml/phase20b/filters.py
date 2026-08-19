"""Phase 20B — live filter effectiveness (RSI / ADX)."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.phase19a.metrics import compute_performance
from tradingbot.ml.phase19c.filters import ProfitabilityFilterSettings, apply_profitability_filters


def _classify(delta_pf: float, retention: float) -> str:
    if retention < 0.15:
        return "over_restrictive"
    if delta_pf > 0.05:
        return "effective"
    if delta_pf < -0.05:
        return "under_performing"
    return "neutral"


def _feature_map(all_recs: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for r in all_recs:
        ts = str(r.get("timestamp", ""))
        if not ts:
            continue
        out[ts] = {
            "rsi": float(r.get("rsi", 50)),
            "adx": float(r.get("adx", 0)),
        }
    return out


def analyze_filter_effectiveness(observation: dict[str, Any]) -> dict[str, Any]:
    """
    Compare unfiltered live-path baseline trades vs RSI/ADX filtered subsets.
    Uses baseline R-multiples (pre-filter outcomes) joined with live-path features.
    """
    baseline = observation.get("baseline_trades") or []
    all_recs = observation.get("all_path_records") or []
    feats = _feature_map(all_recs)

    # Enrich baseline with features when available
    pipeline: list[dict[str, Any]] = []
    for t in baseline:
        row = dict(t)
        row["allowed"] = True
        if "r_multiple" not in row:
            continue
        f = feats.get(str(row.get("timestamp", "")), {})
        row["rsi"] = f.get("rsi", row.get("rsi", 50))
        row["adx"] = f.get("adx", row.get("adx", 25))
        pipeline.append(row)

    # Fallback: use path records that were pipeline-allowed and reconstruct
    # from allowed trades only if baseline empty
    if not pipeline:
        for r in all_recs:
            if not r.get("pipeline_allowed"):
                continue
            if "r_multiple" not in r:
                continue
            # Only use rows that were actually traded (have non-hold outcome)
            # or have features for filter study
            row = dict(r)
            row["allowed"] = True
            pipeline.append(row)

    baseline_perf = compute_performance(pipeline) if pipeline else compute_performance([])

    rsi_only = ProfitabilityFilterSettings(enable_rsi=True, enable_adx=False)
    adx_only = ProfitabilityFilterSettings(enable_rsi=False, enable_adx=True)
    both = ProfitabilityFilterSettings(enable_rsi=True, enable_adx=True)

    def apply(settings: ProfitabilityFilterSettings) -> list[dict]:
        kept = []
        for t in pipeline:
            features = {"rsi": t.get("rsi", 50), "adx": t.get("adx", 0)}
            if apply_profitability_filters(features, settings=settings).passed:
                kept.append(t)
        return kept

    rsi_trades = apply(rsi_only)
    adx_trades = apply(adx_only)
    both_trades = apply(both)

    rsi_perf = compute_performance(rsi_trades)
    adx_perf = compute_performance(adx_trades)
    both_perf = compute_performance(both_trades)

    base_pf = float(baseline_perf.get("profit_factor", 0))
    base_dd = abs(float(baseline_perf.get("maximum_drawdown_r", 0)))
    base_n = max(int(baseline_perf.get("trades", 0)), 1)

    def contrib(name: str, perf: dict, kept: list, settings: ProfitabilityFilterSettings) -> dict[str, Any]:
        pf = float(perf.get("profit_factor", 0))
        dd = abs(float(perf.get("maximum_drawdown_r", 0)))
        retention = len(kept) / base_n

        def _kept(t: dict) -> bool:
            return apply_profitability_filters(
                {"rsi": t.get("rsi", 50), "adx": t.get("adx", 0)},
                settings=settings,
            ).passed

        losers_removed = sum(
            1 for t in pipeline
            if float(t.get("r_multiple", 0)) < 0 and not _kept(t)
        )
        winners_removed = sum(
            1 for t in pipeline
            if float(t.get("r_multiple", 0)) > 0 and not _kept(t)
        )
        delta_pf = round(pf - base_pf, 4)
        delta_dd = round(base_dd - dd, 4)
        losers_total = max(sum(1 for t in pipeline if float(t.get("r_multiple", 0)) < 0), 1)
        return {
            "name": name,
            "trades": perf.get("trades"),
            "profit_factor": pf,
            "expectancy_r": perf.get("expectancy_r"),
            "maximum_drawdown_r": perf.get("maximum_drawdown_r"),
            "retention": round(retention, 4),
            "pf_improvement": delta_pf,
            "drawdown_reduction_r": delta_dd,
            "losers_removed": losers_removed,
            "winners_removed": winners_removed,
            "false_positive_removal_rate": round(losers_removed / losers_total, 4),
            "classification": _classify(delta_pf, retention),
        }

    rsi_c = contrib("rsi_mid", rsi_perf, rsi_trades, rsi_only)
    adx_c = contrib("adx_15_50", adx_perf, adx_trades, adx_only)
    both_c = contrib("rsi_mid+adx_15_50", both_perf, both_trades, both)

    return {
        "phase": "20B",
        "baseline": {
            "trades": baseline_perf.get("trades"),
            "profit_factor": baseline_perf.get("profit_factor"),
            "maximum_drawdown_r": baseline_perf.get("maximum_drawdown_r"),
        },
        "rsi_filter": rsi_c,
        "adx_filter": adx_c,
        "combined": both_c,
        "summary": {
            "rsi": rsi_c["classification"],
            "adx": adx_c["classification"],
            "combined": both_c["classification"],
        },
    }

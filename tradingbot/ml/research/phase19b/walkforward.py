"""Phase 19B — chronological walk-forward validation of candidates."""

from __future__ import annotations

from typing import Any, Callable

from tradingbot.ml.phase19a.metrics import compute_performance
from tradingbot.ml.research.phase19b.config import WALK_FORWARD_FOLDS


def _chronological_folds(trades: list[dict], n_folds: int = WALK_FORWARD_FOLDS) -> list[tuple[list, list]]:
    ordered = sorted(trades, key=lambda t: t["timestamp"])
    n = len(ordered)
    if n < n_folds * 5:
        return [(ordered[: max(1, n // 2)], ordered[max(1, n // 2):])]
    fold_size = n // (n_folds + 1)
    folds = []
    for i in range(n_folds):
        train_end = fold_size * (i + 1)
        test_end = min(n, train_end + fold_size)
        train = ordered[:train_end]
        test = ordered[train_end:test_end]
        if train and test:
            folds.append((train, test))
    return folds


def _rebuild_filter(name: str) -> Callable[[dict], bool] | None:
    """Rebuild simple named filters without train-set leakage for fixed thresholds."""
    # Fixed-threshold filters only (no percentile fit on full sample)
    if name.startswith("adx_"):
        parts = name.split("_")
        if len(parts) == 3:
            lo, hi = float(parts[1]), float(parts[2])
            return lambda t, a=lo, b=hi: a <= float(t.get("adx", 0)) <= b
    if name == "rsi_not_extreme":
        return lambda t: 30 <= float(t.get("rsi", 50)) <= 70
    if name == "rsi_mid":
        return lambda t: 40 <= float(t.get("rsi", 50)) <= 60
    if name == "trend_age_ge_3":
        return lambda t: float(t.get("trend_age", 0)) >= 3
    if name == "trend_age_ge_5":
        return lambda t: float(t.get("trend_age", 0)) >= 5
    if name == "trend_age_le_50":
        return lambda t: float(t.get("trend_age", 0)) <= 50
    if name.startswith("session_"):
        sess = name.replace("session_", "").upper()
        if sess == "LONDON_NY":
            return lambda t: t.get("session") in ("LONDON", "NY")
        return lambda t, s=sess: t.get("session") == s
    if name == "hour_8_20":
        return lambda t: 8 <= int(t.get("hour", 0)) <= 20
    if name == "hour_avoid_0_4":
        return lambda t: int(t.get("hour", 0)) not in (0, 1, 2, 3, 4)
    if name.startswith("confidence_ge_"):
        thr = float(name.split("_")[-1])
        return lambda t, x=thr: float(t.get("confidence", 0)) >= x
    if name.startswith("quality_ge_"):
        thr = float(name.split("_")[-1])
        return lambda t, x=thr: float(t.get("quality_score", 0)) >= x
    if name == "regime_range_only":
        return lambda t: t.get("regime") == "RANGE"
    if name == "regime_trend_only":
        return lambda t: t.get("regime") == "TREND"
    if name == "duration_ge_1":
        return lambda t: int(t.get("duration_bars", 0)) >= 1
    if "+" in name:
        parts = name.split("+")
        fns = [_rebuild_filter(p) for p in parts]
        if all(fns):
            return lambda t, fs=fns: all(f(t) for f in fs)
    # Percentile-based filters: fit on train only inside validate_candidate
    return None


def _train_percentile_filter(name: str, train: list[dict]) -> Callable[[dict], bool] | None:
    import numpy as np
    if name == "atr_below_p75":
        x = float(np.percentile([float(t.get("atr", 0)) for t in train], 75))
        return lambda t, v=x: float(t.get("atr", 0)) <= v
    if name == "atr_above_p25":
        x = float(np.percentile([float(t.get("atr", 0)) for t in train], 25))
        return lambda t, v=x: float(t.get("atr", 0)) >= v
    if name == "atr_mid":
        a = float(np.percentile([float(t.get("atr", 0)) for t in train], 25))
        b = float(np.percentile([float(t.get("atr", 0)) for t in train], 75))
        return lambda t, lo=a, hi=b: lo <= float(t.get("atr", 0)) <= hi
    if name == "spread_below_p75":
        x = float(np.percentile([float(t.get("spread", 0)) for t in train], 75))
        return lambda t, v=x: float(t.get("spread", 0)) <= v
    if name == "risk_le_median":
        x = float(np.median([float(t.get("risk_percent", 0.005)) for t in train]))
        return lambda t, v=x: float(t.get("risk_percent", 0)) <= v
    return None


def validate_candidate(name: str, trades: list[dict[str, Any]]) -> dict[str, Any]:
    folds = _chronological_folds(trades)
    fold_results = []
    for train, test in folds:
        fn = _rebuild_filter(name)
        if fn is None:
            fn = _train_percentile_filter(name, train)
        if fn is None:
            return {"name": name, "stable": False, "reason": "filter_not_rebuildable"}
        base_test = compute_performance(test)
        kept = [t for t in test if fn(t)]
        filt = compute_performance(kept)
        fold_results.append({
            "train_trades": len(train),
            "test_trades": len(test),
            "kept": len(kept),
            "baseline_pf": base_test["profit_factor"],
            "filtered_pf": filt["profit_factor"],
            "baseline_exp": base_test["expectancy_r"],
            "filtered_exp": filt["expectancy_r"],
            "baseline_dd": base_test["maximum_drawdown_r"],
            "filtered_dd": filt["maximum_drawdown_r"],
            "pf_improved": filt["profit_factor"] >= base_test["profit_factor"],
            "exp_improved": filt["expectancy_r"] >= base_test["expectancy_r"] - 0.02,
        })

    if not fold_results:
        return {"name": name, "stable": False, "reason": "no_folds"}

    pf_ok = sum(1 for f in fold_results if f["pf_improved"]) / len(fold_results)
    exp_ok = sum(1 for f in fold_results if f["exp_improved"]) / len(fold_results)
    mean_pf_delta = float(sum(f["filtered_pf"] - f["baseline_pf"] for f in fold_results) / len(fold_results))
    stable = pf_ok >= 0.5 and mean_pf_delta > 0 and exp_ok >= 0.5

    return {
        "name": name,
        "stable": stable,
        "folds": fold_results,
        "pf_improve_rate": round(pf_ok, 4),
        "exp_improve_rate": round(exp_ok, 4),
        "mean_pf_delta": round(mean_pf_delta, 4),
    }


def run_walkforward(trades: list[dict], candidate_names: list[str]) -> dict[str, Any]:
    results = [validate_candidate(n, trades) for n in candidate_names]
    survivors = [r for r in results if r.get("stable")]
    return {
        "phase": "19B",
        "candidates_tested": len(results),
        "survivors": survivors,
        "rejected": [r for r in results if not r.get("stable")],
        "all": results,
    }

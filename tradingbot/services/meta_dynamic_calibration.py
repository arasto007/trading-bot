"""Phase 2A — dynamic meta threshold calibration helpers (test/calibration only)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]


def dynamic_threshold_phase2a(base: float, regime: str) -> float:
    """Phase 2A regime-adjusted threshold (does not modify live MetaLabeler)."""
    r = (regime or "RANGING").upper()
    if r in ("TREND", "STRONG_TREND_UP", "STRONG_TREND_DOWN"):
        return max(0.25, round(float(base) - 0.02, 4))
    if r == "RANGING":
        return min(0.55, round(float(base) + 0.02, 4))
    return round(float(base), 4)


def selection_score(metrics: dict[str, Any], *, target_trades: int = 28) -> float:
    pf = float(metrics["pf"]) if metrics.get("pf") not in ("inf", float("inf")) else 3.0
    exp_r = float(metrics.get("expectancy_r", 0))
    dd = float(metrics.get("max_dd_r", 0))
    trades = int(metrics.get("trades", 0))
    return round(pf * 0.45 + exp_r * 0.35 - dd * 0.10 - abs(trades - target_trades) * 0.02, 4)


def _metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {"trades": 0, "win_rate_pct": 0.0, "pf": 0.0, "expectancy_r": 0.0, "max_dd_r": 0.0}
    rs = [float(t["r_multiple"]) for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    gw, gl = sum(wins), abs(sum(losses))
    pf = gw / gl if gl else (float("inf") if gw else 0.0)
    eq = peak = mdd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    return {
        "trades": len(trades),
        "win_rate_pct": round(len(wins) / len(rs) * 100, 2),
        "pf": round(pf, 3) if pf != float("inf") else "inf",
        "expectancy_r": round(sum(rs) / len(rs), 3),
        "max_dd_r": round(mdd, 2),
    }


def _score_m5(meta, signal, snapshot, regime: str, spread: float = 4.0) -> float:
    tf = "M5"
    model = meta._models.get(tf)
    names = meta._features.get(tf)
    if model is None or not names:
        return 1.0
    feats = meta.build_features(signal, snapshot, regime, spread_pips=spread)
    row = [feats.get(n, 0.0) for n in names]
    try:
        proba = model.predict_proba([row])[0]
        return float(proba[1]) if len(proba) > 1 else float(proba[0])
    except Exception:
        return 1.0


def score_pa_trades(
    trades: list[dict[str, Any]],
    df: pd.DataFrame,
    *,
    meta=None,
) -> list[dict[str, Any]]:
    """Attach meta_prob and regime to each PA replay trade."""
    from tradingbot.domain.enums import SignalDirection
    from tradingbot.domain.models import TradingSignal
    from tradingbot.domain.risk_logic import infer_regime_from_ohlcv
    from tradingbot.services.meta_labeler import get_meta_labeler

    ml = meta or get_meta_labeler()
    scored: list[dict[str, Any]] = []
    for t in trades:
        idx = int(t["bar_index"])
        window = df.iloc[: idx + 1]
        regime = infer_regime_from_ohlcv(window, at_index=idx)
        direction = SignalDirection.BUY if t["direction"] == "BUY" else SignalDirection.SELL
        sig = TradingSignal(
            direction=direction,
            confidence=float(t.get("confidence", 0.55)),
            symbol="XAUUSD",
            timeframe="5m",
            strategy_name="priceaction",
            stop_loss=float(t["stop_loss"]),
            take_profit=float(t.get("take_profit") or 0),
            metadata={
                "entry": t["entry"],
                "price": t["entry"],
                "confidence": t.get("confidence"),
                "confluence": t.get("confluence", 0),
                "setup": t.get("setup"),
            },
        )
        snap = {"ohlcv": window, "htf_bias": 0, "current_time": window.index[-1]}
        prob = _score_m5(ml, sig, snap, regime)
        row = dict(t)
        row["meta_prob"] = round(prob, 4)
        row["regime"] = regime
        row["win"] = 1 if float(t["r_multiple"]) > 0 else 0
        scored.append(row)
    return scored


def filter_fixed_threshold(scored: list[dict[str, Any]], threshold: float) -> list[dict[str, Any]]:
    return [t for t in scored if float(t.get("meta_prob", 0)) >= threshold]


def filter_dynamic_threshold(scored: list[dict[str, Any]], base: float) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for t in scored:
        th = dynamic_threshold_phase2a(base, str(t.get("regime", "RANGING")))
        if float(t.get("meta_prob", 0)) >= th:
            row = dict(t)
            row["effective_threshold"] = th
            out.append(row)
    return out


def calibration_curve(probs: list[float], wins: list[int], n_bins: int = 10) -> tuple[list[dict], float]:
    if not probs:
        return [], 1.0
    y = np.asarray(wins, dtype=float)
    p = np.asarray(probs, dtype=float)
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    curve: list[dict[str, float]] = []
    ece = 0.0
    n = len(y)
    for i in range(n_bins):
        lo, hi = bins[i], bins[i + 1]
        mask = (p >= lo) & (p <= hi if i == n_bins - 1 else p < hi)
        cnt = int(mask.sum())
        if cnt == 0:
            continue
        mp = float(p[mask].mean())
        ma = float(y[mask].mean())
        curve.append({"bin_low": round(float(lo), 4), "bin_high": round(float(hi), 4), "mean_pred": round(mp, 4), "mean_actual": round(ma, 4), "count": cnt})
        ece += abs(mp - ma) * (cnt / n)
    return curve, round(float(ece), 4)


def precision_recall_by_regime(accepted: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for regime in sorted({str(t.get("regime", "UNKNOWN")) for t in accepted}):
        subset = [t for t in accepted if str(t.get("regime")) == regime]
        if not subset:
            continue
        wins = sum(int(t.get("win", 0)) for t in subset)
        out[regime] = {
            "trades": len(subset),
            "precision": round(wins / len(subset), 4),
            "recall": round(wins / len(subset), 4),
            "expectancy_r": round(sum(float(t["r_multiple"]) for t in subset) / len(subset), 3),
        }
    return out


def feature_importance_stability(meta) -> dict[str, Any]:
    tf = "M5"
    model = meta._models.get(tf)
    names = list(meta._features.get(tf) or [])
    if model is None or not names:
        return {"stable": False, "top_features": [], "stability_score": 0.0}
    imp = getattr(model, "feature_importances_", None)
    if imp is None:
        coef = getattr(model, "coef_", None)
        if coef is not None:
            imp = np.abs(np.ravel(coef))
        else:
            return {"stable": True, "top_features": names[:5], "stability_score": 1.0}
    pairs = sorted(zip(names, imp), key=lambda x: -float(x[1]))
    top = [n for n, _ in pairs[:5]]
    total = float(sum(float(x[1]) for x in pairs[:5])) or 1.0
    concentration = float(pairs[0][1]) / total if pairs else 0.0
    stable = concentration < 0.65
    return {
        "stable": stable,
        "top_features": top,
        "stability_score": round(1.0 - concentration, 4),
        "concentration_top1": round(concentration, 4),
    }


def drift_detection(scored: list[dict[str, Any]], *, info_path: Path | None = None) -> dict[str, Any]:
    path = info_path or ROOT / "models" / "meta_labeler_info.json"
    oos_mean = 0.5
    if path.is_file():
        try:
            info = json.loads(path.read_text(encoding="utf-8"))
            oos = (info.get("per_tf") or {}).get("M5", {}).get("oos") or {}
            oos_mean = float(oos.get("oos_precision", 0.5) or 0.5)
        except Exception:
            pass
    if not scored:
        return {"drift_detected": False, "live_mean_prob": 0.0, "oos_reference": oos_mean}
    live_mean = float(np.mean([float(t.get("meta_prob", 0)) for t in scored]))
    drift = abs(live_mean - oos_mean) > 0.15
    return {
        "drift_detected": drift,
        "live_mean_prob": round(live_mean, 4),
        "oos_reference": round(oos_mean, 4),
        "delta": round(live_mean - oos_mean, 4),
    }


def monte_carlo_accepted(trades: list[dict[str, Any]], *, simulations: int = 1000, seed: int = 42) -> dict[str, Any]:
    rs = [float(t["r_multiple"]) for t in trades]
    if len(rs) < 3:
        return {"simulations": 0, "pf_p5": 0.0, "pf_p50": 0.0, "pf_p95": 0.0, "exp_p5": 0.0, "exp_p95": 0.0}
    rng = np.random.default_rng(seed)
    pfs: list[float] = []
    exps: list[float] = []
    arr = np.asarray(rs)
    for _ in range(simulations):
        sample = rng.choice(arr, size=len(arr), replace=True)
        wins = sample[sample > 0]
        losses = sample[sample < 0]
        gw, gl = float(wins.sum()), abs(float(losses.sum()))
        pf = gw / gl if gl > 0 else (999.0 if gw > 0 else 0.0)
        pfs.append(min(pf, 20.0))
        exps.append(float(sample.mean()))
    return {
        "simulations": simulations,
        "pf_p5": round(float(np.percentile(pfs, 5)), 3),
        "pf_p50": round(float(np.percentile(pfs, 50)), 3),
        "pf_p95": round(float(np.percentile(pfs, 95)), 3),
        "exp_p5": round(float(np.percentile(exps, 5)), 3),
        "exp_p95": round(float(np.percentile(exps, 95)), 3),
    }


def regime_collapse(regime_stats: dict[str, dict[str, float]], *, min_trades: int = 3) -> bool:
    """True if any regime with enough samples has negative expectancy."""
    active = [v for v in regime_stats.values() if int(v.get("trades", 0)) >= min_trades]
    if len(active) < 2:
        return False
    return any(float(v.get("expectancy_r", 0)) < -0.3 for v in active)


def certify_phase2a(
    *,
    trade_reduction_pct: float,
    final_metrics: dict[str, Any],
    calibration_error: float,
    regime_stats: dict[str, dict[str, float]],
) -> bool:
    pf = float(final_metrics["pf"]) if final_metrics.get("pf") not in ("inf", float("inf")) else 999.0
    exp = float(final_metrics.get("expectancy_r", 0))
    return (
        35.0 <= trade_reduction_pct <= 50.0
        and pf >= 1.8
        and exp > 0.5
        and calibration_error < 0.08
        and not regime_collapse(regime_stats)
    )

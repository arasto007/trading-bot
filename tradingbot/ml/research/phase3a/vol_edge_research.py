"""Phase 3A — VOL edge reconstruction research (no live enable)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

ATR_BANDS = [(20, 60), (25, 65), (30, 70), (35, 75)]
SL_ATR_MULTS = [1.2, 1.5, 2.0, 2.5]
RR_TARGETS = [0.8, 1.0, 1.2, 1.5]
SESSIONS = {
    "London": (7, 12),
    "NY": (13, 17),
    "Overlap": (13, 16),
}


def session_name(hour: int) -> str | None:
    for name, (lo, hi) in SESSIONS.items():
        if lo <= hour < hi:
            return name
    return None


def regime_cluster(atr_pct: float) -> str:
    """Map ATR percentile to LOW / NORMAL / EXPANSION / EXTREME."""
    p = float(atr_pct) * 100.0 if atr_pct <= 1.0 else float(atr_pct)
    if p < 25:
        return "LOW"
    if p < 50:
        return "NORMAL"
    if p < 75:
        return "EXPANSION"
    return "EXTREME"


def _metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {
            "trades": 0,
            "win_rate_pct": 0.0,
            "pf": 0.0,
            "expectancy_r": 0.0,
            "max_dd_r": 0.0,
        }
    rs = [float(t["r_multiple"]) for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    gw, gl = sum(wins), abs(sum(losses))
    pf = gw / gl if gl > 0 else (999.0 if gw > 0 else 0.0)
    eq = peak = mdd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    return {
        "trades": len(trades),
        "win_rate_pct": round(len(wins) / len(rs) * 100, 2),
        "pf": round(pf, 3) if pf != 999.0 else "inf",
        "expectancy_r": round(sum(rs) / len(rs), 3),
        "max_dd_r": round(mdd, 2),
    }


def _pf_num(pf: Any) -> float:
    if pf in ("inf", float("inf")):
        return 999.0
    return float(pf)


def regime_breakdown(trades: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for reg in ("LOW", "NORMAL", "EXPANSION", "EXTREME"):
        subset = [t for t in trades if t.get("regime") == reg]
        out[reg] = _metrics(subset)
    return out


def monte_carlo(
    trades: list[dict[str, Any]],
    *,
    simulations: int = 1000,
    seed: int = 42,
) -> dict[str, Any]:
    rs = np.asarray([float(t["r_multiple"]) for t in trades], dtype=float)
    if len(rs) < 5:
        return {
            "simulations": 0,
            "pf_median": 0.0,
            "pf_p5": 0.0,
            "pf_p95": 0.0,
            "exp_median": 0.0,
            "worst_5pct_dd_r": 0.0,
        }
    rng = np.random.default_rng(seed)
    pfs: list[float] = []
    exps: list[float] = []
    dds: list[float] = []
    for _ in range(simulations):
        sample = rng.choice(rs, size=len(rs), replace=True)
        wins = sample[sample > 0]
        losses = sample[sample < 0]
        gw, gl = float(wins.sum()), abs(float(losses.sum()))
        pf = gw / gl if gl > 0 else (999.0 if gw > 0 else 0.0)
        pfs.append(min(pf, 50.0))
        exps.append(float(sample.mean()))
        eq = peak = mdd = 0.0
        for r in sample:
            eq += r
            peak = max(peak, eq)
            mdd = max(mdd, peak - eq)
        dds.append(mdd)
    return {
        "simulations": simulations,
        "pf_median": round(float(np.median(pfs)), 3),
        "pf_p5": round(float(np.percentile(pfs, 5)), 3),
        "pf_p95": round(float(np.percentile(pfs, 95)), 3),
        "exp_median": round(float(np.median(exps)), 3),
        "worst_5pct_dd_r": round(float(np.percentile(dds, 95)), 2),
    }


@dataclass(frozen=True)
class VolVariant:
    atr_lo: int
    atr_hi: int
    sl_atr: float
    rr: float
    session: str

    @property
    def key(self) -> str:
        return f"ATR{self.atr_lo}-{self.atr_hi}_SL{self.sl_atr}_RR{self.rr}_{self.session}"


def scan_vol_candidates(df: pd.DataFrame, *, warmup: int = 500) -> list[dict[str, Any]]:
    """Collect raw VOL direction signals before variant filters."""
    from tradingbot.strategies.vol_regime_signal import evaluate_at_index, prepare_frame

    frame = prepare_frame(df)
    cands: list[dict[str, Any]] = []
    for i in range(max(warmup, 60), len(frame)):
        sig = evaluate_at_index(frame, i)
        if sig is None:
            continue
        ts = frame.index[i]
        hour = int(pd.Timestamp(ts).hour)
        row = frame.iloc[i]
        cands.append({
            "bar_index": i,
            "bar_time": str(ts),
            "hour": hour,
            "direction": int(sig.direction),
            "side": sig.side,
            "atr_pct": float(sig.atr_pct),
            "atr14": float(row["atr14"]),
            "entry": float(row["close"]),
            "regime": regime_cluster(float(sig.atr_pct)),
        })
    return cands


def simulate_variant(
    df: pd.DataFrame,
    candidates: list[dict[str, Any]],
    variant: VolVariant,
    *,
    cooldown_bars: int = 8,
    max_trades_per_day: int = 4,
) -> list[dict[str, Any]]:
    from tradingbot.ml.research.phase35.label_alignment import resolve_label_with_sl_tp

    atr_lo = variant.atr_lo / 100.0
    atr_hi = variant.atr_hi / 100.0
    sess_lo, sess_hi = SESSIONS[variant.session]
    trades: list[dict[str, Any]] = []
    open_until = last = -9999
    day_counts: dict[str, int] = {}

    for c in candidates:
        i = int(c["bar_index"])
        if i <= open_until or i - last < cooldown_bars:
            continue
        atr_pct = float(c["atr_pct"])
        if not (atr_lo <= atr_pct <= atr_hi):
            continue
        hour = int(c["hour"])
        if not (sess_lo <= hour < sess_hi):
            continue
        day = str(pd.Timestamp(c["bar_time"]).date())
        if day_counts.get(day, 0) >= max_trades_per_day:
            continue

        price = float(c["entry"])
        atr = float(c["atr14"])
        d = int(c["direction"])
        sl_dist = atr * variant.sl_atr
        if d > 0:
            sl = price - sl_dist
            tp = price + sl_dist * variant.rr
        else:
            sl = price + sl_dist
            tp = price - sl_dist * variant.rr

        outcome = resolve_label_with_sl_tp(
            df, i, d, sl, tp, future_window_bars=72, entry_price=price
        )
        sl_d = abs(price - sl)
        if outcome.get("exit_reason") == "tp" and sl_d > 0:
            r_mult = abs(tp - price) / sl_d
        elif outcome.get("exit_reason") == "sl":
            r_mult = -1.0
        else:
            r_mult = 0.0
        hold = int(outcome.get("bars", 1) or 1)
        open_until = i + max(hold, 1)
        last = i
        day_counts[day] = day_counts.get(day, 0) + 1

        trades.append({
            **c,
            "stop_loss": sl,
            "take_profit": tp,
            "sl_atr": variant.sl_atr,
            "rr": variant.rr,
            "session": variant.session,
            "atr_band": f"{variant.atr_lo}-{variant.atr_hi}",
            "r_multiple": round(r_mult, 3),
            "exit_reason": outcome.get("exit_reason"),
            "variant": variant.key,
        })
    return trades


def passes_winner_gate(metrics: dict[str, Any], mc: dict[str, Any]) -> bool:
    return (
        int(metrics["trades"]) >= 80
        and _pf_num(metrics["pf"]) >= 1.2
        and float(metrics["expectancy_r"]) > 0.15
        and float(metrics["max_dd_r"]) < 12.0
        and float(mc.get("pf_median", 0)) > 1.1
    )


def run_variant_matrix(
    df: pd.DataFrame,
    *,
    simulations: int = 1000,
) -> dict[str, Any]:
    candidates = scan_vol_candidates(df)
    baseline = simulate_variant(
        df,
        candidates,
        VolVariant(30, 70, 2.5, 0.8, "Overlap"),
    )
    results: list[dict[str, Any]] = []

    for atr_lo, atr_hi in ATR_BANDS:
        for sl in SL_ATR_MULTS:
            for rr in RR_TARGETS:
                for session in SESSIONS:
                    v = VolVariant(atr_lo, atr_hi, sl, rr, session)
                    trades = simulate_variant(df, candidates, v)
                    m = _metrics(trades)
                    mc = monte_carlo(trades, simulations=simulations)
                    reg = regime_breakdown(trades)
                    row = {
                        "variant": v.key,
                        "atr_band": f"{atr_lo}-{atr_hi}",
                        "sl_atr": sl,
                        "rr": rr,
                        "session": session,
                        **m,
                        "monte_carlo": mc,
                        "regime_breakdown": reg,
                        "winner": passes_winner_gate(m, mc),
                    }
                    results.append(row)

    winners = [r for r in results if r["winner"]]
    pool = winners if winners else results
    best = max(pool, key=lambda r: (_pf_num(r["pf"]), float(r["expectancy_r"]), -float(r["max_dd_r"])))

    return {
        "candidates": len(candidates),
        "baseline_current": _metrics(baseline),
        "variants_tested": len(results),
        "winners": winners,
        "best": best,
        "all_results": results,
    }

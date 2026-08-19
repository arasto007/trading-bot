"""Bootstrap, Monte Carlo, walk-forward validation for Phase 31C."""

from __future__ import annotations

import random
import statistics
from typing import Any

import pandas as pd

from tradingbot.ml.research.phase31b.metrics import compute_metrics, trades_to_pseudo
from tradingbot.ml.research.phase26b.analyzers import _profit_factor


def _pf_from_pnls(pnls: list[float]) -> float:
    w = sum(p for p in pnls if p > 0)
    l = abs(sum(p for p in pnls if p < 0))
    return float(w / l) if l > 0 else 999.0


def bootstrap_validation(trades: list[dict], *, n: int = 400, seed: int = 42) -> dict[str, Any]:
    pnls = [float(t["pnl"]) for t in trades]
    if len(pnls) < 10:
        return {"valid": False, "reason": "insufficient_trades"}
    rng = random.Random(seed)
    pfs = []
    nets = []
    for _ in range(n):
        sample = [rng.choice(pnls) for _ in range(len(pnls))]
        pfs.append(_pf_from_pnls(sample))
        nets.append(sum(sample))
    pfs.sort()
    nets.sort()
    return {
        "simulations": n,
        "pf_median": round(statistics.median(pfs), 4),
        "pf_p05": round(pfs[int(0.05 * len(pfs))], 4),
        "pf_p95": round(pfs[int(0.95 * len(pfs))], 4),
        "net_median": round(statistics.median(nets), 2),
        "confidence": 95,
    }


def montecarlo_validation(trades: list[dict], *, n: int = 500, seed: int = 42) -> dict[str, Any]:
    """Trade-order shuffle — sequence risk."""
    pnls = [float(t["pnl"]) for t in trades]
    rng = random.Random(seed)
    nets = []
    for _ in range(n):
        shuffled = pnls.copy()
        rng.shuffle(shuffled)
        nets.append(sum(shuffled))
    nets.sort()
    return {
        "simulations": n,
        "net_median": round(statistics.median(nets), 2),
        "net_p05": round(nets[int(0.05 * len(nets))], 2),
        "net_p95": round(nets[int(0.95 * len(nets))], 2),
        "sequence_risk": "LOW" if nets[int(0.05 * len(nets))] > 0 else "HIGH",
    }


def walkforward_validation(
    trade_results: list[dict],
    *,
    train_frac: float = 0.7,
) -> dict[str, Any]:
    """Chronological split — test PF must hold."""
    df = pd.DataFrame(trade_results)
    df["ts"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("ts")
    cut = int(len(df) * train_frac)
    train = df.iloc[:cut]
    test = df.iloc[cut:]

    def _metrics(sub: pd.DataFrame) -> dict:
        pseudo = [{"pnl": r["pnl"], "pnl_r": r.get("pnl_r", 0), "timestamp": r["timestamp"],
                   "exit_timestamp": r.get("exit_timestamp"), "duration_bars": r.get("duration_bars", 1)}
                  for _, r in sub.iterrows()]
        return compute_metrics(pseudo)

    train_m = _metrics(train)
    test_m = _metrics(test)
    stable = test_m["profit_factor"] >= train_m["profit_factor"] * 0.85
    return {
        "train_trades": int(len(train)),
        "test_trades": int(len(test)),
        "train_pf": train_m["profit_factor"],
        "test_pf": test_m["profit_factor"],
        "train_net": train_m["net_profit"],
        "test_net": test_m["net_profit"],
        "stable": stable,
        "walkforward_pass": stable and test_m["net_profit"] > 0,
    }


def rejection_check(candidate: dict, baseline_pf: float) -> dict[str, Any]:
    """Reject overfitting / hindsight / instability."""
    reasons = []
    m = candidate["metrics"]
    wf = candidate.get("walkforward", {})
    if m.get("profit_factor", 0) > baseline_pf * 3 and not wf.get("walkforward_pass", False):
        reasons.append("pf_spike_without_walkforward_stability")
    if candidate.get("uses_future_info"):
        reasons.append("uses_future_info")
    if not candidate.get("live_implementable", True):
        reasons.append("not_live_implementable")
    if wf and not wf.get("stable", True):
        reasons.append("walkforward_unstable")
    if m.get("trade_count", 0) < 50:
        reasons.append("insufficient_sample")
    rejected = len(reasons) > 0 and "uses_future_info" in reasons
    return {"rejected": rejected, "reject_reasons": reasons, "passed": len(reasons) == 0}

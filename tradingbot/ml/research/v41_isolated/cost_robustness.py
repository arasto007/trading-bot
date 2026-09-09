"""Phase 1.5.41–1.5.45 — cost audit, sensitivity, break-even, robustness (offline)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.research.v41_isolated.replay import MIN_TRADES_FOR_INFERENCE, summarize_r

BOOK_PATH = Path("data/ml/reports/phase15_36/v41_isolated_trend_replay.json")
REPORTS_DIR = Path("data/ml/reports/phase15_41")

# Conservative lab bar — NOT a live-profitability claim. Matches v40-class PF floor (1.21)
# without copying v40 factors. SENSITIVITY only.
CONSERVATIVE_PF_MIN = 1.20
CONSERVATIVE_EXP_MIN = 0.05
SLICE_MIN = 30

# Extended deterministic R-cost grid (Phase 1.5.48). NOT measured broker costs.
EXTENDED_COST_GRID_R: tuple[float, ...] = (0.00, 0.01, 0.02, 0.03, 0.04, 0.05, 0.08, 0.10)
ROLLING_WINDOWS: tuple[int, ...] = (250, 500)
COST_SCENARIOS_R: tuple[tuple[str, float, str], ...] = (
    ("zero", 0.0, "existing baseline — no spread/slippage/commission"),
    ("low", 0.01, "optimistic round-trip 0.01 R/trade — not a measured spread"),
    ("medium", 0.03, "round-trip 0.03 R/trade ≈ current OOS expectancy"),
    ("high", 0.08, "round-trip 0.08 R/trade — still below many gold-point defaults if ATR is moderate"),
)

# Paper / backtest DEFAULTS — class B assumptions, not historical fills.
PAPER_SPREAD_POINTS = 0.30
PAPER_SLIPPAGE_POINTS = 0.10
BACKTEST_SPREAD_PIPS = 2.5
BACKTEST_SLIPPAGE_PIPS = 0.8
XAU_PIP_SIZE = 0.1  # tradingbot.domain.position_logic.pip_size for XAU*


def load_isolated_book(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or BOOK_PATH
    if not p.is_file():
        raise FileNotFoundError(f"isolated v41 book missing: {p}")
    payload = json.loads(p.read_text(encoding="utf-8"))
    trades = payload.get("trades") or []
    if not trades:
        raise ValueError("isolated v41 book has no trades")
    return trades


def oos_trades(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [t for t in trades if t.get("split") == "oos"]


def extended_sensitivity(returns: list[float]) -> dict[str, Any]:
    """Deterministic flat-R grid. Does not claim these are broker costs."""
    out: dict[str, Any] = {}
    for c in EXTENDED_COST_GRID_R:
        key = f"{c:.2f}R"
        m = book_metrics(returns, cost_r=c)
        m["kind"] = "SENSITIVITY"
        m["not_measured_broker_cost"] = True
        out[key] = m
    return out


def rolling_trade_windows(
    returns: list[float],
    *,
    window: int,
) -> dict[str, Any]:
    """Time-ordered rolling metrics. Diagnostic only — no filter selection."""
    arr = np.asarray(returns, dtype=float)
    n = int(len(arr))
    if n < window or window < SLICE_MIN:
        return {
            "window": window,
            "status": "INSUFFICIENT",
            "n": n,
            "n_windows": 0,
        }
    exps: list[float] = []
    pfs: list[float] = []
    dds: list[float] = []
    for i in range(0, n - window + 1):
        chunk = arr[i : i + window].tolist()
        m = summarize_r(chunk)
        if m["expectancy"] is None:
            continue
        exps.append(float(m["expectancy"]))
        pf = m["profit_factor"]
        if isinstance(pf, (int, float)) and np.isfinite(pf):
            pfs.append(float(pf))
        dds.append(float(m["max_drawdown_r"]))
    if not exps:
        return {"window": window, "status": "INSUFFICIENT", "n": n, "n_windows": 0}
    exp_a = np.asarray(exps)
    pf_a = np.asarray(pfs) if pfs else np.array([np.nan])
    return {
        "window": window,
        "status": "OK",
        "n": n,
        "n_windows": int(len(exps)),
        "expectancy": {
            "min": round(float(exp_a.min()), 6),
            "p25": round(float(np.percentile(exp_a, 25)), 6),
            "p50": round(float(np.percentile(exp_a, 50)), 6),
            "p75": round(float(np.percentile(exp_a, 75)), 6),
            "max": round(float(exp_a.max()), 6),
            "frac_positive": round(float(np.mean(exp_a > 0)), 6),
        },
        "profit_factor": {
            "min": round(float(np.nanmin(pf_a)), 6),
            "p50": round(float(np.nanmedian(pf_a)), 6),
            "max": round(float(np.nanmax(pf_a)), 6),
            "frac_gt_1": round(float(np.mean(pf_a > 1.0)), 6) if pfs else None,
        },
        "max_drawdown_r": {
            "min": round(float(np.min(dds)), 4),
            "p50": round(float(np.median(dds)), 4),
            "max": round(float(np.max(dds)), 4),
        },
        "note": "rolling windows are diagnostic; a good window is not a live filter",
    }


def apply_flat_cost_r(returns: list[float], cost_r: float) -> list[float]:
    """Round-trip cost subtracted from every trade. Does not invent fills."""
    c = float(cost_r)
    return [float(r) - c for r in returns]


def book_metrics(returns: list[float], *, cost_r: float = 0.0) -> dict[str, Any]:
    net = apply_flat_cost_r(returns, cost_r)
    m = summarize_r(net)
    m["cost_r_per_trade"] = round(float(cost_r), 6)
    m["terminal_equity_r"] = m["total_r"]
    m["expectancy_positive"] = bool(m["expectancy"] is not None and m["expectancy"] > 0)
    pf = m["profit_factor"]
    m["pf_gt_1"] = bool(isinstance(pf, (int, float)) and pf > 1.0)
    m["clears_conservative_viability"] = bool(
        m["meaningful"]
        and m["expectancy"] is not None
        and m["expectancy"] >= CONSERVATIVE_EXP_MIN
        and isinstance(pf, (int, float))
        and pf >= CONSERVATIVE_PF_MIN
    )
    return m


def break_even_cost_r(returns: list[float]) -> dict[str, Any]:
    """Max constant round-trip cost_R before expectancy=0 and before PF=1."""
    arr = np.asarray(returns, dtype=float)
    n = int(len(arr))
    if n == 0:
        return {
            "n": 0,
            "expectancy_zero_cost_r": None,
            "pf_one_cost_r": None,
            "note": "empty series",
        }
    exp0 = float(arr.mean())
    # Expectancy after flat cost: mean(R) - c. Zero at c = mean(R).
    exp_be = exp0
    # PF=1 after reclassification: binary search on c.
    lo, hi = 0.0, max(0.0, float(np.max(np.abs(arr))) + 0.5)
    pf_be = None
    for _ in range(60):
        mid = (lo + hi) / 2.0
        m = summarize_r(apply_flat_cost_r(arr.tolist(), mid))
        pf = m["profit_factor"]
        net = float(np.mean(apply_flat_cost_r(arr.tolist(), mid)))
        # PF<=1 or undefined when net<=0 and there are losses
        at_or_below = (
            net <= 0
            or pf is None
            or (isinstance(pf, (int, float)) and pf <= 1.0)
        )
        if at_or_below:
            pf_be = mid
            hi = mid
        else:
            lo = mid
    return {
        "n": n,
        "gross_expectancy": round(exp0, 6),
        "expectancy_zero_cost_r": round(exp_be, 6),
        "pf_one_cost_r": round(float(pf_be if pf_be is not None else hi), 6),
        "formula_expectancy": "c* = mean(R_i); R_net = R_gross - c for every trade",
        "formula_pf": "smallest c such that PF(R - c) <= 1 (binary search; winners can flip to losses)",
        "not_evidence_of_actual_costs": True,
    }


def session_label(ts: pd.Timestamp) -> str:
    hour = int(pd.Timestamp(ts).hour)
    if 0 <= hour < 8:
        return "asian"
    if 8 <= hour < 13:
        return "london"
    if 13 <= hour < 16:
        return "overlap"
    if 16 <= hour < 21:
        return "new_york"
    return "late"


def duration_bucket(hold_bars: int) -> str:
    h = int(hold_bars)
    if h <= 3:
        return "1-3"
    if h <= 12:
        return "4-12"
    if h <= 36:
        return "13-36"
    return "37-72"


def probability_bucket(prob: float) -> str:
    p = float(prob)
    if p < 0.45:
        return "0.40-0.45"
    if p < 0.50:
        return "0.45-0.50"
    if p < 0.60:
        return "0.50-0.60"
    return "0.60+"


def _slice_table(trades: list[dict[str, Any]], key_fn, *, cost_r: float = 0.0) -> list[dict[str, Any]]:
    groups: dict[str, list[float]] = {}
    for t in trades:
        groups.setdefault(str(key_fn(t)), []).append(float(t["r_multiple"]))
    rows: list[dict[str, Any]] = []
    for name in sorted(groups):
        rs = groups[name]
        n = len(rs)
        row = book_metrics(rs, cost_r=cost_r)
        row["slice"] = name
        row["insufficient"] = n < SLICE_MIN
        if row["insufficient"]:
            row["note"] = f"n={n} < {SLICE_MIN} — insufficient for inference"
        rows.append(row)
    return rows


def concentration(trades: list[dict[str, Any]]) -> dict[str, Any]:
    rs = np.asarray([float(t["r_multiple"]) for t in trades], dtype=float)
    if len(rs) == 0:
        return {"n": 0}
    total = float(rs.sum())
    winners = np.sort(rs[rs > 0])[::-1]
    def share(k: int) -> float | None:
        if total <= 0 or len(winners) == 0:
            return None
        take = min(k, len(winners))
        return round(float(winners[:take].sum()) / total, 6)
    n = len(rs)
    top1 = max(1, int(round(0.01 * n)))
    top5 = max(1, int(round(0.05 * n)))
    top10 = max(1, int(round(0.10 * n)))
    # longest losing streak on the time-ordered book
    streak = best = 0
    for r in rs:
        if r < 0:
            streak += 1
            best = max(best, streak)
        else:
            streak = 0
    return {
        "n": n,
        "total_r": round(total, 4),
        "n_winners": int((rs > 0).sum()),
        "top_1pct_winners_share_of_total_r": share(top1),
        "top_5pct_winners_share_of_total_r": share(top5),
        "top_10pct_winners_share_of_total_r": share(top10),
        "top_10_winners_share_of_total_r": share(10),
        "longest_losing_streak": int(best),
        "max_single_win_r": round(float(rs.max()), 4),
        "max_single_loss_r": round(float(rs.min()), 4),
    }


def recover_atr_at_timestamps(timestamps: list[str]) -> dict[str, Any]:
    """Causal ATR(14) at trade timestamps — unit conversion only, not a cost model."""
    from tradingbot.ml.data.stores.candle_store import CandleStore
    from tradingbot.ml.research.phase13_9.candle_prepare import normalize_candles_index, true_range_series
    from tradingbot.ml.research.trend_strategy.trend_features import _atr_series

    candles = CandleStore().load("XAUUSD", "M5")
    if candles is None or candles.empty:
        return {"ok": False, "reason": "XAUUSD M5 candles missing"}
    df = normalize_candles_index(candles)
    atr = _atr_series(df, tr=true_range_series(df))
    values: list[float | None] = []
    missing = 0
    for ts in timestamps:
        t = pd.Timestamp(ts)
        if t.tzinfo is None:
            t = t.tz_localize("UTC")
        else:
            t = t.tz_convert("UTC")
        v: Any = np.nan
        if t in atr.index:
            v = atr.loc[t]
        elif len(atr):
            loc = int(atr.index.searchsorted(t))
            loc = min(max(loc, 0), len(atr) - 1)
            v = atr.iloc[loc]
        if v is None or (isinstance(v, (float, np.floating)) and not np.isfinite(v)):
            missing += 1
            values.append(None)
            continue
        values.append(float(v))
    finite = [v for v in values if v is not None]
    if not finite:
        return {"ok": False, "reason": "no ATR mapped", "missing": missing}
    arr = np.asarray(finite, dtype=float)
    return {
        "ok": True,
        "n_mapped": int(len(arr)),
        "n_missing": missing,
        "atr_mean": round(float(arr.mean()), 6),
        "atr_median": round(float(np.median(arr)), 6),
        "atr_p25": round(float(np.percentile(arr, 25)), 6),
        "atr_p75": round(float(np.percentile(arr, 75)), 6),
        "one_r_equals": "ATR * sl_atr_mult=1.0 (price points)",
        "values": arr.tolist(),
    }


def assumption_cost_from_points(atr_values: list[float], round_trip_points: float) -> list[float]:
    """cost_R_i = round_trip_points / ATR_i. Skips non-positive ATR."""
    out: list[float] = []
    for a in atr_values:
        if a is None or a <= 0:
            continue
        out.append(float(round_trip_points) / float(a))
    return out


def metrics_per_trade_cost(returns: list[float], costs: list[float]) -> dict[str, Any]:
    if len(returns) != len(costs):
        n = min(len(returns), len(costs))
        returns, costs = returns[:n], costs[:n]
    net = [float(r) - float(c) for r, c in zip(returns, costs)]
    m = summarize_r(net)
    c_arr = np.asarray(costs, dtype=float)
    m["cost_r_mean"] = round(float(c_arr.mean()), 6) if len(c_arr) else None
    m["cost_r_median"] = round(float(np.median(c_arr)), 6) if len(c_arr) else None
    m["terminal_equity_r"] = m["total_r"]
    m["expectancy_positive"] = bool(m["expectancy"] is not None and m["expectancy"] > 0)
    pf = m["profit_factor"]
    m["pf_gt_1"] = bool(isinstance(pf, (int, float)) and pf > 1.0)
    m["clears_conservative_viability"] = bool(
        m["meaningful"]
        and m["expectancy"] is not None
        and m["expectancy"] >= CONSERVATIVE_EXP_MIN
        and isinstance(pf, (int, float))
        and pf >= CONSERVATIVE_PF_MIN
    )
    return m


def classify_phase50(payload: dict[str, Any]) -> dict[str, Any]:
    """Conservative 1.5.50 class. Does not write production factors."""
    sens = payload.get("extended_sensitivity_oos") or {}
    zero = sens.get("0.00R") or {}
    c03 = sens.get("0.03R") or {}
    c04 = sens.get("0.04R") or {}
    tape = int((payload.get("cost_model_audit") or {}).get("historical_spread_tick_files") or 0)
    live_n = int((payload.get("measured_live_entry_slippage") or {}).get("n") or 0)
    n_oos = int(zero.get("trades") or 0)
    exp0 = zero.get("expectancy")

    if n_oos < MIN_TRADES_FOR_INFERENCE:
        letter, reason = "C", "OOS book too small"
    elif exp0 is not None and exp0 <= 0:
        letter, reason = "D", "uncosted OOS expectancy is not positive"
    elif tape == 0 and c04.get("expectancy_positive") is False:
        letter, reason = "C", (
            "no historical spread/tick tape; OOS expectancy is not positive at a modest 0.04 R "
            "round-trip (just above break-even 0.033 R). 17 live entry-slippage rows are INSUFFICIENT."
        )
    elif tape == 0 and not c03.get("clears_conservative_viability"):
        letter, reason = "C", (
            "real broker cost tape unavailable; uncosted/0.03 R books never clear conservative "
            f"viability (PF>={CONSERVATIVE_PF_MIN}, exp>={CONSERVATIVE_EXP_MIN}); live fills n={live_n}"
        )
    elif (
        tape > 0
        and live_n >= MIN_TRADES_FOR_INFERENCE
        and c03.get("clears_conservative_viability")
        and payload.get("robustness", {}).get("stability_verdict") == "broad_and_stable"
    ):
        letter, reason = "A", "cost robustness demonstrated — still not production-activated"
    else:
        letter, reason = "B", "thin uncosted edge remains; real-world full-tape costs still unknown"

    return {
        "classification": letter,
        "reason": reason,
        "v41_remains_neutral_1_0": True,
        "production_calibrators_modified": False,
        "real_world_costs": (
            "UNKNOWN as a full tape; "
            f"{live_n} live journal entry-slippage rows exist but are INSUFFICIENT for a v41 cost model"
        ),
        "label": "SENSITIVITY ANALYSIS plus a tiny measured live-slip sample — not proof of live profitability",
    }


def classify_v41_after_costs(payload: dict[str, Any]) -> dict[str, Any]:
    """Exactly one of A/B/C/D. Does not write production factors."""
    zero = payload.get("sensitivity_oos", {}).get("zero") or {}
    low = payload.get("sensitivity_oos", {}).get("low") or {}
    medium = payload.get("sensitivity_oos", {}).get("medium") or {}
    paper = payload.get("labeled_assumption_scenarios", {}).get("paper_round_trip") or {}
    real_costs = payload.get("cost_model_audit", {}).get("historical_spread_tick_files", 0)

    def _pos(row: dict[str, Any]) -> bool:
        return bool(row.get("expectancy_positive") and row.get("pf_gt_1"))

    if int(zero.get("trades") or 0) < MIN_TRADES_FOR_INFERENCE:
        letter, reason = "C", "OOS book too small"
    elif real_costs == 0 and not _pos(low):
        letter, reason = "C", (
            "no historical cost tape; OOS edge dies under even the optimistic 0.01 R round-trip assumption"
        )
    elif real_costs == 0 and not _pos(medium):
        letter, reason = "C", (
            "no historical cost tape; OOS edge does not survive a 0.03 R round-trip "
            "(equal to current uncosted expectancy)"
        )
    elif paper and paper.get("expectancy_positive") is False:
        letter, reason = "C", (
            "under PaperBroker round-trip assumption (class B, not measured) OOS expectancy is not positive"
        )
    elif (
        _pos(medium)
        and paper.get("clears_conservative_viability")
        and payload.get("robustness", {}).get("no_concentration_problem")
    ):
        letter, reason = "A", "edge survives plausible costs with acceptable robustness — still not activated"
    elif _pos(zero) and not _pos(low):
        letter, reason = "C", "uncosted OOS PF>1 is not usable; plausible costs remove the edge"
    else:
        letter, reason = "B", "thin uncosted OOS edge remains; real-world costs still unknown"

    if zero and (zero.get("expectancy") is not None) and zero["expectancy"] <= 0:
        letter, reason = "D", "uncosted OOS expectancy is not positive"

    return {
        "classification": letter,
        "reason": reason,
        "v41_remains_neutral_1_0": True,
        "production_calibrators_modified": False,
        "real_world_costs": "UNKNOWN — no historical spread/tick files",
        "label": "SENSITIVITY ANALYSIS, not proof of live profitability",
    }

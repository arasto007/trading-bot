"""Offline orchestrator for v41 cost realism & robustness (no live path)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import reports_dir, spread_dir, ticks_dir
from tradingbot.ml.research.v41_isolated.cost_robustness import (
    BACKTEST_SLIPPAGE_PIPS,
    BACKTEST_SPREAD_PIPS,
    BOOK_PATH,
    CONSERVATIVE_EXP_MIN,
    CONSERVATIVE_PF_MIN,
    COST_SCENARIOS_R,
    PAPER_SLIPPAGE_POINTS,
    PAPER_SPREAD_POINTS,
    XAU_PIP_SIZE,
    assumption_cost_from_points,
    book_metrics,
    break_even_cost_r,
    classify_v41_after_costs,
    concentration,
    duration_bucket,
    load_isolated_book,
    metrics_per_trade_cost,
    oos_trades,
    probability_bucket,
    recover_atr_at_timestamps,
    session_label,
    _slice_table,
)
from tradingbot.ml.research.v41_isolated.replay import summarize_r


def _count_files(root: Path) -> int:
    if not root.is_dir():
        return 0
    return sum(1 for p in root.rglob("*") if p.is_file())


def cost_model_audit() -> dict[str, Any]:
    n_spread = _count_files(spread_dir())
    n_ticks = _count_files(ticks_dir())
    mechanisms = [
        {
            "name": "historical spread parquet",
            "path": str(spread_dir()),
            "class": "C" if n_spread == 0 else "A",
            "files": n_spread,
            "note": "directory exists; zero files — no trustworthy historical bid/ask tape",
        },
        {
            "name": "historical tick parquet",
            "path": str(ticks_dir()),
            "class": "C" if n_ticks == 0 else "A",
            "files": n_ticks,
            "note": "directory exists; zero files — cannot reconstruct fills",
        },
        {
            "name": "PaperBroker defaults",
            "path": "tradingbot/ml/paper_trading/paper_broker.py",
            "class": "B",
            "values": {
                "spread_points": PAPER_SPREAD_POINTS,
                "slippage_points": PAPER_SLIPPAGE_POINTS,
                "commission": 0.0,
            },
            "note": "paper defaults, not measured XAUUSD tape; exit spread not charged in execute_entry",
        },
        {
            "name": "BacktestConfig + SimulatedBroker",
            "path": "tradingbot/backtest/config.py",
            "class": "B",
            "values": {
                "spread_pips": BACKTEST_SPREAD_PIPS,
                "slippage_pips": BACKTEST_SLIPPAGE_PIPS,
                "pip_size_xau": XAU_PIP_SIZE,
                "round_trip_points_approx": round(
                    (BACKTEST_SPREAD_PIPS + 2 * BACKTEST_SLIPPAGE_PIPS) * XAU_PIP_SIZE, 4
                ),
            },
            "note": "hardcoded heuristics + session multipliers; pip convention 0.1 for gold",
        },
        {
            "name": "execution_costs.py simulator",
            "path": "tradingbot/execution/execution_costs.py",
            "class": "B",
            "note": "synthetic multipliers on an assumed ctx.spread_points — not a historical cost tape",
        },
        {
            "name": "phase6a apply_execution_stress",
            "path": "tradingbot/ml/research/phase6a/vol_v2_expansion.py",
            "class": "B",
            "note": "VOL-v2 research; BASE_SPREAD_PIPS=4.0; not v41 evidence",
        },
        {
            "name": "phase19a random_spread/slippage",
            "path": "tradingbot/ml/phase19a/robustness.py",
            "class": "D",
            "note": "uniform 0–0.15R / 0–0.1R fabricated stress on mixed RANGE+TREND — unsafe as v41 cost",
        },
        {
            "name": "live MT5 slippage journal",
            "path": "tradingbot/adapters/mt5_execution.py",
            "class": "C",
            "note": "live-only post-fill measurement; MT5 not started",
        },
        {
            "name": "RiskGate tick_value",
            "path": "tradingbot/adapters/risk_gate.py",
            "class": "C",
            "note": "live MT5 symbol_info — unsuitable offline",
        },
    ]
    return {
        "historical_spread_tick_files": n_spread + n_ticks,
        "real_world_xauusd_costs": "UNKNOWN",
        "do_not_invent_broker_costs": True,
        "mechanisms": mechanisms,
        "reusable_offline_method": (
            "flat R deduction on the frozen isolated book, plus optional ATR unit conversion "
            "from M5 candles (same ATR-14 as the v41 SL). Labeled SENSITIVITY, not live proof."
        ),
    }


def run_cost_robustness(*, write_reports: bool = True) -> dict[str, Any]:
    trades = load_isolated_book()
    oos = oos_trades(trades)
    oos_2025 = [t for t in oos if str(t["timestamp"]).startswith("2025")]
    oos_2026 = [t for t in oos if str(t["timestamp"]).startswith("2026")]
    oos_r = [float(t["r_multiple"]) for t in oos]

    audit = cost_model_audit()
    sensitivity = {
        name: book_metrics(oos_r, cost_r=c) | {"label": label, "kind": "SENSITIVITY"}
        for name, c, label in COST_SCENARIOS_R
    }

    be_all = break_even_cost_r(oos_r)
    be_2025 = break_even_cost_r([float(t["r_multiple"]) for t in oos_2025])
    be_2026 = break_even_cost_r([float(t["r_multiple"]) for t in oos_2026])
    sensitivity["break_even_expectancy"] = book_metrics(
        oos_r, cost_r=float(be_all["expectancy_zero_cost_r"] or 0.0)
    ) | {
        "label": "cost equal to OOS mean R — expectancy ~ 0 by construction",
        "kind": "BREAK_EVEN",
    }

    atr = recover_atr_at_timestamps([t["timestamp"] for t in oos])
    labeled: dict[str, Any] = {}
    atr_meta: dict[str, Any]
    if atr.get("ok"):
        atr_vals_raw = atr.pop("values")
        paired_r = [r for r, a in zip(oos_r, atr_vals_raw) if a is not None]
        atr_vals = [float(a) for a in atr_vals_raw if a is not None]
        paper_entry = PAPER_SPREAD_POINTS / 2.0 + PAPER_SLIPPAGE_POINTS
        paper_rt = PAPER_SPREAD_POINTS + 2.0 * PAPER_SLIPPAGE_POINTS
        bt_rt = (BACKTEST_SPREAD_PIPS + 2.0 * BACKTEST_SLIPPAGE_PIPS) * XAU_PIP_SIZE
        labeled["paper_entry_only"] = metrics_per_trade_cost(
            paired_r, assumption_cost_from_points(atr_vals, paper_entry)
        ) | {
            "kind": "LABELED_ASSUMPTION_B",
            "round_trip_points": paper_entry,
            "formula": "cost_R_i = (spread/2 + entry_slip) / ATR_i — PaperBroker entry only",
        }
        labeled["paper_round_trip"] = metrics_per_trade_cost(
            paired_r, assumption_cost_from_points(atr_vals, paper_rt)
        ) | {
            "kind": "LABELED_ASSUMPTION_B",
            "round_trip_points": paper_rt,
            "formula": "cost_R_i = (spread + 2*slip) / ATR_i — assumed both legs",
        }
        labeled["backtest_default_round_trip"] = metrics_per_trade_cost(
            paired_r, assumption_cost_from_points(atr_vals, bt_rt)
        ) | {
            "kind": "LABELED_ASSUMPTION_B",
            "round_trip_points": bt_rt,
            "formula": "cost_R_i = ((2.5 + 2*0.8)*0.1) / ATR_i",
        }
        atr_meta = dict(atr)
        med = atr.get("atr_median")
        atr_meta["implied_cost_r_at_median_atr"] = {
            "paper_entry_only": round(paper_entry / float(med), 6) if med else None,
            "paper_round_trip": round(paper_rt / float(med), 6) if med else None,
            "backtest_default_round_trip": round(bt_rt / float(med), 6) if med else None,
        }
    else:
        atr_meta = atr

    conc = concentration(oos)
    robustness = {
        "year": _slice_table(oos, lambda t: str(t["timestamp"])[:4]),
        "month": _slice_table(oos, lambda t: str(t["timestamp"])[:7]),
        "direction": _slice_table(oos, lambda t: str(t.get("direction"))),
        "session": _slice_table(oos, lambda t: session_label(t["timestamp"])),
        "duration": _slice_table(oos, lambda t: duration_bucket(int(t.get("hold_bars") or 0))),
        "probability": _slice_table(oos, lambda t: probability_bucket(float(t.get("probability") or 0))),
        "regime": _slice_table(oos, lambda t: str(t.get("regime"))),
        "concentration": conc,
        "after_medium_cost_year": _slice_table(oos, lambda t: str(t["timestamp"])[:4], cost_r=0.03),
        "trend_subtype": "ALL rows already TREND — no further subtype in the frozen book",
        "no_concentration_problem": bool(
            (conc.get("top_10_winners_share_of_total_r") or 1) < 0.25
            and (conc.get("top_5pct_winners_share_of_total_r") or 1) < 0.50
        ),
    }

    payload: dict[str, Any] = {
        "phase": "1.5.41-1.5.45",
        "offline_only": True,
        "source_book": str(BOOK_PATH),
        "n_book": len(trades),
        "n_oos": len(oos),
        "uncosted_oos": summarize_r(oos_r),
        "cost_model_audit": audit,
        "conversion": {
            "sl_atr_mult": 1.0,
            "one_r_price": "ATR(14) at entry (same series as v41 SL)",
            "flat_cost_formula": "R_net = R_gross - c  (c in R, every trade)",
            "point_cost_formula": "cost_R_i = round_trip_price_points / ATR_i",
            "conservative_viability": {
                "pf_min": CONSERVATIVE_PF_MIN,
                "expectancy_min": CONSERVATIVE_EXP_MIN,
                "note": "labeled lab bar, not live proof; not a v40-factor copy",
            },
        },
        "atr_unit_conversion": atr_meta,
        "sensitivity_oos": sensitivity,
        "break_even": {
            "oos_aggregate": be_all,
            "oos_2025": be_2025,
            "oos_2026": be_2026,
            "plain_language": (
                "The OOS book can absorb a constant round-trip cost equal to its mean R "
                "before expectancy hits zero. That number is a property of THIS book, "
                "not evidence that broker costs are below it."
            ),
        },
        "labeled_assumption_scenarios": labeled,
        "robustness": robustness,
    }
    payload["decision"] = classify_v41_after_costs(payload)

    if write_reports:
        out = reports_dir() / "phase15_41"
        out.mkdir(parents=True, exist_ok=True)
        slim = json.loads(json.dumps(payload, default=str))
        (out / "v41_cost_robustness.json").write_text(json.dumps(slim, indent=2), encoding="utf-8")
        payload["report_path"] = str(out / "v41_cost_robustness.json")
    return payload


if __name__ == "__main__":
    result = run_cost_robustness()
    keep = {
        "decision": result.get("decision"),
        "uncosted_oos": result.get("uncosted_oos"),
        "sensitivity_oos": result.get("sensitivity_oos"),
        "break_even": result.get("break_even"),
        "atr_unit_conversion": result.get("atr_unit_conversion"),
        "labeled_assumption_scenarios": result.get("labeled_assumption_scenarios"),
        "concentration": (result.get("robustness") or {}).get("concentration"),
        "year": (result.get("robustness") or {}).get("year"),
        "direction": (result.get("robustness") or {}).get("direction"),
        "session": (result.get("robustness") or {}).get("session"),
        "duration": (result.get("robustness") or {}).get("duration"),
        "probability": (result.get("robustness") or {}).get("probability"),
        "report_path": result.get("report_path"),
    }
    print(json.dumps(keep, indent=2, default=str))

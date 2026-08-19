"""Phase 53A — ML kernel validation on Phase 51 forward-demo closed trades."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.shadow.phase49a_metrics import (
    _bucket_metrics,
    _index_entries,
    _precision,
    load_shadow_events,
)

MIN_SAMPLE = 100
PF_GATE = 1.2
EXPECTANCY_GATE = 0.15
PRECISION_GATE = 60.0


def _phase51_trades_path() -> Path:
    from tradingbot.services.phase51a_forward_cert import TRADES_PATH

    return TRADES_PATH


def load_phase51_completed_trades() -> list[dict[str, Any]]:
    """Closed trades from Phase 51A forward demo window."""
    from tradingbot.services.phase51a_forward_cert import _completed_trades

    return _completed_trades(since_start=True)


def _shadow_trade_index(events: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for e in events:
        if e.get("event") != "shadow_trade_record":
            continue
        ticket = e.get("ticket")
        if ticket is not None:
            out[int(ticket)] = e
    return out


def build_phase53a_trade_records(
    *,
    phase51_trades: list[dict[str, Any]] | None = None,
    shadow_events: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    Join Phase 51 closed trades with shadow ML fields.

    Per trade: live_direction, ml_direction, ml_probability, final_R.
    """
    trades = phase51_trades if phase51_trades is not None else load_phase51_completed_trades()
    events = shadow_events if shadow_events is not None else load_shadow_events()
    entries = _index_entries(events)
    records = _shadow_trade_index(events)

    built: list[dict[str, Any]] = []
    for row in trades:
        ticket = int(row.get("ticket", 0) or 0)
        entry = row.get("entry") or {}
        exit_ = row.get("exit") or {}

        live_dir = str(entry.get("direction", "HOLD")).upper()
        final_r = float(exit_.get("pnl_R", 0) or 0)

        shadow = records.get(ticket) or entries.get(ticket)
        if shadow:
            live_dir = str(
                shadow.get("live_engine_direction") or shadow.get("direction") or live_dir
            ).upper()
            ml_dir = str(shadow.get("ml_prediction_direction", "HOLD")).upper()
            ml_prob = shadow.get("ml_probability")
            if shadow.get("event") == "shadow_trade_record":
                final_r = float(shadow.get("final_trade_R", final_r) or final_r)
        else:
            ml_dir = "HOLD"
            ml_prob = None

        agrees = ml_dir in ("BUY", "SELL") and ml_dir == live_dir
        built.append({
            "ticket": ticket,
            "live_direction": live_dir,
            "ml_direction": ml_dir,
            "ml_probability": ml_prob,
            "final_R": round(final_r, 4),
            "ml_agrees_with_live": agrees,
            "selected_engine": entry.get("selected_engine"),
            "meta_probability": entry.get("meta_probability"),
            "exit_reason": exit_.get("exit_reason"),
            "pnl_usd": exit_.get("pnl_usd"),
        })
    return built


def _pf_num(pf: Any) -> float:
    if pf in ("inf", float("inf")):
        return 999.0
    return float(pf)


def compute_phase53a_metrics(
    *,
    phase51_trades: list[dict[str, Any]] | None = None,
    shadow_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    records = build_phase53a_trade_records(
        phase51_trades=phase51_trades,
        shadow_events=shadow_events,
    )

    # Normalize for shared bucket helpers
    norm = [
        {
            "live_engine_direction": r["live_direction"],
            "ml_prediction_direction": r["ml_direction"],
            "ml_probability": r["ml_probability"],
            "final_trade_R": r["final_R"],
            "ml_agrees_with_live": r["ml_agrees_with_live"],
        }
        for r in records
    ]

    agrees = [t for t in norm if t.get("ml_agrees_with_live")]
    disagrees = [
        t for t in norm
        if not t.get("ml_agrees_with_live")
        and str(t.get("ml_prediction_direction", "")).upper() in ("BUY", "SELL")
    ]

    live_m = _bucket_metrics(norm)
    agree_m = _bucket_metrics(agrees)
    disagree_m = _bucket_metrics(disagrees)
    precision_buy = _precision(norm, "BUY")
    precision_sell = _precision(norm, "SELL")

    sample = len(records)
    agree_pf = _pf_num(agree_m["pf"])
    live_pf = _pf_num(live_m["pf"])
    disagree_pf = _pf_num(disagree_m["pf"])

    certified = (
        sample >= MIN_SAMPLE
        and agree_pf > PF_GATE
        and float(agree_m["expectancy_r"]) > EXPECTANCY_GATE
        and precision_buy > PRECISION_GATE
        and precision_sell > PRECISION_GATE
        and disagree_pf < live_pf
    )

    return {
        "sample_size": sample,
        "live_pf": live_m["pf"],
        "live_expectancy_r": live_m["expectancy_r"],
        "ml_agrees_with_live": agree_m,
        "ml_disagrees_with_live": disagree_m,
        "precision_buy_pct": precision_buy,
        "precision_sell_pct": precision_sell,
        "min_sample": MIN_SAMPLE,
        "pf_gate": PF_GATE,
        "expectancy_gate": EXPECTANCY_GATE,
        "precision_gate_pct": PRECISION_GATE,
        "disagree_pf_below_live_pf": disagree_pf < live_pf,
        "ml_kernel_live_ready": certified,
        "keep_shadow_mode": not certified,
        "trade_records": records,
    }


def format_phase53a_result(metrics: dict[str, Any]) -> str:
    agree = metrics.get("ml_agrees_with_live", {})
    disagree = metrics.get("ml_disagrees_with_live", {})
    lines = [
        "PHASE_53A_RESULT",
        f"SAMPLE_SIZE={metrics.get('sample_size', 0)}",
        f"LIVE_PF={metrics.get('live_pf', 0)}",
        f"ML_AGREE_PF={agree.get('pf', 0)}",
        f"ML_AGREE_EXPECTANCY_R={agree.get('expectancy_r', 0)}",
        f"ML_DISAGREE_PF={disagree.get('pf', 0)}",
        f"ML_DISAGREE_EXPECTANCY_R={disagree.get('expectancy_r', 0)}",
        f"PRECISION_BUY={metrics.get('precision_buy_pct', 0)}",
        f"PRECISION_SELL={metrics.get('precision_sell_pct', 0)}",
    ]
    if metrics.get("ml_kernel_live_ready"):
        lines.append("ML_KERNEL_LIVE_READY=YES")
        lines.append("USE_ML_KERNEL=true")
    else:
        lines.append("ML_KERNEL_LIVE_READY=NO")
        lines.append("KEEP_SHADOW_MODE=YES")
    return "\n".join(lines)

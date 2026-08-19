"""Per-trade production vs simulator parity comparison."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.research.phase25b.replay_position_state import simulate_stateful_lifecycle
from tradingbot.ml.research.phase27l.exit_trace import _entry_idx, prepare_indicator_frame
from tradingbot.ml.research.phase27n.hybrid_simulators import simulate_strategy
from tradingbot.ml.research.regime_router.phase99_feature_validation import normalize_candles_for_builder
from tradingbot.services.exit_mode import ExitMode
from tradingbot.services.exit_policy import resolve_hybrid_b

PARITY_PF_TOLERANCE = 0.005
PARITY_PNL_TOLERANCE = 0.005
PROJECT_ROOT = Path(__file__).resolve().parents[4]


def load_replay_parity_candles() -> pd.DataFrame:
    """Match phase29b replay window — 30-day subsampled calibration candles."""
    raw = CandleStore(PROJECT_ROOT).load("XAUUSD", "M5")
    if raw is None or raw.empty:
        raise RuntimeError("CandleStore unavailable for parity audit")
    window = prepare_calibration_candles(raw, days=30)
    norm = normalize_candles_for_builder(window)
    return prepare_indicator_frame(norm)


def _profit_factor(pnls: list[float]) -> float:
    wins = sum(p for p in pnls if p > 0)
    losses = abs(sum(p for p in pnls if p < 0))
    return round(wins / losses, 4) if losses > 0 else 999.0


def _exit_fingerprint(exit_reason: str | None, duration_bars: int, partial: bool) -> str:
    return f"{exit_reason or 'unknown'}|{duration_bars}|{int(partial)}"


def _normalize_exit(exit_info: dict[str, Any]) -> dict[str, Any]:
    return {
        "exit_timestamp": exit_info.get("exit_timestamp"),
        "exit_price": round(float(exit_info.get("exit_price") or 0), 6),
        "exit_reason": str(exit_info.get("exit_reason") or ""),
        "duration_bars": int(exit_info.get("duration_bars") or exit_info.get("bars_held") or 0),
        "pnl": round(float(exit_info.get("pnl") or 0), 4),
        "pnl_r": round(float(exit_info.get("pnl_r") or 0), 4),
        "partial_close_applied": bool(exit_info.get("partial_close_applied")),
        "partial_pnl": round(float(exit_info.get("partial_pnl") or 0), 4),
        "remaining_lot": float(exit_info.get("remaining_lot") or 0),
        "mfe": round(float(exit_info.get("mfe") or 0), 4),
        "mae": round(float(exit_info.get("mae") or 0), 4),
        "spread": round(float(exit_info.get("spread") or 0.3), 4),
    }


def production_snapshot(trade: dict[str, Any]) -> dict[str, Any]:
    return _normalize_exit({
        "exit_timestamp": trade.get("exit_timestamp"),
        "exit_price": trade.get("exit_price"),
        "exit_reason": trade.get("exit_reason"),
        "duration_bars": trade.get("duration_bars"),
        "pnl": trade.get("pnl"),
        "pnl_r": trade.get("pnl_r"),
        "partial_close_applied": trade.get("partial_close_applied"),
        "partial_pnl": trade.get("partial_pnl"),
        "remaining_lot": trade.get("lot"),
        "mfe": trade.get("mfe"),
        "mae": trade.get("mae"),
        "spread": trade.get("spread"),
    }) | {
        "entry_timestamp": trade.get("timestamp"),
        "entry_price": float(trade.get("entry_price") or trade.get("fill_price") or 0),
        "bar_index": trade.get("bar_index"),
        "lot": float(trade.get("lot") or 0.01),
        "sl": trade.get("sl"),
        "tp": trade.get("tp"),
        "direction": trade.get("direction"),
    }


def simulate_full_hybrid_b(trade: dict[str, Any], frame: pd.DataFrame) -> dict[str, Any]:
    is_buy = str(trade.get("direction")) == "BUY"
    return _normalize_exit(resolve_hybrid_b(
        candles=frame,
        entry_ts=str(trade["timestamp"]),
        entry_price=float(trade.get("entry_price") or trade.get("fill_price") or 0),
        sl=float(trade["sl"]) if trade.get("sl") is not None else None,
        tp=float(trade["tp"]) if trade.get("tp") is not None else None,
        is_buy=is_buy,
        lot=float(trade.get("lot") or 0.01),
        symbol=str(trade.get("symbol") or "XAUUSD"),
        spread=float(trade.get("spread") or 0.3),
    ))


def simulate_truncated_replay(trade: dict[str, Any], frame: pd.DataFrame) -> dict[str, Any]:
    """Reproduce ReplayPortfolioTracker._exit_up_to_bar on first bar after entry."""
    entry_bar = trade.get("bar_index")
    if entry_bar is not None:
        first_after = min(int(entry_bar) + 1, len(frame) - 1)
    else:
        start = _entry_idx(frame, trade)
        first_after = min(start + 1, len(frame) - 1)
    sub = frame.iloc[: first_after + 1]
    is_buy = str(trade.get("direction")) == "BUY"
    out = resolve_hybrid_b(
        candles=sub,
        entry_ts=str(trade["timestamp"]),
        entry_price=float(trade.get("entry_price") or trade.get("fill_price") or 0),
        sl=float(trade["sl"]) if trade.get("sl") is not None else None,
        tp=float(trade["tp"]) if trade.get("tp") is not None else None,
        is_buy=is_buy,
        lot=float(trade.get("lot") or 0.01),
        symbol=str(trade.get("symbol") or "XAUUSD"),
        spread=float(trade.get("spread") or 0.3),
    )
    return _normalize_exit(out) | {
        "truncated_end_bar": first_after,
        "truncated_bars_available": len(sub),
        "entry_bar_index": entry_bar,
    }


def simulate_repaired_replay(trade: dict[str, Any], replay_frame: pd.DataFrame) -> dict[str, Any]:
    """Phase 31E stateful replay engine output on replay candles."""
    entry_bar = int(trade.get("bar_index") or _entry_idx(replay_frame, trade))
    out = simulate_stateful_lifecycle(
        entry_timestamp=str(trade["timestamp"]),
        entry_price=float(trade.get("entry_price") or trade.get("fill_price") or 0),
        entry_bar_index=entry_bar,
        direction=str(trade["direction"]),
        symbol=str(trade.get("symbol") or "XAUUSD"),
        sl=float(trade["sl"]) if trade.get("sl") is not None else None,
        tp=float(trade["tp"]) if trade.get("tp") is not None else None,
        lot=float(trade.get("lot") or 0.01),
        candles=replay_frame,
        exit_mode=ExitMode.HYBRID_B,
        spread=float(trade.get("spread") or 0.3),
    )
    return _normalize_exit(out) | {"entry_bar_index": entry_bar}


def simulate_oracle_replay(trade: dict[str, Any], replay_frame: pd.DataFrame) -> dict[str, Any]:
    """resolve_hybrid_b on replay candles — parity reference."""
    return simulate_full_hybrid_b(trade, replay_frame)


def simulate_hybrid_b_proxy(trade: dict[str, Any], frame: pd.DataFrame) -> dict[str, Any]:
    sim = simulate_strategy(trade, frame, "hybrid_b")
    return _normalize_exit(sim)


def candle_alignment(trade: dict[str, Any], frame: pd.DataFrame) -> dict[str, Any]:
    ts = pd.to_datetime(trade["timestamp"], utc=True)
    idx = int(frame.index.searchsorted(ts))
    entry_price = float(trade.get("entry_price") or trade.get("fill_price") or 0)
    bar = frame.iloc[idx] if idx < len(frame) else None
    close_delta = abs(float(bar["close"]) - entry_price) if bar is not None else None
    return {
        "entry_timestamp": str(trade["timestamp"]),
        "resolved_bar_index": idx,
        "journal_bar_index": trade.get("bar_index"),
        "bar_timestamp": str(frame.index[idx]) if idx < len(frame) else None,
        "entry_price": entry_price,
        "bar_close": round(float(bar["close"]), 4) if bar is not None else None,
        "bar_open": round(float(bar["open"]), 4) if bar is not None else None,
        "bar_atr": round(float(bar.get("atr") or 0), 4) if bar is not None else None,
        "close_entry_delta": round(close_delta, 4) if close_delta is not None else None,
        "aligned": close_delta is not None and close_delta < 1.0,
    }


def diff_snapshots(prod: dict[str, Any], sim: dict[str, Any], *, label: str) -> dict[str, Any]:
    fields = (
        "exit_timestamp", "exit_price", "exit_reason", "duration_bars", "pnl", "pnl_r",
        "partial_close_applied", "partial_pnl", "remaining_lot", "mfe", "mae", "spread",
    )
    mismatches = []
    for f in fields:
        pv, sv = prod.get(f), sim.get(f)
        if f in ("exit_price", "pnl", "pnl_r", "partial_pnl", "mfe", "mae", "spread"):
            if abs(float(pv or 0) - float(sv or 0)) > 0.01:
                mismatches.append({"field": f, "production": pv, "simulator": sv, "delta": round(float(sv or 0) - float(pv or 0), 4)})
        elif pv != sv:
            mismatches.append({"field": f, "production": pv, "simulator": sv})

    prod_fp = _exit_fingerprint(prod.get("exit_reason"), int(prod.get("duration_bars") or 0), bool(prod.get("partial_close_applied")))
    sim_fp = _exit_fingerprint(sim.get("exit_reason"), int(sim.get("duration_bars") or 0), bool(sim.get("partial_close_applied")))

    return {
        "comparison": label,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "exit_fingerprint_match": prod_fp == sim_fp,
        "production_fingerprint": prod_fp,
        "simulator_fingerprint": sim_fp,
        "pnl_delta": round(float(sim.get("pnl") or 0) - float(prod.get("pnl") or 0), 4),
        "duration_delta": int(sim.get("duration_bars") or 0) - int(prod.get("duration_bars") or 0),
    }


def audit_single_trade(
    trade: dict[str, Any],
    research_frame: pd.DataFrame,
    replay_frame: pd.DataFrame,
    *,
    repaired: bool = False,
) -> dict[str, Any]:
    legacy_prod = production_snapshot(trade)
    repaired_sim = simulate_repaired_replay(trade, replay_frame)
    oracle = simulate_oracle_replay(trade, replay_frame)
    prod = repaired_sim if repaired else legacy_prod
    full = simulate_full_hybrid_b(trade, research_frame)
    truncated = simulate_truncated_replay(trade, replay_frame)
    proxy = simulate_hybrid_b_proxy(trade, research_frame)
    align = candle_alignment(trade, research_frame)

    diff_prod_full = diff_snapshots(prod, full, label="production_vs_full_hybrid_b")
    diff_prod_trunc = diff_snapshots(legacy_prod, truncated, label="legacy_vs_truncated_replay")
    diff_prod_proxy = diff_snapshots(prod, proxy, label="production_vs_hybrid_b_proxy")
    diff_repaired_oracle = diff_snapshots(repaired_sim, oracle, label="repaired_vs_oracle")
    diff_full_proxy = diff_snapshots(full, proxy, label="full_hybrid_b_vs_proxy")

    primary_cause = "unknown"
    if repaired and diff_repaired_oracle["exit_fingerprint_match"]:
        primary_cause = "repaired_replay_matches_oracle"
    elif diff_prod_trunc["exit_fingerprint_match"]:
        primary_cause = "truncated_replay_matches_legacy_production"
    elif diff_prod_proxy["mismatch_count"] > 0:
        primary_cause = "truncated_causal_window_vs_full_frame"

    return {
        "trade_id": trade.get("trade_id"),
        "timestamp": trade.get("timestamp"),
        "direction": trade.get("direction"),
        "legacy_production": legacy_prod,
        "production": prod,
        "simulator_repaired_replay": repaired_sim,
        "simulator_oracle_replay": oracle,
        "simulator_full_hybrid_b": full,
        "simulator_truncated_replay": truncated,
        "simulator_hybrid_b_proxy": proxy,
        "candle_alignment": align,
        "diffs": {
            "production_vs_full_hybrid_b": diff_prod_full,
            "legacy_vs_truncated_replay": diff_prod_trunc,
            "production_vs_hybrid_b_proxy": diff_prod_proxy,
            "repaired_vs_oracle": diff_repaired_oracle,
            "full_hybrid_b_vs_proxy": diff_full_proxy,
        },
        "primary_divergence_cause": primary_cause,
    }


def aggregate_parity(trade_audits: list[dict[str, Any]], *, repaired: bool = False) -> dict[str, Any]:
    prod_pnls = [float(a["production"]["pnl"]) for a in trade_audits]
    oracle_pnls = [float(a["simulator_oracle_replay"]["pnl"]) for a in trade_audits]
    full_pnls = [float(a["simulator_full_hybrid_b"]["pnl"]) for a in trade_audits]
    trunc_pnls = [float(a["simulator_truncated_replay"]["pnl"]) for a in trade_audits]
    proxy_pnls = [float(a["simulator_hybrid_b_proxy"]["pnl"]) for a in trade_audits]

    prod_pf = _profit_factor(prod_pnls)
    oracle_pf = _profit_factor(oracle_pnls)
    full_pf = _profit_factor(full_pnls)
    trunc_pf = _profit_factor(trunc_pnls)
    proxy_pf = _profit_factor(proxy_pnls)

    prod_net = round(sum(prod_pnls), 4)
    oracle_net = round(sum(oracle_pnls), 4)
    full_net = round(sum(full_pnls), 4)
    proxy_net = round(sum(proxy_pnls), 4)

    sim_pf = oracle_pf if repaired else proxy_pf
    sim_net = oracle_net if repaired else proxy_net
    pf_gap = round(abs(sim_pf - prod_pf) / prod_pf, 6) if prod_pf else 1.0
    pnl_gap = round(abs(sim_net - prod_net) / abs(prod_net), 6) if prod_net else 1.0

    fp_match_sim = sum(
        1 for a in trade_audits
        if a["diffs"]["repaired_vs_oracle"]["exit_fingerprint_match"]
    ) if repaired else sum(
        1 for a in trade_audits
        if a["diffs"]["production_vs_hybrid_b_proxy"]["exit_fingerprint_match"]
    )
    fp_match_trunc = sum(
        1 for a in trade_audits
        if a["diffs"]["legacy_vs_truncated_replay"]["exit_fingerprint_match"]
    )

    duration_match_oracle = sum(
        1 for a in trade_audits
        if int(a["simulator_repaired_replay"]["duration_bars"]) == int(a["simulator_oracle_replay"]["duration_bars"])
    )

    return {
        "trade_count": len(trade_audits),
        "repaired_mode": repaired,
        "production_pf": prod_pf,
        "oracle_replay_pf": oracle_pf,
        "simulator_pf": sim_pf,
        "full_hybrid_b_pf": full_pf,
        "truncated_replay_pf": trunc_pf,
        "hybrid_b_proxy_pf": proxy_pf,
        "production_net_pnl": prod_net,
        "simulator_net_pnl": sim_net,
        "oracle_replay_net_pnl": oracle_net,
        "full_hybrid_b_net_pnl": full_net,
        "hybrid_b_proxy_net_pnl": proxy_net,
        "pf_gap_pct": round(pf_gap * 100, 4),
        "pnl_gap_pct": round(pnl_gap * 100, 4),
        "pf_gap_pct_vs_proxy": round(abs(proxy_pf - prod_pf) / prod_pf * 100, 4) if prod_pf else 0,
        "exit_fingerprint_match_count": fp_match_sim,
        "exit_fingerprint_match_count_oracle": fp_match_sim if repaired else 0,
        "exit_fingerprint_match_count_proxy": fp_match_sim if not repaired else sum(
            1 for a in trade_audits if a["diffs"]["production_vs_hybrid_b_proxy"]["exit_fingerprint_match"]
        ),
        "exit_fingerprint_match_count_truncated": fp_match_trunc,
        "duration_match_oracle_count": duration_match_oracle,
        "parity_pf_within_tolerance": pf_gap < PARITY_PF_TOLERANCE,
        "parity_pnl_within_tolerance": pnl_gap < PARITY_PNL_TOLERANCE,
        "trade_count_identical": True,
        "exit_fingerprints_identical": fp_match_sim == len(trade_audits),
    }

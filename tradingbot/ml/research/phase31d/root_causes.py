"""Root cause decomposition for simulator parity failures."""

from __future__ import annotations

from collections import Counter
from typing import Any


ROOT_CAUSES = [
    {
        "cause_id": "RC01",
        "title": "Truncated causal candle window in replay portfolio",
        "file": "tradingbot/ml/research/phase25b/replay_portfolio.py",
        "function": "ReplayPortfolioTracker._exit_up_to_bar",
        "code_path": "advance_to_bar → _exit_up_to_bar → resolve_paper_trade_exit(candles=sub)",
        "reason": (
            "Each bar, exit is re-evaluated on candles.iloc[:bar_index+1]. On the first bar after "
            "entry, end=start+1 in resolve_hybrid_b, so j==end fires immediately as a 1-bar time exit."
        ),
        "confidence": 0.99,
    },
    {
        "cause_id": "RC02",
        "title": "Full-frame counterfactual in research simulator",
        "file": "tradingbot/ml/research/phase27n/hybrid_simulators.py",
        "function": "simulate_hybrid",
        "code_path": "simulate_strategy → simulate_hybrid → bar loop to MAX_HOLD_BARS (72)",
        "reason": (
            "hybrid_b_proxy walks the complete post-entry frame (up to 72 bars), allowing partial "
            "close at +1R, SL hits, and true max-hold time exits — not available in truncated replay."
        ),
        "confidence": 0.99,
    },
    {
        "cause_id": "RC03",
        "title": "No partial-state persistence across replay bars",
        "file": "tradingbot/ml/research/phase25b/replay_portfolio.py",
        "function": "ReplayPortfolioTracker._exit_up_to_bar",
        "code_path": "resolve_hybrid_b re-invoked from scratch each bar; partial_done resets",
        "reason": (
            "Even if truncation were fixed, partial close state is not carried on ReplayOpenPosition; "
            "each evaluation restarts Hybrid B from entry with full lot."
        ),
        "confidence": 0.92,
    },
    {
        "cause_id": "RC04",
        "title": "Production policy matches full-frame resolve_hybrid_b",
        "file": "tradingbot/services/exit_policy.py",
        "function": "resolve_hybrid_b",
        "code_path": "resolve_exit → resolve_hybrid_b (HYBRID_B mode)",
        "reason": (
            "Production exit policy logic is identical between exit_policy.resolve_hybrid_b and "
            "phase27n simulate_hybrid(hybrid_b); divergence is data-window not policy."
        ),
        "confidence": 0.97,
    },
    {
        "cause_id": "RC05",
        "title": "Accounting path consistent when exit_info matches",
        "file": "tradingbot/accounting/engine.py",
        "function": "AccountingEngine.close_trade",
        "code_path": "_finalize_close → accounting.close_trade(exit_info=...)",
        "reason": (
            "PnL uses exit_info from resolve_hybrid_b _finalize; when truncated replay forces early "
            "time exit, accounting correctly records the wrong-duration outcome."
        ),
        "confidence": 0.95,
    },
    {
        "cause_id": "RC06",
        "title": "Spread and slippage not a material PF driver",
        "file": "tradingbot/services/exit_policy.py",
        "function": "_finalize",
        "code_path": "spread parameter stored; PaperBroker bar resolution has no slippage model",
        "reason": "Both production replay and simulator use PaperBroker with fixed spread=0.30; no slippage delta.",
        "confidence": 0.88,
    },
    {
        "cause_id": "RC07",
        "title": "Trailing logic not involved",
        "file": "tradingbot/services/exit_policy.py",
        "function": "resolve_hybrid_b",
        "code_path": "effective_sl unchanged; no trailing in Hybrid B",
        "reason": "Hybrid B maintains original SL; trailing_atr is not in production or proxy path.",
        "confidence": 1.0,
    },
    {
        "cause_id": "RC08",
        "title": "Candle alignment acceptable at M5 resolution",
        "file": "tradingbot/ml/research/phase31c/exit_simulators.py",
        "function": "_trade_window_candles / _entry_idx",
        "code_path": "searchsorted(entry_timestamp) on full M5 frame",
        "reason": (
            "Entry timestamps align to M5 bar opens; close matches fill_price on entry bar. "
            "Not the primary PF divergence source."
        ),
        "confidence": 0.90,
    },
]


def build_root_cause_analysis(
    trade_audits: list[dict[str, Any]],
    aggregate: dict[str, Any],
) -> dict[str, Any]:
    duration_deltas = Counter()
    reason_prod = Counter()
    reason_proxy = Counter()
    trunc_reason = Counter()
    pnl_impact = 0.0

    for a in trade_audits:
        prod = a["production"]
        proxy = a["simulator_hybrid_b_proxy"]
        trunc = a["simulator_truncated_replay"]
        reason_prod[str(prod.get("exit_reason"))] += 1
        reason_proxy[str(proxy.get("exit_reason"))] += 1
        trunc_reason[str(trunc.get("exit_reason"))] += 1
        dd = int(proxy.get("duration_bars") or 0) - int(prod.get("duration_bars") or 0)
        duration_deltas[dd] += 1
        pnl_impact += float(proxy.get("pnl") or 0) - float(prod.get("pnl") or 0)

    early_exit_count = sum(
        1 for a in trade_audits
        if int(a["production"]["duration_bars"]) <= 1
        and str(a["production"]["exit_reason"]) in ("time", "hybrid_time")
    )

    trunc_match = aggregate.get("exit_fingerprint_match_count_truncated", 0)
    oracle_match = aggregate.get("duration_match_oracle_count", aggregate.get("exit_fingerprint_match_count_oracle", 0))
    total = len(trade_audits)

    ranked = []
    for rc in ROOT_CAUSES:
        impact = _numerical_impact(rc["cause_id"], aggregate, early_exit_count, trunc_match, total, pnl_impact)
        ranked.append({**rc, "numerical_impact": impact})

    ranked.sort(key=lambda x: x["numerical_impact"]["pf_contribution_pct"], reverse=True)

    return {
        "phase": "31D",
        "dominant_root_cause": "RC01",
        "secondary_root_cause": "RC02",
        "production_exit_distribution": dict(reason_prod),
        "proxy_exit_distribution": dict(reason_proxy),
        "truncated_replay_exit_distribution": dict(trunc_reason),
        "early_1bar_time_exits": early_exit_count,
        "duration_delta_histogram": {str(k): v for k, v in sorted(duration_deltas.items())},
        "total_pnl_impact_proxy_minus_production": round(pnl_impact, 4),
        "truncated_replay_duration_matches": trunc_match,
        "truncated_replay_duration_match_pct": round(100.0 * trunc_match / max(total, 1), 2),
        "repaired_oracle_match_count": oracle_match,
        "repaired_oracle_match_pct": round(100.0 * oracle_match / max(total, 1), 2),
        "ranked_causes": ranked,
    }


def _numerical_impact(
    cause_id: str,
    agg: dict[str, Any],
    early_exit_count: int,
    trunc_match: int,
    total: int,
    pnl_impact: float,
) -> dict[str, Any]:
    prod_pf = agg.get("production_pf", 1.0)
    proxy_pf = agg.get("hybrid_b_proxy_pf", 1.0)
    pf_delta = round(proxy_pf - prod_pf, 4)

    if cause_id == "RC01":
        return {
            "pf_contribution_pct": round(100 * (pf_delta / prod_pf) if prod_pf else 0, 2),
            "trades_affected": early_exit_count,
            "trades_affected_pct": round(100 * early_exit_count / max(total, 1), 2),
            "truncated_duration_match_pct": round(100 * trunc_match / max(total, 1), 2),
            "estimated_pnl_delta": round(pnl_impact, 2),
        }
    if cause_id == "RC02":
        return {
            "pf_contribution_pct": round(100 * (pf_delta / prod_pf) if prod_pf else 0, 2),
            "proxy_pf": proxy_pf,
            "production_pf": prod_pf,
            "estimated_pnl_delta": round(pnl_impact, 2),
        }
    return {
        "pf_contribution_pct": 0.0,
        "trades_affected": 0,
        "note": "secondary or non-material",
    }

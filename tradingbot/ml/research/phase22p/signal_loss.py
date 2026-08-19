"""Phase 22P — signal loss mapping and filter ranking."""

from __future__ import annotations

from collections import Counter
from typing import Any

import pandas as pd

from tradingbot.ml.research.phase14_4.pipeline_simulator import simulate_trade_outcome


def _module_for_block(reason: str) -> str:
    r = reason.lower()
    if "decision" in r or "calibration" in r or "engine_or_orchestrator" in r:
        return "Decision/Engine"
    if "risk" in r and "riskgate" not in r:
        return "AdaptiveRisk"
    if "quality" in r:
        return "TradeQuality"
    if "rsi" in r:
        return "RSI Filter (phase19c)"
    if "adx" in r:
        return "ADX Filter (phase19c)"
    if "meta" in r:
        return "MetaLabeler"
    if "riskgate" in r or reason in ("max positions for symbol", "daily loss limit"):
        return "RiskGate"
    if "htf" in r:
        return "HTF Confirmation"
    return reason.split(":")[0] if ":" in reason else reason


def build_signal_loss_map(
    *,
    hold_chain: dict[str, Any],
    blocked_events: list[dict],
    trace_records: list[dict],
    ohlcv: pd.DataFrame | None,
) -> dict[str, Any]:
    """Map non-traded signals to blocking module."""
    losses: list[dict] = []
    module_counts: Counter[str] = Counter()

    stages = hold_chain.get("ml_hold_stages") or {}
    stage_to_module = {
        "decision_hold": ("Decision/Engine", "tradingbot/ml/decision_engine/orchestrator.py"),
        "calibration_hold": ("Calibration", "tradingbot/ml/confidence_engine/validator.py"),
        "trade_quality_hold": ("TradeQuality", "tradingbot/ml/trade_quality/adapter.py"),
        "rsi_filter_hold": ("RSI Filter", "tradingbot/ml/phase19c/filters.py"),
        "adx_filter_hold": ("ADX Filter", "tradingbot/ml/phase19c/filters.py"),
    }
    for stage, count in stages.items():
        if count <= 0:
            continue
        mod, path = stage_to_module.get(stage, (stage, "unknown"))
        module_counts[mod] += count
        losses.append({
            "blocker_module": mod,
            "blocker_file": path,
            "stage": stage,
            "bars_blocked": count,
            "source": "hold_chain",
        })

    meta = int(hold_chain.get("meta_hold") or 0)
    if meta:
        module_counts["MetaLabeler"] += meta
        losses.append({
            "blocker_module": "MetaLabeler",
            "blocker_file": "tradingbot/services/meta_labeler.py",
            "stage": "meta_hold",
            "bars_blocked": meta,
            "source": "hold_chain",
        })

    rg = int(hold_chain.get("riskgate_hold") or 0)
    if rg:
        module_counts["RiskGate"] += rg
        reasons = hold_chain.get("riskgate_block_reasons") or {}
        losses.append({
            "blocker_module": "RiskGate",
            "blocker_file": "tradingbot/adapters/risk_gate.py",
            "stage": "riskgate_hold",
            "bars_blocked": rg,
            "reasons": reasons,
            "source": "hold_chain",
        })

    actionable_not_executed: list[dict] = []
    if trace_records:
        for rec in trace_records:
            if rec.get("error"):
                continue
            orch = rec.get("orchestrator_action")
            final = rec.get("final_direction")
            executed = rec.get("execution_decision") == "EXECUTE"
            if executed:
                continue
            raw_buy_sell = orch in ("BUY", "SELL")
            if not raw_buy_sell and final not in ("BUY", "SELL"):
                continue
            blockers = list(rec.get("block_reasons") or [])
            if not blockers and final == "HOLD":
                blockers = ["engine_or_orchestrator_hold"]
            for b in blockers:
                mod = _module_for_block(b)
                module_counts[mod] += 1
                actionable_not_executed.append({
                    "timestamp": rec.get("timestamp"),
                    "orchestrator_action": orch,
                    "calibrated_action": rec.get("calibrated_action"),
                    "final_direction": final,
                    "blocker_module": mod,
                    "block_reason": b,
                    "regime": rec.get("regime"),
                    "range_prob": rec.get("range_prob"),
                    "trend_prob": rec.get("trend_prob"),
                    "router_engine": rec.get("router_engine"),
                })

    missed_profitable = 0
    if ohlcv is not None and not ohlcv.empty and actionable_not_executed:
        ohlcv = ohlcv.copy()
        ohlcv.index = pd.to_datetime(ohlcv.index, utc=True)
        for item in actionable_not_executed[:500]:
            direction = item.get("orchestrator_action") or item.get("calibrated_action")
            if direction not in ("BUY", "SELL"):
                continue
            ts = pd.Timestamp(item.get("timestamp", ""))
            if ts is pd.NaT:
                continue
            idx = ohlcv.index.searchsorted(ts)
            if idx >= len(ohlcv) - 5:
                continue
            outcome = simulate_trade_outcome(ohlcv, idx, direction=direction)
            r = float(outcome.get("r_multiple", 0))
            item["forward_r_if_taken"] = round(r, 4)
            if r > 0:
                missed_profitable += 1

    return {
        "phase": "22P",
        "summary": {
            "hold_chain_bars_evaluated": hold_chain.get("bars_evaluated"),
            "ml_signals_emitted": hold_chain.get("ml_signals"),
            "buy_emitted": hold_chain.get("buy_emitted"),
            "sell_emitted": hold_chain.get("sell_emitted"),
            "total_module_blocks": dict(module_counts),
            "actionable_not_executed_traced": len(actionable_not_executed),
            "missed_profitable_among_traced": missed_profitable,
        },
        "hold_chain_losses": losses,
        "actionable_not_executed_sample": actionable_not_executed[:200],
    }


def rank_filter_effectiveness(
    *,
    hold_chain: dict[str, Any],
    backtest_metrics: dict[str, Any],
    blocked_events: list[dict],
    ohlcv: pd.DataFrame | None,
    baseline_trades: list[dict],
) -> dict[str, Any]:
    """Rank filters by real block count and counterfactual forward-R impact."""
    baseline_pf = backtest_metrics.get("profit_factor")
    baseline_dd = backtest_metrics.get("max_drawdown_pct")
    baseline_trades_n = len(baseline_trades)

    filters: list[dict[str, Any]] = []
    stages = hold_chain.get("ml_hold_stages") or {}
    rg_reasons = hold_chain.get("riskgate_block_reasons") or {}

    definitions = [
        ("decision_hold", "Decision/Engine Gate", "tradingbot/ml/decision_engine/decision_policy.py"),
        ("calibration_hold", "Calibration Gate", "tradingbot/ml/confidence_engine/validator.py"),
        ("trade_quality_hold", "Trade Quality Gate", "tradingbot/ml/trade_quality/adapter.py"),
        ("rsi_filter_hold", "RSI Filter", "tradingbot/ml/phase19c/filters.py"),
        ("adx_filter_hold", "ADX Filter", "tradingbot/ml/phase19c/filters.py"),
    ]
    for key, name, path in definitions:
        blocks = int(stages.get(key) or 0)
        filters.append(_filter_row(name, path, blocks, blocked_events, ohlcv, baseline_pf, baseline_dd))

    meta_blocks = int(hold_chain.get("meta_hold") or 0)
    filters.append(_filter_row(
        "MetaLabeler", "tradingbot/services/meta_labeler.py", meta_blocks,
        blocked_events, ohlcv, baseline_pf, baseline_dd,
    ))

    rg_total = int(hold_chain.get("riskgate_hold") or 0)
    filters.append(_filter_row(
        "RiskGate (all)", "tradingbot/adapters/risk_gate.py", rg_total,
        [e for e in blocked_events if e.get("stage") == "riskgate"],
        ohlcv, baseline_pf, baseline_dd,
        extra={"reasons": rg_reasons},
    ))

    for reason, count in rg_reasons.items():
        filters.append(_filter_row(
            f"RiskGate:{reason}", "tradingbot/adapters/risk_gate.py", count,
            [e for e in blocked_events if reason in str(e.get("reason", ""))],
            ohlcv, baseline_pf, baseline_dd,
        ))

    filters.sort(key=lambda x: x["signals_removed"], reverse=True)

    for f in filters:
        blocks = f["signals_removed"]
        pos_r = f.get("blocked_positive_forward_r", 0)
        if blocks == 0:
            f["verdict"] = "inactive"
        elif blocks > 100 and pos_r == 0 and baseline_pf is not None and baseline_pf <= 1.0:
            f["verdict"] = "low_value_blocker"
        elif blocks < 50 and pos_r > 5:
            f["verdict"] = "potentially_harmful"
        elif blocks > 0 and pos_r == 0:
            f["verdict"] = "blocks_losing_or_neutral"
        else:
            f["verdict"] = "mixed"

    return {
        "phase": "22P",
        "baseline": {
            "profit_factor": baseline_pf,
            "max_drawdown_pct": baseline_dd,
            "trades": baseline_trades_n,
        },
        "ranked_filters": filters,
        "method": "hold_chain counts + forward-R on blocked_events sample (no threshold changes)",
    }


def _filter_row(
    name: str,
    path: str,
    blocks: int,
    events: list[dict],
    ohlcv: pd.DataFrame | None,
    baseline_pf: float | None,
    baseline_dd: float | None,
    *,
    extra: dict | None = None,
) -> dict[str, Any]:
    pos_r = 0
    neg_r = 0
    checked = 0
    if ohlcv is not None and not ohlcv.empty and events:
        ohlcv = ohlcv.copy()
        ohlcv.index = pd.to_datetime(ohlcv.index, utc=True)
        for ev in events[:300]:
            direction = ev.get("direction", "")
            if direction not in ("BUY", "SELL", "?"):
                if direction in ("Buy", "SELL"):
                    direction = direction.upper()
                else:
                    continue
            ts = pd.Timestamp(ev.get("timestamp", ""))
            if ts is pd.NaT or not str(ts):
                continue
            idx = ohlcv.index.searchsorted(ts)
            if idx >= len(ohlcv) - 5:
                continue
            outcome = simulate_trade_outcome(ohlcv, idx, direction=direction if direction != "?" else "BUY")
            r = float(outcome.get("r_multiple", 0))
            checked += 1
            if r > 0:
                pos_r += 1
            elif r < 0:
                neg_r += 1

    row = {
        "filter": name,
        "file": path,
        "signals_removed": blocks,
        "blocked_events_sampled": checked,
        "blocked_positive_forward_r": pos_r,
        "blocked_negative_forward_r": neg_r,
        "pf_after_removal": baseline_pf,
        "pf_change": 0.0,
        "dd_after_removal": baseline_dd,
        "note": "PF unchanged in forensics — no filter disabled; forward-R estimates only",
    }
    if extra:
        row.update(extra)
    return row

"""Phase 22F — signal bottleneck funnel map."""

from __future__ import annotations

from typing import Any


def build_bottleneck_map(baseline_by_tf: dict[str, dict]) -> dict[str, Any]:
    per_tf = {}
    combined_blocks: dict[str, int] = {}
    total_bars = 0

    for tf, result in baseline_by_tf.items():
        hc = result.get("hold_chain") or {}
        trace = result.get("trace") or {}
        bars = hc.get("bars_evaluated", 0)
        total_bars += bars
        stages = hc.get("ml_hold_stages") or {}

        funnel_stages = [
            ("bars", bars),
            ("signals_emitted", hc.get("buy_emitted", 0) + hc.get("sell_emitted", 0)),
            ("decision_pass", bars - stages.get("decision_hold", 0)),
            ("calibration_pass", bars - stages.get("decision_hold", 0) - stages.get("calibration_hold", 0)),
            ("trade_quality_pass", bars - stages.get("decision_hold", 0) - stages.get("calibration_hold", 0) - stages.get("trade_quality_hold", 0)),
            ("rsi_pass", bars - stages.get("decision_hold", 0) - stages.get("calibration_hold", 0) - stages.get("trade_quality_hold", 0) - stages.get("rsi_filter_hold", 0)),
            ("adx_pass", bars - sum(stages.values())),
            ("meta_pass", bars - sum(stages.values()) - hc.get("meta_hold", 0)),
            ("riskgate_reached", result.get("summary", {}).get("signals_reaching_riskgate", 0)),
            ("riskgate_pass", result.get("summary", {}).get("signals_reaching_riskgate", 0) - result.get("summary", {}).get("signals_blocked_riskgate", 0)),
            ("executed", result.get("trades", 0)),
        ]

        flow = []
        prev = bars
        for name, count in funnel_stages[1:]:
            lost = max(0, prev - count) if name not in ("signals_emitted",) else max(0, bars - count)
            if name == "signals_emitted":
                lost = max(0, bars - count)
            pct_lost = round(lost / max(prev if name != "signals_emitted" else bars, 1) * 100, 3)
            flow.append({"stage": name, "count": count, "lost_from_prev": lost, "lost_pct": pct_lost})
            if name != "signals_emitted":
                prev = count
            combined_blocks[name] = combined_blocks.get(name, 0) + lost

        per_tf[tf] = {
            "bars": bars,
            "funnel": flow,
            "trace_funnel": trace.get("funnel"),
            "riskgate_block_reasons": hc.get("riskgate_block_reasons", {}),
        }

    return {
        "phase": "22F",
        "pipeline": "Bars->Signals->Model->Calibration->TradeQuality->RSI->ADX->Meta->RiskGate->Execution",
        "total_bars": total_bars,
        "per_timeframe": per_tf,
        "combined_stage_losses": combined_blocks,
    }

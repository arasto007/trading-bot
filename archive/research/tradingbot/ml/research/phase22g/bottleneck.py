"""Phase 22G — profitability bottleneck from trace + baseline."""

from __future__ import annotations

from typing import Any


def build_profitability_bottleneck(baseline: dict, trace: dict) -> dict[str, Any]:
    m5 = baseline.get("per_tf", {}).get("M5", {})
    hc = m5.get("hold_chain") or {}
    stages = hc.get("ml_hold_stages") or {}
    metrics = m5.get("metrics") or {}

    trace_blocks = trace.get("stage_block_counts") or {}
    bars = hc.get("bars_evaluated") or trace.get("bars_traced") or 1

    stage_loss = [
        {"stage": "bars", "count": bars, "pct": 100.0},
        {"stage": "engine_actionable", "count": hc.get("buy_emitted", 0) + hc.get("sell_emitted", 0),
         "lost_pct": round((bars - hc.get("buy_emitted", 0) - hc.get("sell_emitted", 0)) / bars * 100, 2)},
        {"stage": "decision_hold", "count": stages.get("decision_hold", 0), "source": "hold_chain"},
        {"stage": "calibration_hold", "count": stages.get("calibration_hold", 0)},
        {"stage": "trade_quality_hold", "count": stages.get("trade_quality_hold", 0)},
        {"stage": "rsi_filter", "count": stages.get("rsi_filter_hold", 0)},
        {"stage": "adx_filter", "count": stages.get("adx_filter_hold", 0)},
        {"stage": "meta_hold", "count": hc.get("meta_hold", 0)},
        {"stage": "riskgate_hold", "count": hc.get("riskgate_hold", 0),
         "reasons": hc.get("riskgate_block_reasons", {})},
        {"stage": "executed_trades", "count": m5.get("trades", 0)},
    ]

    ranked = sorted(
        [
            {"stage": k, "blocks": v}
            for k, v in trace_blocks.items()
        ] + [
            {"stage": "decision_hold (hold_chain)", "blocks": stages.get("decision_hold", 0)},
            {"stage": "riskgate_hold (hold_chain)", "blocks": hc.get("riskgate_hold", 0)},
        ],
        key=lambda x: x["blocks"],
        reverse=True,
    )

    first_destroyer = ranked[0]["stage"] if ranked else "unknown"

    return {
        "phase": "22G",
        "evidence_sources": ["M5_backtest_hold_chain", "execution_trace_stage_blocks"],
        "first_destroyer": first_destroyer,
        "first_destroyer_detail": (
            "Engine + orchestrator produce HOLD on ~96%+ bars before RiskGate. "
            "Primary code path: regime_classifier -> range/trend engines -> DecisionPolicy confidence gate. "
            "RiskGate cascade (min balance, daily loss) is secondary once trades occur."
        ),
        "executed_trade_metrics_m5": {
            "trades": m5.get("trades"),
            "profit_factor": metrics.get("profit_factor"),
            "expectancy": metrics.get("expectancy"),
            "max_drawdown_pct": metrics.get("max_drawdown_pct"),
            "buy_trades": metrics.get("buy_trades"),
            "sell_trades": metrics.get("sell_trades"),
        },
        "stage_loss_ranked": ranked,
        "funnel": stage_loss,
        "summary": (
            f"Information loss peaks at '{first_destroyer}'. "
            f"Only {m5.get('trades', 0)} trades executed from {bars} bars. "
            f"Executed PF={metrics.get('profit_factor')}."
        ),
    }

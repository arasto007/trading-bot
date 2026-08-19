"""Phase 30A — execution pipeline audit (read-only)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def build_execution_pipeline_map() -> dict[str, Any]:
    return {
        "phase": "30A",
        "title": "Execution Pipeline Map",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "production_modified": False,
        "pipeline": [
            {"step": 1, "stage": "Signal", "component": "SignalStage / ML Kernel", "file": "tradingbot/pipeline/signal_stage.py", "output": "TradingSignal"},
            {"step": 2, "stage": "SignalFilter", "component": "SignalFilterStage (WPSQF)", "file": "tradingbot/pipeline/signal_filter_stage.py", "optional": True},
            {"step": 3, "stage": "RiskGate", "component": "RiskStage → RiskGate.evaluate", "file": "tradingbot/pipeline/risk_stage.py", "output": "RiskDecision"},
            {"step": 4, "stage": "ExecutionAdapter", "component": "ExecutionStage → Mt5ExecutionAdapter", "file": "tradingbot/adapters/mt5_execution.py", "output": "ExecutionResult"},
            {"step": 5, "stage": "PaperTradeRecorder", "component": "PaperTradeRecorder.record_entry", "file": "tradingbot/services/paper_trade_recorder.py", "modes": ["paper"]},
            {"step": 6, "stage": "AccountingEngine", "component": "AccountingEngine.close_trade", "file": "tradingbot/accounting/engine.py", "optional": True},
            {"step": 7, "stage": "Journal", "component": "TradeJournal", "file": "tradingbot/services/trade_journal.py", "tables": ["executions", "paper_trades", "cycle_events"]},
        ],
        "flow_diagram": "Signal → [WPSQF] → RiskGate → ExecutionAdapter → PaperTradeRecorder → AccountingEngine → Journal",
        "ideal_assumptions": [
            {
                "category": "Paper fills",
                "assumption": "Fixed spread 0.30 points",
                "evidence": "tradingbot/ml/paper_trading/paper_broker.py BrokerConfig.spread_points=0.30",
                "severity": "high",
            },
            {
                "category": "Paper fills",
                "assumption": "Fixed slippage 0.10 points on entry",
                "evidence": "paper_broker.py BrokerConfig.slippage_points=0.10",
                "severity": "high",
            },
            {
                "category": "Paper fills",
                "assumption": "Instant 100% fill — no partial fills or queue",
                "evidence": "paper_broker.execute_entry returns immediate FillResult",
                "severity": "high",
            },
            {
                "category": "Paper fills",
                "assumption": "Zero slippage logged to journal",
                "evidence": "paper_trade_recorder.py log_execution slippage_pips=0.0",
                "severity": "medium",
            },
            {
                "category": "Paper fills",
                "assumption": "Zero commission and swap",
                "evidence": "paper_broker.py commission=0.0; paper_trade_recorder swap=0.0",
                "severity": "medium",
            },
            {
                "category": "Exit simulation",
                "assumption": "Bar-level OHLC exits — no tick path",
                "evidence": "exit_policy.py bar walk-forward",
                "severity": "high",
            },
            {
                "category": "Exit simulation",
                "assumption": "SL resolved before TP on same bar (pessimistic)",
                "evidence": "paper_broker.py resolve_bar docstring",
                "severity": "medium",
            },
            {
                "category": "Latency",
                "assumption": "Zero execution delay",
                "evidence": "No latency model in production execution path",
                "severity": "high",
            },
            {
                "category": "Liquidity",
                "assumption": "Unlimited liquidity at requested lot",
                "evidence": "No liquidity cap in paper fill resolver",
                "severity": "high",
            },
            {
                "category": "Market impact",
                "assumption": "No market impact from order size",
                "evidence": "Fill price independent of lot size in paper_broker",
                "severity": "medium",
            },
            {
                "category": "Live execution",
                "assumption": "Market order max deviation 20 points",
                "evidence": "mt5_execution.py _DEVIATION=20",
                "severity": "low",
            },
            {
                "category": "Accounting",
                "assumption": "AccountingEngine optional in default paper path",
                "evidence": "paper_trade_recorder accounting=None by default",
                "severity": "medium",
            },
        ],
        "phase30a_scope": {
            "builds": "tradingbot/execution/* simulation layer",
            "does_not_modify": [
                "ML Kernel", "Models", "Feature Engineering", "Entry Logic",
                "WPSQF", "Hybrid B", "RiskGate", "Accounting Engine",
                "Journal", "Replay Portfolio",
            ],
        },
    }

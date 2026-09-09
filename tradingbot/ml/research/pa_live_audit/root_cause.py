"""Phase 1.5.59 — ranked live-failure / parity findings from repository evidence only."""

from __future__ import annotations

from typing import Any

CRITICAL = "CRITICAL"
HIGH = "HIGH"
MEDIUM = "MEDIUM"
LOW = "LOW"
UNKNOWN = "UNKNOWN"


def root_cause_findings() -> list[dict[str, Any]]:
    return [
        {
            "id": "symbol_identity",
            "title": "Research/backtest XAUUSD vs live XAUUSD_i identity unproven",
            "severity": HIGH,
            "evidence": (
                "PRIMARY_SYMBOL=XAUUSD_i; candles are XAUUSD; no XAUUSD_i parquet; "
                "order_value diverges 1000× (1.5.52). Not invented."
            ),
            "maps_to": ["symbol mismatch", "data mismatch"],
        },
        {
            "id": "cost_tape",
            "title": "No class-A round-trip cost tape",
            "severity": HIGH,
            "evidence": (
                "Empty spread/tick stores; 17 live entry slips only; paper spread 0.30; "
                "backtest 2.5/0.8 pips assumed (1.5.51–55)."
            ),
            "maps_to": ["spread/slippage", "execution mismatch"],
        },
        {
            "id": "backtest_default_tf",
            "title": "BacktestConfig default timeframe is M1, live is M5",
            "severity": HIGH,
            "evidence": "tradingbot/backtest/config.py timeframe='M1'; get_live_config TIMEFRAMES=['5m']",
            "maps_to": ["signal mismatch", "timing/latency"],
        },
        {
            "id": "execution_model",
            "title": "Bar first-touch / assumed fill vs Mt5ExecutionAdapter",
            "severity": HIGH,
            "evidence": "Live fills from MT5; research uses close/high/low; SimulatedBroker uses assumed spread",
            "maps_to": ["execution mismatch", "candle-close assumptions"],
        },
        {
            "id": "position_management",
            "title": "Backtest defaults enable trailing/partial/zscore/EOD; live M5 partial TP is off",
            "severity": MEDIUM,
            "evidence": "BacktestConfig enable_partial_tp/trailing/zscore True; M5 preset ENABLE_PARTIAL_TP=False",
            "maps_to": ["execution mismatch"],
        },
        {
            "id": "meta_gating",
            "title": "Meta-labeler can reject PA live; continuous enforcement not proven",
            "severity": MEDIUM,
            "evidence": "risk_gate.py apply_pa_meta_decision; ML_STATUS continuous enforcement NOT PROVEN",
            "maps_to": ["signal mismatch", "overtrading"],
        },
        {
            "id": "spread_fail_closed",
            "title": "Missing live tick → spread 999 → reject",
            "severity": MEDIUM,
            "evidence": "RiskGate._live_spread_pips except/None → 999.0; check_spread_gate",
            "maps_to": ["order rejection", "spread/slippage"],
        },
        {
            "id": "research_lookahead",
            "title": "Some research scripts enrich the full frame (swing right=3 uses future bars)",
            "severity": MEDIUM,
            "evidence": "find_swings uses i+right; live enrich at last index only",
            "maps_to": ["look-ahead", "indicator warmup"],
        },
        {
            "id": "atr_proxy",
            "title": "Some research fast scripts use (high-low) rolling mean as ATR",
            "severity": MEDIUM,
            "evidence": "scripts/phase14b2_pa_hold_replay_fast.py",
            "maps_to": ["data mismatch"],
        },
        {
            "id": "demo_session_bypass",
            "title": "DEMO_DISABLE_SESSION_FILTER can disable NY 15–16 live",
            "severity": MEDIUM,
            "evidence": "filter_policy.py + live.py; operator .env not inspected",
            "maps_to": ["session/timezone handling", "overtrading"],
        },
        {
            "id": "dedup_in_memory",
            "title": "PA dedup cache is process-local; lost on restart",
            "severity": LOW,
            "evidence": "pa_hardening._DEDUP dict; clear_pa_dedup_cache",
            "maps_to": ["duplicate signals", "restart behavior", "state persistence"],
        },
        {
            "id": "live_sample",
            "title": "Only 17 live journal fills — cannot prove live PA expectancy",
            "severity": HIGH,
            "evidence": "data/trade_journal.db mode=live n=17; entry slip only; not TREND-v41 and not a PA OOS book",
            "maps_to": ["journal mismatch", "logging mismatch"],
        },
        {
            "id": "partial_fills",
            "title": "Partial-fill / rejection rates",
            "severity": UNKNOWN,
            "evidence": "No trustworthy fill-quality tape in repo (phase20c count=0)",
            "maps_to": ["partial fills", "order rejection"],
        },
        {
            "id": "latency",
            "title": "Signal-to-fill latency as a cause of live underperformance",
            "severity": UNKNOWN,
            "evidence": "PIPELINE_TIMEOUT_MS=500 documented; no measured PA latency tape used here",
            "maps_to": ["timing/latency"],
        },
        {
            "id": "position_state_bugs",
            "title": "Position-state bugs as proven live-loss cause",
            "severity": UNKNOWN,
            "evidence": "Not demonstrated from this audit's sources",
            "maps_to": ["position-state bugs"],
        },
    ]

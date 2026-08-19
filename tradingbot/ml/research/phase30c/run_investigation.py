"""Phase 30C — Digital Broker Twin research (design only, no code changes)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[4]
PHASE_DIR = Path(__file__).resolve().parent
PHASE30A = PROJECT_ROOT / "tradingbot" / "ml" / "research" / "phase30a"
PHASE30B = PROJECT_ROOT / "tradingbot" / "ml" / "research" / "phase30b"
PHASE29B = PROJECT_ROOT / "tradingbot" / "ml" / "research" / "phase29b" / "_cache" / "wpsqf" / "replay_meta.json"

VERDICTS = {"DIGITAL_BROKER_MODEL_COMPLETE", "MORE_BROKER_RESEARCH_REQUIRED"}


def _write(name: str, payload: dict[str, Any]) -> None:
    (PHASE_DIR / name).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _load(path: Path) -> dict[str, Any]:
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _gap(
    component: str,
    *,
    current: str,
    real_broker: str,
    difference: str,
    risk: str,
    pf: str,
    dd: str,
    exp: str,
    confidence: int,
    sources: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "component": component,
        "current_implementation": current,
        "real_broker_behavior": real_broker,
        "difference": difference,
        "risk": risk,
        "expected_impact": {
            "profit_factor": pf,
            "drawdown": dd,
            "expectancy": exp,
        },
        "confidence": confidence,
        "evidence_sources": sources or [],
    }


def build_broker_component_audit(perf: dict, stress: dict) -> dict[str, Any]:
    ideal_pf = perf.get("ideal_execution", {}).get("profit_factor", 1.211)
    sim_pf = perf.get("simulated_normal_execution", {}).get("profit_factor", 1.049)
    components = [
        _gap(
            "Bid/Ask Stream",
            current="Paper: single price + fixed half-spread; Live: mt5.symbol_info_tick bid/ask at send time only",
            real_broker="Continuous bid/ask tick stream; ask>=bid; spread varies tick-to-tick; last tick may be stale",
            difference="No tick history stored; paper often uses candle close not live bid/ask",
            risk="HIGH — fill price may not match any real tick at decision time",
            pf="HIGH — contributes to ideal→sim PF gap",
            dd="MEDIUM",
            exp="HIGH",
            confidence=88,
            sources=["paper_fill_resolver.py", "mt5_execution.py _current_price"],
        ),
        _gap(
            "Tick-by-Tick Spread",
            current="Fixed spread_points=0.30 (PaperBroker); Phase30A session multipliers research-only",
            real_broker="Spread dynamic per tick; XAUUSD retail 20–150+ points intraday",
            difference="Production spread static; no tick-level spread series",
            risk="CRITICAL",
            pf=f"HIGH — PF {ideal_pf}→{sim_pf} when modelled; breaking 1.5× multiplier",
            dd="HIGH — DD 24%→38% normal sim",
            exp="HIGH",
            confidence=92,
            sources=["phase30a/performance_comparison.json", "paper_broker.py"],
        ),
        _gap(
            "Spread Expansion (Volatility)",
            current="Phase30A: atr_percentile scales spread; production: none",
            real_broker="Spread widens proportionally with volatility and order flow imbalance",
            difference="Volatility-spread coupling absent in production",
            risk="HIGH during news/fast markets",
            pf="MEDIUM-HIGH in tails",
            dd="HIGH in flash crash stress PF=0.58",
            exp="MEDIUM",
            confidence=85,
            sources=["execution_costs.py vol_mult", "phase30a/stress_tests.json"],
        ),
        _gap(
            "Session Spread",
            current="Phase30A Asian 1.35× London 1.0× Overlap 0.85×; production: flat",
            real_broker="Asian gold spread often 2–3× overlap; Sunday open extreme",
            difference="Session not modelled in production path",
            risk="MEDIUM — M5 strategy crosses sessions",
            pf="MEDIUM",
            dd="MEDIUM",
            exp="MEDIUM",
            confidence=80,
            sources=["execution_costs.py SESSION_SPREAD_MULT"],
        ),
        _gap(
            "News Spread",
            current="Phase30A flag is_news_window ×1.8 spread; no calendar in production",
            real_broker="NFP/FOMC: spread 5–20×; fills delayed/requoted",
            difference="No economic calendar integration",
            risk="CRITICAL on event days",
            pf="CRITICAL — news stress PF=0.73",
            dd="CRITICAL",
            exp="CRITICAL",
            confidence=86,
            sources=["phase30a/stress_tests.json news"],
        ),
        _gap(
            "Weekend Spread / Gap",
            current="Phase30A weekend scenario; production bar exit at exact levels",
            real_broker="Friday close / Sunday open gap; widened spread; SL gap-through",
            difference="No weekend open modelling in production",
            risk="HIGH for held positions",
            pf="HIGH — weekend stress PF=0.68",
            dd="CRITICAL",
            exp="HIGH",
            confidence=82,
            sources=["phase30a/stress_tests.json weekend"],
        ),
        _gap(
            "Liquidity / Order Book",
            current="Phase30A scalar liquidity_score; production unlimited at min lot",
            real_broker="Depth at bid/ask; thin book off-hours; last-look on MM",
            difference="No L2 approximation; no broker last-look",
            risk="MEDIUM at 0.01 lot; HIGH at size",
            pf="MEDIUM — partial fill 22.9% in sim may overstate min lot",
            dd="MEDIUM",
            exp="MEDIUM",
            confidence=75,
            sources=["liquidity_model.py", "phase30a fill_stats"],
        ),
        _gap(
            "Fill Probability",
            current="Paper: fill if price resolved; Live: market order with deviation 20",
            real_broker="FOK/IOC/RETURN modes; partial reject; off-quotes; margin reject",
            difference="Paper never rejects except unresolved price",
            risk="MEDIUM",
            pf="LOW-MEDIUM",
            dd="LOW",
            exp="LOW",
            confidence=78,
            sources=["mt5_execution.py", "fill_model.py"],
        ),
        _gap(
            "Partial Fills",
            current="Phase30A discrete ratios; production 100% fill",
            real_broker="Common on limits; rare on small market XAUUSD ECN",
            difference="Simulator may over-penalize 0.01 lot",
            risk="LOW at current sizing",
            pf="LOW-MEDIUM",
            dd="LOW",
            exp="LOW-MEDIUM",
            confidence=72,
            sources=["fill_model.py"],
        ),
        _gap(
            "Market Impact",
            current="Phase30A linear impact from lot/ATR; negligible at 0.01 lot",
            real_broker="Square-root impact; walks book on size",
            difference="Minimal at min lot; model inactive in production",
            risk="LOW now; HIGH if sizing increases",
            pf="NEGLIGIBLE at 0.01",
            dd="LOW",
            exp="NEGLIGIBLE",
            confidence=88,
            sources=["market_impact.py", "phase30a breaking points impact sweep"],
        ),
        _gap(
            "Entry Slippage",
            current="Paper: +0.10 points fixed; Live: measured post-fill; journal paper=0",
            real_broker="Fat-tailed; worse in volatility; can be positive (price improvement)",
            difference="Hidden in paper journal; not session-varying",
            risk="HIGH",
            pf="MEDIUM — slippage break 7× vs spread 1.5×",
            dd="MEDIUM",
            exp="MEDIUM",
            confidence=85,
            sources=["paper_broker.py", "paper_trade_recorder.py"],
        ),
        _gap(
            "Exit Slippage",
            current="Production: exact TP/SL/bar close; Phase30A sim applies slip on exit replay",
            real_broker="SL/TP hit with slip; stop hunting; gap through level",
            difference="CRITICAL optimism in production exit path",
            risk="CRITICAL",
            pf="CRITICAL — ~30% of PF loss share (phase30b rank 2)",
            dd="HIGH",
            exp="CRITICAL",
            confidence=94,
            sources=["exit_policy.py", "phase30b root cause rank 2"],
        ),
        _gap(
            "Gap Through Stop",
            current="Bar SL at exact stop_loss price (pessimistic ordering vs TP same bar)",
            real_broker="Price gaps through SL especially weekend/news; slip beyond SL",
            difference="No gap-through modelling in production",
            risk="CRITICAL tail",
            pf="HIGH in tail events",
            dd="CRITICAL",
            exp="HIGH",
            confidence=83,
            sources=["paper_broker resolve_bar", "fill_model price_gap"],
        ),
        _gap(
            "Gap Through TP",
            current="Exact TP fill at take_profit level on bar touch",
            real_broker="Positive gap may overshoot TP; limit fill better than stop",
            difference="Optimistic TP fills; no overshoot capture variance",
            risk="LOW-MEDIUM",
            pf="LOW optimistic bias",
            dd="LOW",
            exp="LOW optimistic",
            confidence=70,
            sources=["exit_policy.py"],
        ),
        _gap(
            "Latency (All Components)",
            current="Phase30A Gaussian sum ~80ms mean; NOT applied to price; production instant",
            real_broker="50–500ms retail; co-located lower; price moves during delay",
            difference="Latency decorative in Phase30A replay PnL",
            risk="MEDIUM M5 bar boundary races",
            pf="NONE in current sim sweeps",
            dd="NONE",
            exp="NONE until coupled",
            confidence=95,
            sources=["execution_latency.py", "phase30a breaking points delay sweep"],
        ),
        _gap(
            "Latency → Price Coupling",
            current="NOT IMPLEMENTED anywhere",
            real_broker="Fill price = f(tick_stream, t + latency); drift proportional to vol×√time",
            difference="CRITICAL missing causal link",
            risk="HIGH — understates fast market cost",
            pf="UNKNOWN — estimated MEDIUM when implemented",
            dd="MEDIUM",
            exp="MEDIUM",
            confidence=80,
            sources=["phase30b missing_features"],
        ),
        _gap(
            "Queue / Broker Processing Delay",
            current="Phase30A exponential queue delay; MT5 retry sleep 0.5s once",
            real_broker="Broker internal matching queue; multi-second during news",
            difference="Minimal production modelling",
            risk="MEDIUM",
            pf="LOW in replay",
            dd="LOW",
            exp="LOW",
            confidence=68,
            sources=["order_queue.py", "mt5_execution _order_send_with_retry"],
        ),
        _gap(
            "Network Delay",
            current="Phase30A component 10–30ms; unmodelled production",
            real_broker="Geo-dependent RTT; jitter spikes",
            difference="Only in research sim score not PnL",
            risk="LOW-MEDIUM",
            pf="LOW until coupled",
            dd="LOW",
            exp="LOW",
            confidence=75,
            sources=["execution_latency.py"],
        ),
        _gap(
            "Price Improvement",
            current="Phase30A positive slippage prob ~10–15%; production paper none",
            real_broker="Occasional better fill on market orders; MM dependent",
            difference="Paper always adverse half-spread + slip",
            risk="LOW — slight pessimism in paper entry",
            pf="LOW optimistic bias in paper",
            dd="LOW",
            exp="LOW",
            confidence=65,
            sources=["execution_costs slippage_probability"],
        ),
        _gap(
            "Requotes",
            current="Phase30A 2% prob widen spread; MT5 retry codes 10004 etc once",
            real_broker="Requote loops; trader accepts worse or cancels",
            difference="Single retry insufficient for full requote chain",
            risk="MEDIUM",
            pf="LOW-MEDIUM",
            dd="LOW",
            exp="LOW",
            confidence=72,
            sources=["fill_model should_requote", "mt5_execution _RETRY_CODES"],
        ),
        _gap(
            "Minimum Distance / Freeze Level",
            current="NOT IMPLEMENTED — SL/TP sent without stops_level/freeze_level validation",
            real_broker="symbol_info.stops_level freeze_level block modify/place near price",
            difference="Orders may be rejected live but pass paper",
            risk="MEDIUM live reject",
            pf="LOW — fewer trades if enforced",
            dd="LOW",
            exp="LOW",
            confidence=60,
            sources=["mt5_execution request dict — no stops_level check in codebase grep"],
        ),
        _gap(
            "Tick Size / Price Precision",
            current="BrokerConstraints tick_size 0.01 gold; fills rounded 5–6 dp in exit_policy",
            real_broker="symbol_info.digits point tick_size strict rounding",
            difference="Partial — constraints exist but not enforced on every fill path",
            risk="LOW",
            pf="NEGLIGIBLE",
            dd="NEGLIGIBLE",
            exp="NEGLIGIBLE",
            confidence=82,
            sources=["broker_constraints.py"],
        ),
        _gap(
            "Minimum Lot / Lot Step",
            current="min_lot=0.01 step=0.01 clamp in BrokerConstraints + position_sizing",
            real_broker="Broker-specific; volume_min volume_step volume_max",
            difference="Static defaults not loaded from symbol_info at runtime in paper",
            risk="LOW for XAUUSD standard",
            pf="LOW",
            dd="LOW",
            exp="LOW",
            confidence=85,
            sources=["broker_constraints.py", "accounting/position_sizing.py"],
        ),
        _gap(
            "Margin Calculation",
            current="margin = lot×contract×price/leverage; leverage fixed 100",
            real_broker="MT5 order_calc_margin; hedging vs netting; symbol margin_initial",
            difference="Simplified; no hedged margin discount",
            risk="MEDIUM if multiple positions",
            pf="LOW",
            dd="MEDIUM if margin call unmodelled",
            exp="LOW",
            confidence=78,
            sources=["broker_constraints.margin_required"],
        ),
        _gap(
            "Margin Call / Stop Out",
            current="NOT IMPLEMENTED",
            real_broker="Stop out at margin_level 20–50%; forced close worst positions",
            difference="Complete absence — replay never liquidated",
            risk="HIGH live tail not in backtest",
            pf="LOW until extreme leverage",
            dd="UNDERSTATES tail",
            exp="N/A",
            confidence=85,
            sources=["phase30b missing margin stop-out"],
        ),
        _gap(
            "Swap",
            current="swap=0.0 in paper_trade_recorder",
            real_broker="Triple swap Wed; long/short rates; affects hold >24h",
            difference="Zero overnight carry in all paper/replay",
            risk="MEDIUM multi-day holds (max 72 bars M5 ≈ 6h — limited)",
            pf="LOW for current hold horizon",
            dd="LOW",
            exp="LOW per trade",
            confidence=80,
            sources=["paper_trade_recorder.py", "exit_policy DEFAULT_MAX_HOLD_BARS=72"],
        ),
        _gap(
            "Commission",
            current="commission=0.0 PaperBroker and journal",
            real_broker="Per-lot or per-million; ECN raw spread + commission",
            difference="Absent",
            risk="LOW if spread includes markup",
            pf="LOW-MEDIUM cumulative",
            dd="LOW",
            exp="LOW",
            confidence=82,
            sources=["paper_broker.py"],
        ),
        _gap(
            "Execution Rejection / Off Quotes",
            current="Paper: unresolved price only; Live: retcode failures logged",
            real_broker="TRADE_RETCODE_OFF_QUOTES REJECT NO_MONEY MARKET_CLOSED",
            difference="No rejection taxonomy in paper/replay",
            risk="MEDIUM",
            pf="LOW — missed trades",
            dd="LOW",
            exp="LOW",
            confidence=70,
            sources=["mt5_execution.py retcode handling"],
        ),
        _gap(
            "Trade Context Busy",
            current="guarded_order_send wrapper; single retry",
            real_broker="TRADE_CONTEXT_BUSY common under load; exponential backoff",
            difference="Minimal retry policy",
            risk="LOW-MEDIUM",
            pf="LOW",
            dd="LOW",
            exp="LOW",
            confidence=65,
            sources=["mt5_order_guard.py"],
        ),
    ]
    return {
        "phase": "30C",
        "audit_type": "digital_broker_twin_forensic",
        "component_count": len(components),
        "components": components,
        "reference_metrics": {
            "phase29b_ideal_pf": ideal_pf,
            "phase30a_sim_normal_pf": sim_pf,
            "high_spread_stress_pf": stress.get("scenarios", {}).get("high_spread", {}).get("performance", {}).get("profit_factor"),
            "flash_crash_pf": stress.get("scenarios", {}).get("flash_crash", {}).get("performance", {}).get("profit_factor"),
        },
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_digital_broker_architecture() -> dict[str, Any]:
    return {
        "phase": "30C",
        "name": "Digital Broker Twin (DBT)",
        "objective": "Replay and paper paths consume identical broker physics as live MT5 without modifying signal/risk/exit logic",
        "design_principle": "Replace execution adapter internals with DBT; keep IOrderExecutor interface stable",
        "modules": [
            {
                "id": "dbt.core",
                "name": "BrokerTwinEngine",
                "responsibility": "Orchestrate order lifecycle: accept → validate → queue → fill → report",
                "inputs": ["OrderRequest", "MarketSnapshot", "BrokerProfile"],
                "outputs": ["FillReport", "RejectReport"],
            },
            {
                "id": "dbt.market",
                "name": "MarketDataFeed",
                "responsibility": "Bid/ask tick stream or synthetic from candles+ticks",
                "inputs": ["TickStore", "CandleStore", "live MT5 tick optional"],
                "outputs": ["QuoteStream"],
            },
            {
                "id": "dbt.spread",
                "name": "SpreadEngine",
                "responsibility": "Tick spread from session/vol/news/weekend profiles",
                "inputs": ["QuoteStream", "SessionCalendar", "VolatilityState"],
                "outputs": ["EffectiveSpread"],
            },
            {
                "id": "dbt.slippage",
                "name": "SlippageEngine",
                "responsibility": "Entry/exit implementation shortfall distribution",
                "inputs": ["OrderRequest", "EffectiveSpread", "LiquidityState", "LatencyDraw"],
                "outputs": ["SlippagePoints", "PriceImprovementFlag"],
            },
            {
                "id": "dbt.liquidity",
                "name": "LiquidityBook",
                "responsibility": "Approximate depth curve; max fillable lot",
                "inputs": ["SymbolProfile", "Session", "VolatilityState"],
                "outputs": ["DepthCurve", "FillCap"],
            },
            {
                "id": "dbt.fill",
                "name": "FillEngine",
                "responsibility": "Partial fills, FOK/IOC/RETURN simulation, requotes",
                "inputs": ["OrderRequest", "QuoteStream", "FillCap"],
                "outputs": ["FillEvent"],
            },
            {
                "id": "dbt.latency",
                "name": "LatencySimulator",
                "responsibility": "Sample delay; advance tick stream to t+Δ; price at arrival",
                "inputs": ["LatencyProfile", "VPSProfile"],
                "outputs": ["ArrivalTimestamp", "ArrivalQuote"],
            },
            {
                "id": "dbt.rules",
                "name": "BrokerRules",
                "responsibility": "stops_level freeze_level digits volume_min/step max deviation",
                "inputs": ["BrokerProfile", "symbol_info snapshot"],
                "outputs": ["ValidationResult"],
            },
            {
                "id": "dbt.margin",
                "name": "MarginEngine",
                "responsibility": "Margin calc, margin call, stop-out simulation",
                "inputs": ["OpenPositions", "AccountState", "BrokerProfile"],
                "outputs": ["MarginLevel", "StopOutEvents"],
            },
            {
                "id": "dbt.carry",
                "name": "CarryEngine",
                "responsibility": "Swap accrual, commission per fill",
                "inputs": ["Position", "HoldDuration", "BrokerProfile"],
                "outputs": ["SwapCharge", "CommissionCharge"],
            },
            {
                "id": "dbt.gap",
                "name": "GapEngine",
                "responsibility": "Weekend/news gap through SL/TP",
                "inputs": ["BarGapEvents", "TickStream"],
                "outputs": ["GapAdjustedExitPrice"],
            },
            {
                "id": "dbt.profile",
                "name": "BrokerProfile",
                "responsibility": "Frozen broker fingerprint JSON (calibrated Phase 30D)",
                "inputs": ["Calibration dataset"],
                "outputs": ["SpreadCoeffs", "SlippageCoeffs", "RetcodeRates"],
            },
            {
                "id": "dbt.telemetry",
                "name": "ExecutionTelemetry",
                "responsibility": "TCA metrics, execution score, rejection log",
                "inputs": ["FillReport"],
                "outputs": ["ExecutionQualityRecord"],
            },
        ],
        "interfaces": {
            "IOrderExecutor": "Existing port — DBT implements shadow or replaces Mt5ExecutionAdapter paper branch",
            "IBrokerTwin": "simulate_market_order(req, snapshot) → FillReport",
            "IQuoteStream": "get_quote(ts), advance_to(ts)",
            "IBrokerProfileLoader": "load(profile_id) → BrokerProfile",
        },
        "data_flow": [
            "TradingSignal + lot → OrderRequest",
            "MarketSnapshot ← TickStore/CandleStore (+ optional live)",
            "BrokerRules.validate(OrderRequest)",
            "LatencySimulator → arrival time",
            "QuoteStream.advance(arrival) → bid/ask",
            "SpreadEngine + SlippageEngine + FillEngine → FillReport",
            "CarryEngine on position updates",
            "MarginEngine after each fill",
            "FillReport → PaperTradeRecorder / journal (prices only, no logic change)",
            "AccountingEngine unchanged — receives final prices/PnL",
        ],
        "dependencies": {
            "must_not_import": ["ML kernel", "RiskGate internals", "WPSQF", "exit_policy logic changes"],
            "may_read": ["CandleStore", "symbol_info", "BrokerConstraints", "domain.position_logic"],
            "feeds": ["PaperTradeRecorder", "TradeJournal", "ReplayPortfolioTracker"],
        },
        "validation_strategy": {
            "unit": "Each engine deterministic with fixed seed + golden fixtures",
            "parity": "DBT paper vs live fill log MAE on spread/slip (Phase 30D)",
            "replay": "489 Phase29B trades — PF within ±5% of calibrated target",
            "regression": "TRADINGBOT_SIGNAL_FILTER=OFF byte-identical signals; only fills differ",
            "stress": "Phase30A scenario matrix re-run under DBT",
        },
        "integration_modes": {
            "replay": "Bar loop feeds MarketSnapshot; DBT replaces instant fill in replay portfolio open",
            "paper": "Mt5ExecutionAdapter paper branch delegates to DBT instead of PaperBroker",
            "live_shadow": "Live sends real order; DBT simulates parallel; log divergence",
            "live": "Future Phase 31+ — optional not in 30C scope",
        },
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_realism_gap(audit: dict) -> dict[str, Any]:
    critical = [c for c in audit["components"] if c["risk"] in ("CRITICAL", "HIGH — fill price may not match any real tick at decision time") or "CRITICAL" in c["risk"]]
    return {
        "phase": "30C",
        "overall_gap_score": 58,
        "scale": "0=identical to broker, 100=no gap",
        "production_vs_retail_mt5_gap": 58,
        "phase30a_vs_retail_mt5_gap": 42,
        "top_gaps": [
            {"gap": "Exit slippage and gap-through-stop absent in production", "severity": "critical"},
            {"gap": "Static spread vs tick-by-tick", "severity": "critical"},
            {"gap": "Latency not price-coupled", "severity": "critical"},
            {"gap": "No margin stop-out", "severity": "high"},
            {"gap": "No broker rules (stops_level/freeze)", "severity": "high"},
            {"gap": "No live calibration dataset", "severity": "high"},
        ],
        "pf_sensitivity_summary": {
            "spread_exit_dominant": True,
            "latency_non_binding_until_coupled": True,
            "tail_events_dominate_dd": True,
        },
        "component_gap_count": len(audit["components"]),
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_broker_behavior_model() -> dict[str, Any]:
    return {
        "phase": "30C",
        "model_type": "Hybrid stochastic MT5 retail market-maker twin",
        "state_variables": [
            "bid", "ask", "spread", "mid", "atr", "session", "vol_regime",
            "liquidity_score", "queue_depth", "margin_level", "news_flag", "weekend_flag",
        ],
        "order_lifecycle_states": [
            "PENDING_VALIDATE", "REJECTED_RULES", "QUEUED", "SENT",
            "REQUOTED", "PARTIAL_FILL", "FILLED", "OFF_QUOTES", "REJECTED_MARGIN", "CANCELLED",
        ],
        "fill_price_formula": "fill = mid ± spread/2 ± slippage + impact + gap; slippage ~ f(vol, spread, lot, latency, side)",
        "spread_formula": "spread = base_spread(session, symbol) × vol_mult(atr_pct) × news_mult × weekend_mult",
        "latency_price_formula": "P(t+Δ) = P(t) + drift(vol) × √Δ + jump(news); Δ ~ sum(latency_components)",
        "marginal_distributions": {
            "spread_xauusd_points": {"asian_p50": 0.45, "overlap_p50": 0.28, "news_p95": 1.2, "note": "Industry typical retail ranges — requires broker calibration"},
            "slippage_points": {"normal_p50": 0.05, "news_p95": 0.40},
            "latency_ms": {"vps_p50": 65, "home_p95": 250},
        },
        "retcode_model": {
            "DONE": 0.92,
            "REQUOTE": 0.04,
            "OFF_QUOTES": 0.02,
            "REJECT": 0.015,
            "NO_MONEY": 0.005,
            "note": "Placeholder — must calibrate from live logs",
        },
        "calibration_required": True,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_tick_requirements() -> dict[str, Any]:
    return {
        "phase": "30C",
        "minimum_data": {
            "fields": ["timestamp_utc", "bid", "ask", "last", "volume", "flags"],
            "frequency": "Every tick or 100ms sampled for XAUUSD during overlap",
            "history_depth_days": 30,
            "alignment": "UTC; synchronized with M5 bar timestamps",
        },
        "sources": [
            {"source": "MT5 symbol_info_tick stream export", "priority": 1},
            {"source": "Broker statement fill logs", "priority": 1},
            {"source": "Candle close proxy", "priority": 3, "adequacy": "insufficient for twin"},
        ],
        "storage": "tradingbot/ml/research/phase30d/tick_store/ (proposed)",
        "validation": "bid <= ask; spread positive; no backward time",
        "replay_mode": "Tick replay for fill path; bar replay for signal path unchanged",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_spread_model_requirements() -> dict[str, Any]:
    return {
        "phase": "30C",
        "inputs": ["session", "atr_percentile", "news_flag", "weekend_flag", "symbol", "broker_profile"],
        "outputs": ["spread_points", "bid", "ask"],
        "calibration_targets": [
            "Match p50/p95 spread by session vs live tick export",
            "News window spread multiplier from NFP/FOMC samples",
        ],
        "production_gap": "Fixed 0.30 → must become tick-level",
        "evidence": "phase30a spread breaking point 1.5×; high_spread PF 0.75",
        "acceptance": "Simulated spread distribution KS-test vs live ticks p>0.05",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_latency_model_requirements() -> dict[str, Any]:
    return {
        "phase": "30C",
        "components_ms": ["decision", "python", "mt5", "broker", "network", "execution"],
        "profiles": ["normal", "fast_vps", "slow_vps"],
        "critical_requirement": "MUST couple to price via tick stream advance",
        "formula": "arrival_ts = decision_ts + total_latency; fill_quote = quote_stream[arrival_ts]",
        "production_gap": "Zero latency in paper; Phase30A latency does not move price",
        "acceptance": "Fill price variance increases with latency at fixed decision price",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_slippage_model_requirements() -> dict[str, Any]:
    return {
        "phase": "30C",
        "legs": ["entry", "exit"],
        "distribution": "Mixture: negative (adverse), zero, positive (improvement)",
        "drivers": ["atr", "spread", "liquidity", "lot", "session", "trend", "latency"],
        "production_gap": "Entry fixed 0.10; exit zero; journal logs zero",
        "exit_priority": "CRITICAL — phase30b rank 2",
        "acceptance": "Mean slippage within 20% of live fill log by session",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_orderbook_requirements() -> dict[str, Any]:
    return {
        "phase": "30C",
        "approach": "Synthetic depth curve — not full L2 unless broker provides",
        "parameters": ["base_depth_lot", "session_mult", "vol_decay", "last_look_prob"],
        "outputs": ["max_fillable_lot", "partial_fill_prob", "impact_points"],
        "min_lot_note": "At 0.01 lot partial fills likely over-modelled — calibrate down",
        "acceptance": "Partial fill rate <5% at 0.01 lot XAUUSD unless news flag",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_priority_matrix() -> dict[str, Any]:
    modules = [
        {"module": "SpreadEngine (tick-level entry+exit)", "complexity": 4, "benefit": 5, "production_risk": 3, "dev_days": 8, "realism_gain": 18, "priority": 1},
        {"module": "SlippageEngine (exit leg)", "complexity": 4, "benefit": 5, "production_risk": 3, "dev_days": 6, "realism_gain": 15, "priority": 2},
        {"module": "MarketDataFeed / TickStore", "complexity": 5, "benefit": 5, "production_risk": 2, "dev_days": 10, "realism_gain": 20, "priority": 3},
        {"module": "LatencySimulator + price coupling", "complexity": 5, "benefit": 4, "production_risk": 3, "dev_days": 8, "realism_gain": 12, "priority": 4},
        {"module": "BrokerRules (stops/freeze/digits)", "complexity": 3, "benefit": 3, "production_risk": 2, "dev_days": 4, "realism_gain": 8, "priority": 5},
        {"module": "GapEngine (SL/TP gap-through)", "complexity": 4, "benefit": 4, "production_risk": 2, "dev_days": 5, "realism_gain": 10, "priority": 6},
        {"module": "FillEngine + requote taxonomy", "complexity": 4, "benefit": 3, "production_risk": 3, "dev_days": 6, "realism_gain": 7, "priority": 7},
        {"module": "LiquidityBook", "complexity": 4, "benefit": 3, "production_risk": 2, "dev_days": 5, "realism_gain": 6, "priority": 8},
        {"module": "BrokerProfile calibration pipeline", "complexity": 5, "benefit": 5, "production_risk": 1, "dev_days": 12, "realism_gain": 22, "priority": 9},
        {"module": "MarginEngine + stop-out", "complexity": 4, "benefit": 2, "production_risk": 2, "dev_days": 6, "realism_gain": 5, "priority": 10},
        {"module": "CarryEngine (swap/commission)", "complexity": 2, "benefit": 2, "production_risk": 1, "dev_days": 3, "realism_gain": 3, "priority": 11},
        {"module": "ExecutionTelemetry / TCA", "complexity": 2, "benefit": 3, "production_risk": 1, "dev_days": 3, "realism_gain": 4, "priority": 12},
    ]
    return {
        "phase": "30C",
        "scale": {"complexity": "1-5", "benefit": "1-5", "production_risk": "1-5 lower safer", "realism_gain": "points toward 100 realism score"},
        "modules": modules,
        "recommended_sequence": [m["module"] for m in sorted(modules, key=lambda x: x["priority"])],
        "mvp_scope": ["TickStore", "SpreadEngine", "SlippageEngine exit", "LatencySimulator coupled", "BrokerProfile v1"],
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_production_roadmap(priority: dict) -> dict[str, Any]:
    return {
        "phase": "30C",
        "research_only_through": "Phase 30C",
        "implementation_phases": [
            {
                "phase": "30D",
                "title": "Broker Data Collection",
                "deliverables": ["30-day tick export", "Live fill log", "symbol_info snapshot", "Retcode histogram"],
                "blocks": "BrokerProfile calibration",
            },
            {
                "phase": "30E",
                "title": "DBT Core MVP",
                "deliverables": ["SpreadEngine", "SlippageEngine", "LatencySimulator coupled", "Unit tests"],
                "integration": "None — isolated module tests",
            },
            {
                "phase": "30F",
                "title": "Replay Integration",
                "deliverables": ["DBT in unified_pipeline_replay paper branch", "489-trade validation"],
                "gate": "PF within ±5% calibrated target; signals unchanged",
            },
            {
                "phase": "30G",
                "title": "Paper Live Parity",
                "deliverables": ["Paper branch delegation", "Live shadow mode", "TCA dashboard"],
                "gate": "30-day paper trading readiness review",
            },
        ],
        "non_goals": [
            "ML retraining", "RiskGate changes", "WPSQF changes", "Hybrid B exit logic changes", "Accounting formula changes",
        ],
        "backward_compatibility": "DBT disabled via TRADINGBOT_BROKER_TWIN=OFF reproduces current paper",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def determine_verdict() -> str:
    """Model design complete; empirical broker fingerprint requires Phase 30D data."""
    return "MORE_BROKER_RESEARCH_REQUIRED"


def run_phase30c() -> dict[str, Any]:
    ts = datetime.now(timezone.utc).isoformat()
    PHASE_DIR.mkdir(parents=True, exist_ok=True)

    perf = _load(PHASE30A / "performance_comparison.json")
    stress = _load(PHASE30A / "stress_tests.json")

    audit = build_broker_component_audit(perf, stress)
    _write("broker_component_audit.json", audit)

    arch = build_digital_broker_architecture()
    _write("digital_broker_architecture.json", arch)

    gap = build_realism_gap(audit)
    _write("execution_realism_gap.json", gap)

    behavior = build_broker_behavior_model()
    _write("broker_behavior_model.json", behavior)

    _write("tick_requirements.json", build_tick_requirements())
    _write("spread_model_requirements.json", build_spread_model_requirements())
    _write("latency_model_requirements.json", build_latency_model_requirements())
    _write("slippage_model_requirements.json", build_slippage_model_requirements())
    _write("orderbook_requirements.json", build_orderbook_requirements())

    priority = build_priority_matrix()
    _write("broker_priority_matrix.json", priority)

    roadmap = build_production_roadmap(priority)
    _write("production_roadmap.json", roadmap)

    verdict = determine_verdict()

    final = {
        "phase": "30C",
        "verdict": verdict,
        "mission": "Digital Broker Twin design — research only, no implementation",
        "production_modified": False,
        "architecture_modules": len(arch["modules"]),
        "components_audited": audit["component_count"],
        "dominant_gap": "Tick-level spread + exit slippage + latency-price coupling absent in production",
        "mvp_modules": priority["mvp_scope"],
        "next_phase": "30D Broker Data Collection — required before model calibration",
        "deliverables": [
            "digital_broker_architecture.json",
            "broker_component_audit.json",
            "execution_realism_gap.json",
            "broker_behavior_model.json",
            "tick_requirements.json",
            "spread_model_requirements.json",
            "latency_model_requirements.json",
            "slippage_model_requirements.json",
            "orderbook_requirements.json",
            "broker_priority_matrix.json",
            "production_roadmap.json",
            "phase30c_final_report.json",
        ],
        "generated_utc": ts,
    }
    _write("phase30c_final_report.json", final)
    return final


def main() -> int:
    report = run_phase30c()
    print(json.dumps({"verdict": report["verdict"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

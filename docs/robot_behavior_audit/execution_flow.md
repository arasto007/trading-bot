# Complete Execution Flow

**Repository:** `TradingBot new`  
**Live path:** `LiveRunner` → `TradingKernel` → pipeline stages → `Mt5ExecutionAdapter` → `TradeJournal`

Each transition documents **input**, **output**, **conditions**, and **rejection reasons**.

---

## Stage 0 — LiveRunner Bootstrap

| | |
|---|---|
| **File** | `tradingbot/application/live_runner.py` |
| **Class / function** | `LiveRunner.__init__()`, `_run()` |
| **Input** | Legacy config, CLI flags (`--execute` = live, not dry-run) |
| **Output** | Connected `TradingKernel` with all adapters wired |
| **Conditions** | MT5 must connect unless `TRADINGBOT_SKIP_MT5_STARTUP` set |
| **Rejections** | `StartupValidationError` if validation fails; emergency stop state blocks start |

**Wiring:**
- Market data: `Mt5MarketDataAdapter`
- Indicators: `TechnicalIndicatorEngine`
- Strategies: `build_strategy_registry()` → `AdaptiveRegimeStrategyRegistry` (default)
- Risk: `create_risk_gate()` → `RiskGate`
- Execution: `Mt5ExecutionAdapter`
- Positions: `Mt5PositionManager`

---

## Stage 1 — TradingKernel Global Cycle

| | |
|---|---|
| **File** | `tradingbot/kernel/trading_kernel.py` |
| **Class / function** | `TradingKernel.run_global_cycle()` |
| **Input** | Kernel settings (symbols, timeframes, 30s interval) |
| **Output** | `dict[str, CycleContext]` per market + position management |
| **Conditions** | Kernel state must not be `EMERGENCY_STOP` |
| **Rejections** | Entire cycle skipped if MT5 disconnected, health check fails, or emergency stop |

**Sub-steps:**
1. `ensure_connected()` on market data adapter
2. `check_mt5_health()` — tick age ≤ 120s
3. `update_all(symbols, timeframes)` — refresh OHLCV cache
4. `run_market_cycle()` for each `MarketKey`
5. `executor.manage_open_positions()` — log-only per market
6. `_manage_positions()` → `Mt5PositionManager.manage_all()`

---

## Stage 2 — DataStage

| | |
|---|---|
| **File** | `tradingbot/pipeline/data_stage.py` |
| **Class / function** | `DataStage.run()` |
| **Input** | `CycleContext.market`, `portfolio_snapshot` |
| **Output** | `ctx.raw_ohlcv` (pandas DataFrame) |
| **Conditions** | Must fetch ≥ `min_bars` (default **80** from PRICE_ACTION config) |
| **Rejections** | `"Insufficient bars"` — pipeline stops for this market |

**Data source:** `Mt5MarketDataAdapter.get_ohlcv()` — MT5 historical rates.

---

## Stage 3 — IndicatorStage

| | |
|---|---|
| **File** | `tradingbot/pipeline/indicator_stage.py` |
| **Class / function** | `IndicatorStage.run()` |
| **Input** | `ctx.raw_ohlcv` |
| **Output** | `ctx.enriched_ohlcv` with indicator columns |
| **Conditions** | Raw OHLCV must exist |
| **Rejections** | Error added if raw missing; stage returns `False` |

**Engine:** `TechnicalIndicatorEngine.enrich_for_market()` → `tradingbot/domain/indicators.py`.

---

## Stage 4 — SignalStage

| | |
|---|---|
| **File** | `tradingbot/pipeline/signal_stage.py` |
| **Class / function** | `SignalStage.run()` |
| **Input** | `ctx.enriched_ohlcv`, `portfolio_snapshot["correlation_data"]` |
| **Output** | `ctx.signal` (`TradingSignal`) or pipeline stop |
| **Conditions** | New closed bar timestamp ≠ cached `_last_closed_bar`; signal direction ≠ HOLD |
| **Rejections** | Same bar already evaluated; no closed bars; `generate_signal()` returns None/HOLD |

### SignalStage → AdaptiveRegimeStrategyRegistry

| | |
|---|---|
| **File** | `tradingbot/adapters/adaptive_regime_strategy_registry.py` |
| **Function** | `generate_signal()` |
| **Input** | `MarketKey`, closed OHLCV dataframe |
| **Output** | `TradingSignal` with SL/TP, confidence=0.60, metadata |
| **Conditions** | Symbol=XAUUSD, TF=M5, adaptive enabled, frame non-empty |
| **Rejections** | Wrong symbol/TF; empty frame; `evaluate_adaptive_at_index()` returns None |

### AdaptiveRegimeStrategyRegistry → adaptive_regime logic

| | |
|---|---|
| **File** | `tradingbot/strategies/adaptive_regime.py` |
| **Functions** | `prepare_adaptive_frame()`, `classify_regime()`, `evaluate_adaptive_at_index()` |
| **Input** | Prepared frame with atr_pct, ema20/50, h1_trend, rsi14, hour_utc |
| **Output** | `AdaptiveSignal` or None |
| **Conditions (CONFLUENCE_ONLY default)** | Session 12–17 UTC; H1 aligned; EMA sep ≥ 0.055%; MTF+VOL agree (atr 30–70%) OR high-vol HVM+MTF agree |
| **Rejections** | Outside session; regime NO_TRADE; sub-strategies disagree; atr outside bands |

---

## Stage 5 — SignalFilterStage (WPSQF)

| | |
|---|---|
| **File** | `tradingbot/pipeline/signal_filter_stage.py` |
| **Class / function** | `SignalFilterStage.run()` |
| **Input** | `ctx.signal`, closed enriched OHLCV |
| **Output** | Signal unchanged or `ctx.signal = None` |
| **Conditions** | Only active when `TRADINGBOT_SIGNAL_FILTER=WPSQF` |
| **Rejections** | WPSQF score < threshold (default **77.56**) |

**Current live default:** `resolve_signal_filter_mode()` returns **OFF** — stage passes through immediately (line 21–22).

**Filter engine:** `tradingbot/services/winner_population_signal_quality_filter.py` → `WinnerPopulationSignalQualityFilter.evaluate()`.

---

## Stage 6 — RiskStage

| | |
|---|---|
| **File** | `tradingbot/pipeline/risk_stage.py` |
| **Class / function** | `RiskStage.run()` |
| **Input** | `ctx.signal`, enriched portfolio snapshot (ohlcv, htf_bias, open positions) |
| **Output** | `ctx.risk` (`RiskDecision`); may set `ctx.signal.lot_size` |
| **Conditions** | Signal must exist |
| **Rejections** | Any `RiskGate.evaluate()` denial → `"Risk blocked: {reason}"` |

### RiskStage → RiskGate

| | |
|---|---|
| **File** | `tradingbot/adapters/risk_gate.py` |
| **Function** | `RiskGate.evaluate()` |
| **Input** | `TradingSignal`, portfolio snapshot with OHLCV |
| **Output** | `RiskDecision(allowed=True, adjusted_lot=...)` or denied |
| **Conditions** | All live gates + tracker + `risk_logic.can_trade()` pass |
| **Rejections** | See Decision Map — max positions, news, Friday, spread, hedge, cooldown, daily loss, meta-labeler (N/A for adaptive), lot calc failure |

**Live gate order in `_live_gates()`:**
1. Max positions (adaptive capped to **1** concurrent)
2. News blackout (30 min if enabled)
3. Friday no-entry after hour **17**
4. Spread ≤ max (**15** pips min for XAU)
5. No opposite position on same symbol
6. Early return for VOL/ADAPTIVE — **skips** HTF + market filters

**Tracker gates (`LiveRiskTracker.check_entry_allowed`):**
- Max **3** trades/day (vol/adaptive path)
- Cooldown **12** M5 bars
- Daily loss budget (4% of equity)
- Pause after **3** consecutive losses

---

## Stage 7 — ExecutionStage

| | |
|---|---|
| **File** | `tradingbot/pipeline/execution_stage.py` |
| **Class / function** | `ExecutionStage.run()` |
| **Input** | `ctx.signal` with lot_size |
| **Output** | `ctx.execution` (`ExecutionResult`) |
| **Conditions** | Prior stages succeeded |
| **Rejections** | Executor returns `success=False` (MT5 down, Algo Trading off, no price, validation fail) |

---

## Stage 8 — Mt5ExecutionAdapter

| | |
|---|---|
| **File** | `tradingbot/adapters/mt5_execution.py` |
| **Class / function** | `Mt5ExecutionAdapter.execute()` → `_place_market_order()` |
| **Input** | `TradingSignal`, lot float |
| **Output** | `ExecutionResult` with ticket, fill price, slippage |
| **Conditions** | Live mode; MT5 connected; autotrading ready; valid order |
| **Rejections** | Dry-run/paper short-circuit; connection fail; `order_logic.validate_order()` fail; `order_send` retcode ≠ DONE |

**Order details:**
- Action: `TRADE_ACTION_DEAL` (market)
- Magic: 234000
- Deviation: 20
- SL/TP from signal attached to request
- Retry: `_order_send_with_retry()` once on price requote codes

**On success:** `TradeJournal.log_execution()`, `Notifier.alert()`, `record_live_entry()`.

---

## Stage 9 — TradeJournal

| | |
|---|---|
| **File** | `tradingbot/services/trade_journal.py` |
| **Class / function** | `log_execution()`, `log_cycle()` |
| **Input** | Execution details or cycle state string |
| **Output** | SQLite rows in `data/trade_journal.db` |
| **Conditions** | Database path writable |
| **Rejections** | NOT PROVEN — SQLite errors would propagate to caller logs |

**Cycle logging:** `TradingKernel.run_market_cycle()` writes `cycle_events` with state `executed` / `idle` / `blocked` and detail like `no_signal` or `signal=BUY`.

---

## Post-Pipeline — Position Management

| | |
|---|---|
| **File** | `tradingbot/adapters/mt5_position_manager.py` |
| **Function** | `manage_all()` |
| **Input** | All MT5 open positions |
| **Output** | SL updates, partial closes, full closes |
| **Conditions** | Not dry-run for broker sends |
| **Rejections** | `positions_get()` failure → silent return |

---

## End-to-End Flow Diagram (Text)

```
[30s timer]
    │
    ▼
LiveRunner._run() ──► TradingKernel.run_global_cycle()
    │
    ├─► DataStage ──────────► raw OHLCV (≥80 bars)
    │         │
    │         ▼
    ├─► IndicatorStage ─────► enriched OHLCV (RSI, ADX, ATR...)
    │         │
    │         ▼
    ├─► SignalStage ────────► AdaptiveRegimeStrategyRegistry.generate_signal()
    │         │                    │
    │         │                    ▼
    │         │              adaptive_regime.evaluate_adaptive_at_index()
    │         │
    │         ▼ (signal or stop)
    ├─► SignalFilterStage ────► WPSQF [OFF by default] → pass
    │         │
    │         ▼
    ├─► RiskStage ────────────► RiskGate.evaluate() → lot size
    │         │
    │         ▼
    ├─► ExecutionStage ─────► Mt5ExecutionAdapter.execute() → MT5
    │         │
    │         ▼
    └─► TradeJournal.log_cycle() + log_execution()

Then: Mt5PositionManager.manage_all() [trailing / partial / EOD / emergency]
```

---

## Common Rejection Summary (Live ADAPTIVE Path)

| Stage | Most common rejection | Evidence |
|-------|----------------------|----------|
| DataStage | Not enough history bars | `data_stage.py` min_bars check |
| SignalStage | Same bar already checked | `signal_stage.py` `_last_closed_bar` |
| SignalStage | No confluence / outside session | `adaptive_regime.py` |
| SignalFilterStage | WPSQF low score | **Inactive** — default OFF |
| RiskStage | Cooldown / max trades / spread | `live_risk_tracker.py`, `risk_gate.py` |
| ExecutionStage | MT5 autotrading off | `mt5_execution.py` `check_autotrading_ready()` |

**Prior audit observation (conversation history):** When VOL_REGIME-only mode was active, Trade Quality filter blocked signals due to `spread_proxy` overstating spread vs live tick. Current adaptive path sets `tq_skipped: True` in metadata and TQ is not evaluated in registry.

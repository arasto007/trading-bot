# Robot Overview — What the Machine Does

**Repository:** `TradingBot new`  
**Audit mode:** Read-only (code evidence only)  
**Current live engine:** ADAPTIVE_REGIME on XAUUSD M5 (when `USE_ML_KERNEL=false`)

This document explains the robot like a machine manual for its owner — no programming knowledge required.

---

## 1. How the Robot Starts

| Item | Detail |
|------|--------|
| **File** | `start/START_BOT.bat` |
| **Main class** | N/A (Windows batch script) |
| **Main function** | Calls `python scripts\start_bot.py` after loading `.env` |
| **Plain English** | You double-click START_BOT. The script loads your MT5 credentials from `.env`, checks that MetaTrader 5 is open, then launches the background trading daemon. |

**Chain after START_BOT:**

| Step | File | Function | What happens |
|------|------|----------|--------------|
| 2 | `scripts/start_bot.py` | `main()` | Waits for MT5, clears manual-stop flag, starts PowerShell daemon |
| 3 | `scripts/start_live_daemon.ps1` | (script) | Kills old bot processes; sets `USE_ML_KERNEL=false` and `ADAPTIVE_REGIME_ENABLED=true` if unset; starts watchdog |
| 4 | `scripts/run_live_watchdog.py` | `main()` | Restarts `python -m tradingbot --loop --execute` if it crashes |
| 5 | `tradingbot/__main__.py` | `main()` | Parses `--loop --execute` and calls live runner |
| 6 | `tradingbot/application/live_runner.py` | `run_live_loop()` → `LiveRunner._run()` | Builds MT5 adapters, risk gate, strategy engine, and `TradingKernel`; connects to MT5; runs forever |

**Startup validation:** `tradingbot/services/startup_validator.py` → `validate_startup()` checks that `USE_ML_KERNEL` env var is explicitly set and logs which engine mode is active.

---

## 2. What Happens After MT5 Connects

| Item | Detail |
|------|--------|
| **File** | `tradingbot/application/live_runner.py` |
| **Main class** | `LiveRunner` |
| **Main function** | `_run()` |
| **Plain English** | Once MT5 is connected, the robot starts background services (alerts, kill switch, daily reports), then enters a loop that runs every **30 seconds** (`LOOP_INTERVAL` in `tradingbot/config/live.py`). Each loop is called a **global cycle**. |

Inside each global cycle (`TradingKernel.run_global_cycle()` in `tradingbot/kernel/trading_kernel.py`):

1. Check MT5 is still connected and ticks are fresh (max 120 seconds old).
2. Download/update price data for all configured symbols and timeframes.
3. For each market (currently **XAUUSD on 5-minute chart only**), run the trading pipeline.
4. Manage all open positions (trailing stop, partial profit, emergency close, end-of-day close).
5. Write cycle results to the trade journal database.

---

## 3. How a New Candle Is Detected

| Item | Detail |
|------|--------|
| **File** | `tradingbot/pipeline/signal_stage.py` |
| **Main class** | `SignalStage` |
| **Main function** | `run()` |
| **Plain English** | The robot only acts on **closed** candles, never the candle still forming. It remembers the timestamp of the last closed bar it already evaluated. If the newest closed bar has the same timestamp as before, it skips signal generation entirely for that cycle. |

**Supporting logic:**

- `tradingbot/domain/ohlcv.py` → `exclude_forming_bar()` removes the incomplete current bar from the dataframe.
- Data is fetched in `tradingbot/pipeline/data_stage.py` → `DataStage.run()` via `Mt5MarketDataAdapter.get_ohlcv()`.

**Important behavior:** If the first evaluation on a new bar returns no signal, the robot **does not retry** until the **next** closed bar appears. This is by design (deduplication cache `_last_closed_bar`).

---

## 4. How Features Are Created

There are **two parallel feature paths** in live mode:

### Path A — Kernel indicators (pipeline)

| Item | Detail |
|------|--------|
| **File** | `tradingbot/pipeline/indicator_stage.py` |
| **Main class** | `IndicatorStage` |
| **Main function** | `run()` |
| **Engine** | `tradingbot/adapters/indicator_engine.py` → `TechnicalIndicatorEngine` |
| **Plain English** | Adds standard columns to OHLCV: RSI, ADX, ATR, EMAs, etc. via `tradingbot/domain/indicators.py`. Used by risk gates and legacy filters — **not** the primary signal source for ADAPTIVE_REGIME. |

### Path B — Adaptive strategy frame (signal engine)

| Item | Detail |
|------|--------|
| **File** | `tradingbot/strategies/adaptive_regime.py` |
| **Main function** | `prepare_adaptive_frame()` → calls `tradingbot/strategies/vol_regime_signal.py` → `prepare_frame()` |
| **Underlying research module** | `tradingbot/ml/research/live_l2/edge_discovery_round2.py` → `_prepare_frame_round2()` |
| **Plain English** | Before deciding BUY/SELL, the adaptive engine builds its **own** dataframe with ATR percentile, EMA20/50, H1 trend, RSI14, session hour, etc. This is separate from the kernel indicator stage. |

---

## 5. How a Signal Is Produced

| Item | Detail |
|------|--------|
| **File** | `tradingbot/adapters/adaptive_regime_strategy_registry.py` |
| **Main class** | `AdaptiveRegimeStrategyRegistry` |
| **Main function** | `generate_signal()` |
| **Plain English** | Only works for **XAUUSD** on **M5**. Classifies market regime, then runs sub-strategies. With default **CONFLUENCE_ONLY** mode, both multi-timeframe trend and volatility-regime rules must agree on direction (or high-vol momentum + MTF must agree). Confidence is fixed at **0.60** (`VOL_REGIME_RULE_CONFIDENCE`). |

**Decision logic:** `tradingbot/strategies/adaptive_regime.py` → `classify_regime()` + `evaluate_adaptive_at_index()`.

**Stop loss / take profit:** `tradingbot/domain/signal_helpers.py` → `compute_sl_tp()` using ATR-based distances per sub-strategy.

---

## 6. How Risk Is Checked

| Item | Detail |
|------|--------|
| **File** | `tradingbot/pipeline/risk_stage.py` → `tradingbot/adapters/risk_gate.py` |
| **Main class** | `RiskStage` → `RiskGate` |
| **Main function** | `RiskStage.run()` → `RiskGate.evaluate()` |
| **Plain English** | After a BUY/SELL signal exists, the risk gate asks: "Are we allowed to trade right now?" It checks open positions, news blackout, Friday cutoff, live spread, opposite-position hedge block, daily trade count, cooldown since last trade, daily loss budget, and consecutive loss limits. Then it calculates lot size from account equity and stop distance. |

**For ADAPTIVE_REGIME signals specifically:** HTF alignment, price-action market filters, and meta-labeler are **skipped** (`risk_gate.py` lines 174, 277–278).

**Tracker:** `tradingbot/services/live_risk_tracker.py` → `LiveRiskTracker.check_entry_allowed()` enforces max **3 trades/day** and **12-bar cooldown** (M5 = 60 minutes).

---

## 7. How an Order Is Executed

| Item | Detail |
|------|--------|
| **File** | `tradingbot/pipeline/execution_stage.py` → `tradingbot/adapters/mt5_execution.py` |
| **Main class** | `ExecutionStage` → `Mt5ExecutionAdapter` |
| **Main function** | `ExecutionStage.run()` → `Mt5ExecutionAdapter.execute()` |
| **Plain English** | If not in dry-run or paper mode, sends a **market order** to MT5: BUY at ask, SELL at bid, with SL/TP attached. Uses magic number **234000**, deviation **20** points, comment like `TB_5m_ADAPTIVE_REGIME`. Retries once on certain broker error codes. |

**Pre-checks:** MT5 connected, Algo Trading enabled, valid lot size, price available.

**Modes:**
- `TRADINGBOT_DRY_RUN=1` — logs only, no broker order
- `TRADINGBOT_PAPER=1` — simulated fill in paper journal
- Neither set (live `--execute`) — real MT5 order

---

## 8. How a Position Is Managed

| Item | Detail |
|------|--------|
| **File** | `tradingbot/adapters/mt5_position_manager.py` |
| **Main class** | `Mt5PositionManager` |
| **Main function** | `manage_all()` → `_manage_one()` per open position |
| **Plain English** | Every 30 seconds, for each open trade the robot checks (in order): Friday close, end-of-day close, emergency loss limit, partial take-profit at 1R/2R/3R, then ATR-based trailing stop. Stop loss only moves in your favor, never widens. |

**Shared math:** `tradingbot/domain/position_logic.py` (same formulas used in backtest).

**Disabled when adaptive/vol on:** Legacy `PositionProtector` and `PositionRecoveryService` (`live_runner.py` lines 206–208).

**Account-level kill switch:** `tradingbot/services/kill_switch.py` — stops new cycles if drawdown ≥ 15% or daily loss ≥ 4%.

---

## 9. How a Trade Is Closed

A position can close through **any** of these paths:

| Close reason | Component | Plain English |
|--------------|-----------|---------------|
| Take profit hit | MT5 broker | Price reaches TP set at entry |
| Stop loss hit | MT5 broker | Price reaches SL (initial or trailed) |
| Partial TP | `Mt5PositionManager._check_partial_tp()` | Closes 50% at 1R, 30% at 2R, 20% at 3R |
| Trailing stop | `Mt5PositionManager._apply_trailing()` | SL moved up/down as profit grows |
| Emergency | `Mt5PositionManager._check_emergency()` | Force close if unrealized loss exceeds pip limit |
| End of day | `Mt5PositionManager._check_eod_close()` | Closes at 23:55 (configurable) |
| Friday close | `Mt5PositionManager._check_friday_close()` | Closes open positions Friday 20:00 |
| Kill switch | `KillSwitchService` | Halts bot; does not auto-close all positions |

---

## 10. How Results Are Stored

| Item | Detail |
|------|--------|
| **File** | `tradingbot/services/trade_journal.py` |
| **Main class** | `TradeJournal` |
| **Database** | `{project}/data/trade_journal.db` (SQLite) |
| **Plain English** | Every order attempt, every pipeline cycle, and paper trades are logged to a local database file you can inspect later. |

| Table | Written when | Contents |
|-------|--------------|----------|
| `executions` | Order sent (live/dry/paper) | symbol, direction, lot, fill price, slippage, ticket, success |
| `cycle_events` | Every market cycle | state: `executed`, `idle`, `blocked`, `mt5_disconnected` |
| `paper_trades` | Paper mode only | Full trade lifecycle with PnL, exit reason, regime |

**Backtest results** (separate from live journal): `data/backtest_last.json` — last recorded 14-day confluence backtest showed **-30.14% return**, profit factor **0.32** (evidence file exists in repo).

---

## Quick Reference — Live Pipeline Order

```
DataStage → IndicatorStage → SignalStage → SignalFilterStage → RiskStage → ExecutionStage
     ↓              ↓              ↓                ↓                ↓            ↓
  OHLCV bars    RSI/ADX/ATR   ADAPTIVE_REGIME   WPSQF (OFF)    RiskGate    MT5 order
```

Position management runs **after** the pipeline, once per global cycle.

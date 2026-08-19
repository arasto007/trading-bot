# Executive Summary — Robot Behavior Audit

**Repository:** `TradingBot new`  
**Audit date:** 2026-07-22  
**Mode:** Read-only code evidence  
**Live engine:** ADAPTIVE_REGIME on XAUUSD M5 (`USE_ML_KERNEL=false`)

All reports live in: `docs/robot_behavior_audit/`

---

## 1. What are the 3 most dangerous problems?

### A. Negative expectancy — bot loses money in backtest

**Evidence:** `data/backtest_last.json` — 14-day confluence mode: **-30.14% return**, profit factor **0.32**, win rate **15%**, max drawdown **35%**.

The robot **can and does place live orders**, but recent replay shows consistent losses. Trading real money would likely lose capital.

### B. Filter and config lies — safety features appear ON but are OFF

**Evidence:**
- `.env.example` sets `ENABLE_RSI_FILTER=true`, `ENABLE_ADX_FILTER=true` — these apply to **ML path only** (`ml/phase19c/filters.py`), not adaptive.
- `VOL_REGIME_ENABLED=true` in `live.py` but **adaptive wins first** in `factory.py` L163.
- WPSQF, meta-labeler, HTF alignment, Trade Quality — all **bypassed** for ADAPTIVE_REGIME signals (`risk_gate.py` L174, L277–278; `signal_filter_mode.py` default OFF).

An owner reading `.env` believes filters protect them; most do not run on the current path.

### C. Duplicate logic with different answers — spread and regime

**Evidence:** `duplicate_work.md`
- **Spread:** live RiskGate uses MT5 tick (`risk_gate.py` `_live_spread_pips`); TQ used bar `spread_proxy` (~3× overstated) — caused total signal blocks in prior VOL_REGIME session (conversation audit). TQ now skipped, but proxy still feeds adaptive frame.
- **Regime:** three incompatible classifiers (`infer_regime_from_ohlcv`, `classify_regime`, `rule_classify_row`) — RiskGate metadata regime ≠ signal routing regime.

Risk decisions and signal decisions can disagree about "what market we're in."

---

## 2. What are the 3 biggest sources of duplicated logic?

| Rank | Domain | Copies | Live winner |
|------|--------|--------|-------------|
| 1 | **Regime classification** | 5 implementations, 3 taxonomies | `adaptive_regime.classify_regime()` |
| 2 | **ATR / volatility** | 9+ implementations (raw ATR, atr_pct rank, percentile, TQ vol score) | `edge_discovery_round2` atr_pct for signals; `signal_helpers._atr` for SL/TP; `risk_logic.atr_from_ohlcv` for lots |
| 3 | **Spread measurement** | Tick vs session estimate vs bar proxy vs WPSQF default | Live tick at RiskGate only |

Full detail: `duplicate_work.md`

---

## 3. What are the 3 safest cleanup actions?

| Action | Risk | Evidence |
|--------|------|----------|
| **Document truth table** — mark which `.env` flags affect adaptive vs ML vs dead | Zero code risk | `configuration_truth.md`, `dead_features.md` |
| **Remove confirmed dead config keys** (`SIGNAL_TIMEOUT`, `NIGHTLY_OPTIMIZATION`, unused `TIMEFRAME_CONFIGS` consumers) | Low — no references found | `dead_features.md` |
| **Archive research phases 14–32** (~679 files never imported live) to separate repo/folder — **keep `live_l2/edge_discovery_round2.py`** | Low if L2 preserved | `dead_features.md` |

**Do NOT delete** `edge_discovery_round2.py` — adaptive live engine depends on it.

---

## 4. What must be fixed before trusting live trading with real money?

| # | Requirement | Current state |
|---|-------------|---------------|
| 1 | **Profit factor > 1.0 on 30+ days** real MT5 data, same config as live | PF 0.32 on 14 days — **FAIL** |
| 2 | **Single config truth** — every .env flag either wired or removed | Many flags ignored — **FAIL** |
| 3 | **Wire or remove `risk_factor=0.5`** for HIGH_VOL — metadata only today | **FAIL** (`adaptive_regime_strategy_registry.py` vs `risk_gate._compute_lot`) |
| 4 | **Live exit PnL accounting** — prove closed trades recorded with exit reason | Entry-only journal — **NOT PROVEN** |
| 5 | **Demo proof gates** — e.g. 50+ trades, 8 weeks stable demo | NOT PROVEN |
| 6 | **Unify spread semantics** — never gate on `spread_proxy` in any active filter | TQ skipped; proxy still in frame — **PARTIAL** |

**Minimum bar:** Do not use real money until backtest AND forward demo both show PF > 1 and max DD within your risk tolerance.

---

## 5. Which subsystem is closest to production quality?

**Execution (`Mt5ExecutionAdapter`)** — Score **8/10**

**Why:**
- Clear dry-run / paper / live modes (`execution_mode.py`)
- Demo account guard
- Autotrading readiness check
- Order validation via `order_logic`
- Retry on broker requote codes
- Slippage calculation and `TradeJournal.log_execution()` on fill
- Central `guarded_order_send()` wrapper

**File:** `tradingbot/adapters/mt5_execution.py`

Execution is the most trustworthy part of the machine. The weakness is **what gets sent** (signal quality) and **whether config matches behavior**, not **how orders are sent**.

---

## Report Index

| Report | File |
|--------|------|
| Robot overview | `robot_overview.md` |
| Execution flow | `execution_flow.md` |
| Duplicate work | `duplicate_work.md` |
| Dead features | `dead_features.md` |
| Decision map | `decision_map.md` |
| Strategy inventory | `strategy_inventory.md` |
| Position lifecycle | `position_lifecycle.md` |
| Configuration truth | `configuration_truth.md` |
| Reliability scorecard | `reliability_scorecard.md` |
| Architecture diagram | `architecture.mmd` |
| Dependency graph | `dependency_graph.mmd` |
| Live trading graph | `live_trading_graph.mmd` |

---

## One-Sentence Owner Summary

The robot **starts reliably**, **sends orders correctly**, but **uses a confluence strategy that backtests badly**, **runs fewer safety filters than your config suggests**, and **computes the same market facts in multiple conflicting ways** — treat it as a **demo experiment**, not a money-making machine, until profitability and config honesty are proven.

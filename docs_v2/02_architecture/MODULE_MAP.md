# Module Map

## Status

- **Status:** VERIFIED
- **Last Verified:** 2026-08-22
- **Verification Method:** Directory inspection and import tracing on live path
- **Verified against commit:** `57bf778c23cefffe508bb49079688b177796f67e`

## Scope

Map of major packages and their **verified role** on the default live trading path.

---

## Top-Level

| Path | Role | Live path status |
|------|------|------------------|
| `tradingbot/` | Primary runtime package | **ACTIVE** |
| `engine/` | Legacy strategy host (PA) | **PARTIAL** — used via adapter |
| `start/` | Windows launchers | **ACTIVE** |
| `scripts/` | Watchdog, daemon, diagnostics | **MIXED** — watchdog **ACTIVE** |
| `config/` | Example env templates | Reference only |
| `tests/` | Pytest suite (231 files) | Test evidence |
| `models/` | Meta-labeler metadata | **PARTIAL** — `.pkl` UNKNOWN |
| `data/` | Runtime state (gitignored) | Runtime artifacts |
| `logs/` | Watchdog and phase logs | Runtime artifacts |
| `docs/` | Legacy documentation | **HISTORICAL** — conflicts exist |
| `docs_v2/` | Current documentation system | **ACTIVE** (this tree) |
| `ml/` (root) | Parallel ML assets | **UNKNOWN** reachability |

---

## `tradingbot/application/`

| Module | Responsibility | Live wired? |
|--------|----------------|-------------|
| `live_runner.py` | `LiveRunner`, infinite loop, services, `_ReliabilityKernel` | **YES** |
| `bootstrap.py` | Single-cycle demo/live/strategies wiring | Alternate entry only |

---

## `tradingbot/kernel/`

| Module | Responsibility | Live wired? |
|--------|----------------|-------------|
| `trading_kernel.py` | `TradingKernel` — global/market cycle, pipeline | **YES** |

---

## `tradingbot/pipeline/`

| Module | Stage | Live wired? |
|--------|-------|-------------|
| `data_stage.py` | DataStage | **YES** |
| `indicator_stage.py` | IndicatorStage | **YES** |
| `signal_stage.py` | SignalStage | **YES** |
| `signal_filter_stage.py` | SignalFilterStage | **YES** (pass-through when OFF) |
| `risk_stage.py` | RiskStage | **YES** |
| `execution_stage.py` | ExecutionStage | **YES** |

---

## `tradingbot/adapters/` (live-critical)

| Module | Responsibility | Live wired? |
|--------|----------------|-------------|
| `mt5_market_data.py` | OHLCV fetch, parquet cache | **YES** |
| `mt5_execution.py` | Order send, dry-run/paper/live | **YES** |
| `mt5_position_manager.py` | Trailing, partial TP, EOD, emergency | **YES** |
| `risk_gate.py` | `RiskGate`, `create_risk_gate` | **YES** |
| `indicator_engine.py` | `TechnicalIndicatorEngine` | **YES** |
| `legacy_strategy_registry.py` | PA via `StrategyManager` | **YES** (inner router) |
| `multi_engine_router.py` | PA/VOL/Adaptive router | **YES** (outer) |
| `vol_regime_strategy_registry.py` | VOL signals | **SHADOW** (logged, not selected) |
| `adaptive_regime_strategy_registry.py` | Adaptive signals | **SHADOW** |
| `shadow_strategy_registry.py` | ML shadow wrap | **SHADOW** |
| `legacy_loader.py` | Config merge | **YES** |

---

## `tradingbot/domain/` (selected)

| Module | Used by live path? |
|--------|-------------------|
| `indicators.py` | **YES** — `compute_indicators` |
| `price_action.py` | **YES** — PA enrichment |
| `gold_strategies/` | **YES** — M5 setup evaluation |
| `signal_helpers.py` | **YES** — `TradingSignal` build |
| `risk_logic.py` | **YES** — RiskGate |
| `position_logic.py` | **YES** — position manager + backtest |
| `filter_policy.py` | **YES** — session filter policy |
| `live_gates.py` | **YES** — spread/news/friday gates (via risk_gate) |

---

## `tradingbot/services/` (live-critical)

| Module | Responsibility | Live wired? |
|--------|----------------|-------------|
| `startup_validator.py` | Fail-fast startup checks | **YES** |
| `runtime_truth.py` | Equity freeze, stale bar, runtime JSON | **YES** |
| `kill_switch.py` | Drawdown/daily loss emergency | **YES** |
| `live_risk_tracker.py` | Cooldown, daily trade caps | **YES** |
| `trade_journal.py` | SQLite execution journal | **YES** |
| `meta_labeler.py` | Meta scoring in RiskGate | **PARTIAL** |
| `live_loop_health.py` | Heartbeat | **YES** |
| `live_ops_service.py` | Daily report, drift | **YES** (live execute) |
| `position_protector.py` | Legacy background protector | **DISABLED** default |
| `position_recovery_service.py` | Restart recovery | **DISABLED** default |
| `demo_account_guard.py` | Block real accounts | **YES** at startup |

---

## `tradingbot/ml/` (summary)

| Area | Live decision impact |
|------|---------------------|
| `integration/factory.py` | **YES** — strategy selection |
| `integration/config.py` | **YES** — ML flags |
| `shadow/` | **SHADOW** only |
| `research/phase*` | **DEAD** for default live (not imported on path) |
| `training/`, `models/` | Research/offline |

---

## `engine/`

| Module | Live wired? |
|--------|-------------|
| `strategy_manager.py` | **YES** via `LegacyStrategyRegistry` |
| `strategies/price_action_strategy.py` | **YES** — only active strategy file |

---

## Evidence

Live wiring traced through `LiveRunner.__init__` and `TradingKernel.__init__`.

## Change Impact

Any new adapter, service, or pipeline stage requires updating this map.

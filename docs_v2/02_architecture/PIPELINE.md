# Pipeline

## Status

- **Status:** VERIFIED
- **Last Verified:** 2026-08-22
- **Verification Method:** Read `TradingKernel` and each `PipelineStage` implementation
- **Verified against commit:** `57bf778c23cefffe508bb49079688b177796f67e`

## Scope

The **actual** per-market processing pipeline executed by `TradingKernel.run_market_cycle()`.

## Pipeline Count

**Six stages** — not five. `SignalFilterStage` exists and is registered.

**Evidence:** `tradingbot/kernel/trading_kernel.py:84–91`

## Stage Order (Verified)

```text
1. DataStage
2. IndicatorStage
3. SignalStage
4. SignalFilterStage
5. RiskStage
6. ExecutionStage
```

Property `TradingKernel.pipeline_stages` exposes stage names from `PipelineStageName` enum.

## Per-Stage Behavior

### Stage 1 — DataStage

| Field | Value |
|-------|-------|
| **File** | `tradingbot/pipeline/data_stage.py` |
| **Input** | `CycleContext.market` |
| **Output** | `ctx.raw_ohlcv` |
| **Failure** | Insufficient bars → pipeline stops |
| **Evidence** | `DataStage.run()` — `min_bars` from PA config (default 80), `fetch_bars` (default 300) |

### Stage 2 — IndicatorStage

| Field | Value |
|-------|-------|
| **File** | `tradingbot/pipeline/indicator_stage.py` |
| **Implementation** | `TechnicalIndicatorEngine.enrich_for_market()` → `domain.indicators.compute_indicators` |
| **Output** | `ctx.enriched_ohlcv` |

### Stage 3 — SignalStage

| Field | Value |
|-------|-------|
| **File** | `tradingbot/pipeline/signal_stage.py` |
| **Behavior** | Uses **closed bar only** (`exclude_forming_bar`); deduplicates same bar timestamp |
| **Registry** | `build_strategy_registry()` product (default: shadow-wrapped router → PA) |
| **Output** | `ctx.signal` or pipeline stop (HOLD / None) |

### Stage 4 — SignalFilterStage

| Field | Value |
|-------|-------|
| **File** | `tradingbot/pipeline/signal_filter_stage.py` |
| **Implementation** | `WinnerPopulationSignalQualityFilter` (WPSQF) |
| **Default** | **DISABLED** — `resolve_signal_filter_mode()` returns OFF unless `TRADINGBOT_SIGNAL_FILTER=WPSQF` |
| **When OFF** | `run()` returns `True` immediately (pass-through) |

**Evidence:** `tradingbot/services/signal_filter_mode.py`

### Stage 5 — RiskStage

| Field | Value |
|-------|-------|
| **File** | `tradingbot/pipeline/risk_stage.py` |
| **Implementation** | `RiskGate.evaluate(signal, portfolio_snapshot)` |
| **Output** | `ctx.risk`; sets `adjusted_lot` on signal when approved |
| **Failure** | Logs rejection event; pipeline stops |

### Stage 6 — ExecutionStage

| Field | Value |
|-------|-------|
| **File** | `tradingbot/pipeline/execution_stage.py` |
| **Implementation** | `IOrderExecutor.execute(signal, lot)` → `Mt5ExecutionAdapter` |
| **Output** | `ctx.execution` |

## Global Cycle Wrappers (Not Pipeline Stages)

Before/after per-market pipeline, `run_global_cycle()` also:

1. MT5 health check
2. `update_all()` market data
3. Build `htf_bias_map` (H4 for M5 entries)
4. Skip all market cycles if `entries_frozen()`
5. After all markets: `_manage_positions()` → `Mt5PositionManager.manage_all()`

**Evidence:** `tradingbot/kernel/trading_kernel.py::run_global_cycle`

## Pipeline Stop Semantics

Each stage's `run()` returns `bool`. **`False` stops the pipeline** for that market without running subsequent stages.

**Evidence:** `TradingKernel.run_market_cycle()` loop

## Active vs Bypassed Stages

| Stage | Default live |
|-------|--------------|
| Data | ACTIVE |
| Indicators | ACTIVE |
| Signal | ACTIVE |
| SignalFilter | **BYPASSED** (configured OFF) |
| Risk | ACTIVE |
| Execution | ACTIVE (no-op log in dry-run) |

## Backtest Pipeline

Same six stages via `BacktestEngine` with `BacktestRiskGate` and `SimulatedBroker`.

**Evidence:** `tradingbot/backtest/engine.py`

## Unknowns

- Whether operator enables WPSQF via env
- Custom `extra_stages` — none on default `LiveRunner` path

## Change Impact

`tradingbot/kernel/trading_kernel.py`, `tradingbot/pipeline/*.py`

## Verification

```python
# tradingbot/kernel/trading_kernel.py L84-91 — pipeline list
# Each tradingbot/pipeline/*_stage.py — run() behavior
```

# Phase 10.1 — Architecture Audit

## Current Signal Path (Pre-10.1)

```
TradingKernel.run_market_cycle()
  → DataStage          (IMarketDataProvider.get_ohlcv)
  → IndicatorStage     (IIndicatorEngine.enrich)
  → SignalStage        (IStrategyRegistry.generate_signal → ctx.signal)
  → RiskStage          (IRiskGate.evaluate → ctx.risk)
  → ExecutionStage     (IOrderExecutor.execute → ctx.execution)
```

Entry points: `TradingKernel.run_global_cycle()`, `run_market_cycle()`, `run_forever()`  
Bootstrap: `tradingbot/application/bootstrap.py` → `build_kernel_live()` / `build_kernel_with_strategies()`

## Phase 10 Gap (Sidecar)

Phase 10 (`tradingbot/ml/shadow/`) ran a **parallel loop** outside the kernel:
`MLAdapter → ShadowKernelBridge → JSON logs`.  
`TradingKernel` was never invoked; ML never populated `CycleContext.signal`.

## Best ML Injection Point (Phase 10.1)

| Layer | Change? | Approach |
|-------|---------|----------|
| `TradingKernel` | **NO** | Inject dependencies at construction only |
| `SignalStage` | **NO** | Already calls `IStrategyRegistry.generate_signal` |
| `IStrategyRegistry` | **YES (new impl)** | `CompositeStrategyRegistry` = Legacy + `MLShadowStrategy` |
| `RiskStage` | **NO** | Uses injected `IRiskGate` (real `RiskGate`) |
| `ExecutionStage` | **NO** | Inject `ShadowExecutionGuard` as `IOrderExecutor` |
| `Mt5ExecutionAdapter` | **NO** | Not used in shadow replay |

**Injection site:** `tradingbot/ml/integration/kernel_builder.py` (new) — not `application/bootstrap.py`.

## Files That Change (10.1)

| File | Action |
|------|--------|
| `tradingbot/ml/integration/*` | **NEW** — ML strategy, composite registry, shadow executor, replay data, runner |
| `tradingbot/ml/data/paths.py` | **ADD** kernel shadow run paths |
| `scripts/run_ml_kernel_shadow.py` | **NEW** CLI |
| `tests/test_ml_phase10_1_kernel_bridge.py` | **NEW** |
| `docs/phase10_1_architecture_audit.md` | **NEW** |

## Files That Must NOT Change

- `tradingbot/kernel/trading_kernel.py`
- `tradingbot/adapters/risk_gate.py`
- `tradingbot/adapters/mt5_execution.py`
- `tradingbot/pipeline/*` (all stages)
- `tradingbot/ml/features/*` (main pipeline)
- Dataset / training pipelines

## Feature Flags

| Env | Purpose |
|-----|---------|
| `ENABLE_ML_SHADOW=true` | Composite registry prefers ML signal |
| `ML_SHADOW_MODE=true` | Execution guard blocks orders, logs virtual orders |

## Target Flow (10.1)

```
ReplayMarketDataAdapter (bar-by-bar)
  → TradingKernel.run_market_cycle()   [unchanged logic]
      → SignalStage
          → CompositeStrategyRegistry
              → MLShadowStrategy (Phase 9.9)  ← ML enters ctx.signal
              → LegacyStrategyRegistry (fallback)
      → RiskStage → real RiskGate.evaluate()
      → ExecutionStage → ShadowExecutionGuard (no order_send)
  → kernel_run_v1/*.json
```

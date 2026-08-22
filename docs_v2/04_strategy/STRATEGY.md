# Strategy System

## Status

- **Status:** VERIFIED
- **Last Verified:** 2026-08-22
- **Verification Method:** Factory selection logic, registry implementations, ACTIVE_STRATEGIES
- **Verified against commit:** `57bf778c23cefffe508bb49079688b177796f67e`

## Scope

Strategy implementations, selection, and **reachability** on the default live path.

## Strategy Factory

**Entry:** `tradingbot/ml/integration/factory.py::build_strategy_registry()`

**Selection priority** (when `USE_ML_KERNEL` env is set — daemon sets it):

1. ML kernel (if `USE_ML_KERNEL=true` and shadow gate allows)
2. **`MultiEngineRouterRegistry`** if `MULTI_ENGINE_ROUTER_ENABLED` (default true)
3. `AdaptiveRegimeStrategyRegistry` if `ADAPTIVE_REGIME_ENABLED`
4. `VolRegimeStrategyRegistry` if `VOL_REGIME_ENABLED`
5. ML registry if ML enabled after gate
6. `UnconfiguredEngineRegistry` if `USE_ML_KERNEL` unset and vol off
7. `LegacyStrategyRegistry` (+ optional shadow wrap)

**Evidence:** `factory.py:176–238`

## Default Live Selection (Verified)

```text
build_strategy_registry()
  → _maybe_wrap_shadow(
       MultiEngineRouterRegistry(config),
       ...
     )
```

Daemon sets: router **on**, adaptive **off**, vol **off**, ML kernel **off**, ML shadow **on**.

## MultiEngineRouter Behavior

**File:** `tradingbot/adapters/multi_engine_router.py`

Always calls three inner registries:

- `_pa` → `LegacyStrategyRegistry` (Price Action)
- `_vol` → `VolRegimeStrategyRegistry`
- `_adaptive` → `AdaptiveRegimeStrategyRegistry`

**Selection:**

- If valid PA signal → select PA (`ENGINE_PA`)
- Else if **not** `PA_PRODUCTION_LOCK` → VOL, then Adaptive
- With lock (default) → VOL/Adaptive valid signals are **logged but not selected**

**Evidence:** `multi_engine_router.py:114–128`; `pa_production_lock.py`

## Active Strategy: Price Action (SMC)

| Field | Value |
|-------|-------|
| **Registry** | `LegacyStrategyRegistry` |
| **Manager** | `engine.strategy_manager.StrategyManager` |
| **Implementation** | `engine.strategies.price_action_strategy.PriceActionStrategy` |
| **Enabled flag** | `ACTIVE_STRATEGIES["priceaction"] = True` |
| **Preset (M5)** | `gold_ny_sweep` / `london_sweep` |
| **Session** | NY 15–16 UTC (unless demo session override) |
| **Symbol** | XAUUSD (normalized from `XAUUSD_i`) |

**Evidence:** `config/strategies.py`; `pa_symbol_tf_presets.py`; `price_action_strategy.py`

## Strategy Inventory and Status

| Strategy / Engine | Implementation | Default live status |
|-------------------|----------------|---------------------|
| Price Action | `PriceActionStrategy` | **ACTIVE** (selected) |
| MultiEngineRouter | `MultiEngineRouterRegistry` | **ACTIVE** (wrapper) |
| VOL_REGIME | `VolRegimeStrategyRegistry` | **SHADOW** (probed, not selected) |
| ADAPTIVE_REGIME | `AdaptiveRegimeStrategyRegistry` | **SHADOW** |
| ML Kernel | `MLKernelRegistry` | **DISABLED** |
| ML Shadow observer | `ShadowStrategyRegistry` | **SHADOW** (log-only) |
| Unconfigured | `UnconfiguredEngineRegistry` | **UNREACHABLE** (with daemon env) |
| Stub strategies | `StubStrategies` | **UNREACHABLE** (demo only) |
| 14 disabled names in ACTIVE_STRATEGIES | N/A | **DISABLED** — no strategy files in `engine/strategies/` |

## Disabled Strategies

`tradingbot/config/strategies.py::ACTIVE_STRATEGIES` — only `priceaction: True`.

## Signal Output Format

Strategies produce `TradingSignal` via `signal_helpers.build_trading_signal()`:

- Direction: BUY / SELL / HOLD
- Confidence, SL, TP, lot_size, metadata

**Evidence:** `tradingbot/domain/signal_helpers.py`; `legacy_strategy_registry.py`

## Alternate Engine Activation (Available, Not Default)

Operators can enable by environment (requires restart):

- `ADAPTIVE_REGIME_ENABLED=true` **and** disable router or PA lock behavior changes selection
- `VOL_REGIME_ENABLED=true` with router off → standalone VOL
- `USE_ML_KERNEL=true` → ML path (subject to shadow gate)

Exact combination outcomes should be verified before production use.

## Unknowns

- Operator `.env` engine overrides
- Behavior when `PA_PRODUCTION_LOCK=false`

## Change Impact

`tradingbot/ml/integration/factory.py`, `tradingbot/adapters/*strategy*`, `engine/strategies/`, `config/strategies.py`, `config/pa_symbol_tf_presets.py`

## Verification

Read `build_strategy_registry`, `MultiEngineRouterRegistry.generate_signal`, `ACTIVE_STRATEGIES`.

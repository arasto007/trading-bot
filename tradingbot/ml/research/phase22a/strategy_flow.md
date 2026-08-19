# Phase 22A — Strategy Flow

## Strategy Registry Selection

```python
# factory.build_strategy_registry()
if USE_ML_KERNEL:
    return MLKernelRegistry(legacy, adapter=KernelAdapter)
else:
    return LegacyStrategyRegistry(config)
```

## Active Production Strategies

### 1. ML Kernel Stack (Primary when USE_ML_KERNEL=true)

| Component | Regime | Direction Source |
|-----------|--------|------------------|
| Range phase9_9 | RANGE | LogisticRegression proba vs 0.55/0.45 |
| Trend RF v41 | TREND | RandomForest + rule_fn variant A |
| DecisionOrchestrator | ALL | Routes by regime, blocks HIGH_VOLATILITY/NO_TRADE |

**Inputs:** closed OHLCV + enriched indicators + unified ML features  
**Outputs:** `TradingSignal` with direction, confidence, SL, TP, metadata[`signal_source=ml_kernel`]

### 2. Legacy Price Action (Fallback + USE_ML_KERNEL=false)

| Strategy Module | Timeframe Presets | File |
|-----------------|-------------------|------|
| M5 London Sweep | `gold_ny_sweep` | `domain/gold_strategies/m5_london_sweep.py` |
| M5 Scalp | alternate M5 | `m5_scalp.py` |
| M15 Intraday | `atr_tight_gold` | `m15_intraday.py` |
| H4 Swing | `gold_h4_swing` | `h4_swing.py` |

Routed via `domain/gold_strategies/router.py` inside `engine/strategies/price_action_strategy.py`.

**Config source:** `tradingbot/config/pa_symbol_tf_presets.py` + `price_action.py`

**ACTIVE_STRATEGIES:** only `priceaction: True` (`config/strategies.py`)

## Signal Generation — Legacy Path

```
LegacyStrategyRegistry.generate_signal()
  → StrategyManager.generate_combined_signals(df, symbol, tf)
      → PriceActionStrategy.analyze()
      → gold router picks sub-strategy by preset
  → build_trading_signal() — ATR SL/TP, confidence filter
```

## Signal Generation — ML Path

```
MLKernelRegistry.generate_signal()
  → KernelAdapter (see ml_pipeline.md)
  → on failure: same legacy path above
```

## Activation Conditions

| Gate | Location | Rule |
|------|----------|------|
| Closed bar only | SignalStage | `exclude_forming_bar` + dedupe last_ts |
| Min bars | DataStage | default 80 |
| Min confidence | Legacy PA / DecisionPolicy | preset + MIN_CONFIDENCE |
| Regime block | Orchestrator | NO_TRADE, HIGH_VOLATILITY → HOLD |
| ML quality | TradeQualityAdapter | score < threshold → HOLD |
| Phase 19C | apply_profitability_filters | RSI/ADX bands |
| Risk gates | RiskGate | spread, news, friday, htf, meta |

## Priority & Routing

1. **Regime detection** → TREND vs RANGE vs blocks (in ML context builder)
2. **Engine selection** — `select_engine(regime)` in decision_engine
3. **No multi-strategy vote in ML mode** — single orchestrator decision
4. **Legacy mode** — StrategyManager may combine; currently single priceaction

## Combination Logic

- ML mode: **no combination** — one UnifiedSignal
- Legacy: `generate_combined_signals` supports weights; only priceaction loaded

## Decision Logic Summary

```
IF new closed bar:
  IF ML enabled AND health OK:
    unified = orchestrator(range|trend)
    IF quality AND risk AND filters pass:
      emit BUY/SELL with SL/TP
    ELSE HOLD
  ELSE IF legacy fallback:
    PA strategy preset for TF
    IF confidence >= threshold:
      emit signal
  RiskGate filters
  Execute if allowed
```

## Per-Timeframe Live Presets (from check_live_setup)

| TF | Preset | Session | max_day |
|----|--------|---------|---------|
| M5 | gold_ny_sweep | 10-17 | 3 |
| M15 | atr_tight_gold | 7-21 | 4 |
| H4 | gold_h4_swing | 0-24 | 2 |

## HTF Alignment

- `TradingKernel._build_htf_bias_map()` computes bias per symbol:TF
- RiskGate `check_htf_alignment()` uses preset flags REQUIRE_HTF_ALIGNMENT_*

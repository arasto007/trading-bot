# Signal Flow

## Status

- **Status:** VERIFIED
- **Last Verified:** 2026-08-22
- **Verification Method:** Traced pipeline + strategy + risk from market data to order intent
- **Verified against commit:** `57bf778c23cefffe508bb49079688b177796f67e`

## Scope

End-to-end path from market data to **approved trading signal** on the default live path (before execution).

## High-Level Flow

```text
MT5 OHLCV (M5)
  → DataStage (raw_ohlcv)
  → IndicatorStage (enriched_ohlcv + 22 technical columns)
  → exclude_forming_bar (in SignalStage)
  → Strategy registry.generate_signal()
  → [optional WPSQF — OFF by default]
  → RiskGate.evaluate()
  → ExecutionStage (if approved)
```

## Detailed Signal Generation (Price Action)

### 1. Market data input

- Closed M5 bars only in `SignalStage`
- Same-bar dedup: second call on identical closed timestamp returns False (no re-fire)

**Evidence:** `signal_stage.py`

### 2. Router layer

```text
MultiEngineRouterRegistry.generate_signal(market, closed_df)
  ├── LegacyStrategyRegistry → StrategyManager.generate_combined_signals()
  │     └── PriceActionStrategy.generate_signals()
  ├── VolRegimeStrategyRegistry (parallel, not selected under lock)
  └── AdaptiveRegimeStrategyRegistry (parallel, not selected under lock)
```

If PA returns valid BUY/SELL → that signal is selected and tagged `router_engine=PA`.

**Evidence:** `multi_engine_router.py`

### 3. Price Action internal gates

| Gate | Location | Rejection result |
|------|----------|------------------|
| Empty / short data | `PriceActionStrategy` | Empty signal list (WAIT) |
| Symbol/TF not in PA allowlist | `is_pa_cell_enabled()` | Empty |
| Session window | `filter_policy.is_session_filter_enabled()` | HOLD + telemetry |
| Kill zone (if configured) | `is_kill_zone()` | HOLD |
| No gold setup / low confidence | `evaluate_gold_setup()` | HOLD + forensic log |
| Duplicate PA signal | `pa_hardening.is_duplicate_pa_signal()` | HOLD |
| PA hardening | `pa_hardening` module | HOLD |

**Evidence:** `engine/strategies/price_action_strategy.py`

### 4. Signal normalization

`build_trading_signal()` in `signal_helpers.py`:

- Resolves broker symbol, PA preset, min confidence
- Computes confidence (strategy metadata + SMA/ATR/volume heuristics)
- Computes SL/TP via `compute_sl_tp()` (tier-aware for confluence)

Output: `TradingSignal` or None.

### 5. Shadow observation (non-blocking)

If `ENABLE_ML_SHADOW=true`, `ShadowStrategyRegistry` calls `ShadowObserver.observe_cycle()` after inner signal — **does not change signal**.

**Evidence:** `shadow_strategy_registry.py`

## Post-Signal Filters

### SignalFilterStage (WPSQF)

- **Default:** OFF — stage passes through
- When ON: `WinnerPopulationSignalQualityFilter.evaluate()` may nullify signal

**Evidence:** `signal_filter_stage.py`, `signal_filter_mode.py`

### RiskGate (mandatory for execution)

See `RISK.md`. Key PA-specific gate: **meta-labeler** when `should_gate()` true.

Meta observer mode (`META_OBSERVER_MODE=true`): scores and logs **would_reject** but never blocks.

**Evidence:** `risk_gate.py::apply_pa_meta_decision`

## Signal Outcomes

| Outcome | Pipeline effect |
|---------|-----------------|
| WAIT / HOLD / None | Pipeline stops at SignalStage or filter; no risk/execution |
| BUY / SELL approved by RiskGate | Proceeds to ExecutionStage |
| BUY / SELL rejected by RiskGate | Pipeline stops; rejection logged |

## HTF Context (Not Signal, Used by Risk)

`TradingKernel` builds `htf_bias_map` from H4 OHLCV for M5 entries. M5 preset has `REQUIRE_HTF_ALIGNMENT_M5: False` — bias computed but HTF gate **off** for M5 by default.

**Evidence:** `trading_kernel.py::_build_htf_bias_map`; `pa_symbol_tf_presets.py`

## Indicators vs PA Structure

- **IndicatorStage** always computes 22 technical columns
- **PA signal** primarily uses `enrich_price_action` + gold setup logic — not all indicator columns drive entry
- **Confidence** may use SMA/ATR/volume from enriched frame

Status: technical indicators = **CALCULATED**; many = **CALCULATED_BUT_UNUSED** for PA entry logic.

## Unknowns

- Meta-labeler rejection rate on deployment (requires runtime journal)
- WPSQF if enabled by operator

## Change Impact

`tradingbot/pipeline/signal*.py`, `engine/strategies/price_action_strategy.py`, `domain/signal_helpers.py`, `adapters/multi_engine_router.py`, `adapters/risk_gate.py`

## Verification

Step through `SignalStage.run` → `generate_signal` → `RiskStage.run`.

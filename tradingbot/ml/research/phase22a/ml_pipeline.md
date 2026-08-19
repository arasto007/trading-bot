# Phase 22A — ML Pipeline

## Active Models (Production Live)

| Model | Registry ID | Artifact Path | Active When |
|-------|-------------|---------------|-------------|
| **Range Phase 9.9** | `phase9_9` | `data/ml/research/phase9_9_best/model.pkl` | Always in registry |
| **Trend RF v41** | `trend_rf_v41` | `data/ml/research/trend_rf_bundle/model.pkl` (v41) | `TREND_MODEL_VERSION=v41` (default) |
| **Trend RF v40** | `trend_rf_v40` | same bundle root, version v40 | Rollback via `TREND_MODEL_VERSION=v40` |
| **Meta-Labeler M15** | N/A (risk gate) | `data/models/meta_labeler_m15.pkl` | M15 entries when `should_gate()` |
| **Meta-Labeler M5** | N/A | `data/models/meta_labeler_m5.pkl` | M5 gating |
| **Meta-Labeler H4** | N/A | `data/models/meta_labeler_h4.pkl` | H4 gating |

## Inactive / Legacy Models

| Model | Status | Evidence |
|-------|--------|----------|
| Phase 9.6 best | Research artifact | `phase9_6_model_path()` — not in EngineRegistry.build_default |
| Training model_v* | Historical training | `training_model_path()` — not loaded live |
| Legacy meta_labeler.pkl | Fallback only | `MetaLabeler` loads per-TF first |
| Paper/shadow engines | Isolated | `ml/paper_trading/`, shadow runners |
| Phase 13.x standalone routers | Superseded | Unified via DecisionOrchestrator |

## Enable Flag

```python
# tradingbot/ml/integration/config.py
USE_ML_KERNEL=true  # .env → is_ml_kernel_enabled()
```

When false: entire path uses `LegacyStrategyRegistry` only.

## Loading Pipeline

```
build_strategy_registry()
  → normalize_ml_base_dir(BASE_DIR)  # project root → data/ml/
  → build_ml_kernel_stack()
      → PipelineCache.get_registry()
          → EngineRegistry.build_default()
              → load_phase9_9_bundle() → Phase99EngineWrapper
              → load_trend_bundle(v40) → TrendRfEngineWrapper
              → load_trend_bundle(v41) → TrendRfV41Engine
      → build_range_recovery_orchestrator() OR DecisionOrchestrator
      → build_production_calibrated_adapter()
      → build_mapped_production_risk()
      → TradeQualityAdapter
  → KernelAdapter(deps)
  → MLKernelRegistry(legacy, adapter)
```

## Scaler + Feature Order

| Bundle | Scaler | Feature Order |
|--------|--------|---------------|
| phase9_9 | `scaler.pkl` | `feature_order.json` (ema50_slope, candle_direction, structure_distance) |
| trend v40/v41 | `scaler.pkl` in bundle | `feature_order.json` + TREND_ML_FEATURE_COLUMNS |
| Meta | embedded in .pkl | `capture_entry_features()` at risk time |

Loaded via:
- `load_phase9_9_bundle()` → joblib model + scaler
- `load_trend_bundle(version=...)` → TrendRfBundle dataclass

## Prediction Pipeline (per closed bar)

1. **Health gate** — `run_pre_decision_health()` checksums, feature presence
2. **Unified frame** — `build_unified_frame(candles, dataset)` from DatasetStore v2
3. **Market context** — `build_market_context(row, range_engine, trend_engine)`
4. **Regime** — embedded in context from engines
5. **Engine select** — `select_engine(regime)` → phase9_9 (RANGE) or trend_rf_v41 (TREND)
6. **Decision** — `DecisionOrchestrator.decide()` + ConfidenceEngine
7. **Calibration** — `CalibratedDecisionAdapter` (Phase 14.6 recovery)
8. **Adaptive risk** — `AdaptiveRiskEngine` caps risk %
9. **Trade quality** — `TradeQualityEngine` threshold filter
10. **Profitability filters** — Phase 19C RSI/ADX from `.env`
11. **Map to signal** — SL/TP from ATR in `map_unified_to_trading_signal()`

## Thresholds & Filters

| Source | Parameters |
|--------|------------|
| `.env` | `ENABLE_RSI_FILTER`, `ENABLE_ADX_FILTER`, `RSI_MIN/MAX`, `ADX_MIN/MAX` |
| DecisionPolicy | `min_confidence` in orchestrator |
| Phase 9.9 config | `buy_threshold=0.55`, `sell_threshold=0.45` |
| Trend bundle | `threshold` in metadata (TREND_ML_THRESHOLD default) |
| TradeQuality | `DEFAULT_QUALITY_THRESHOLD` (phase14_7) |
| Meta | `META_LABEL_THRESHOLD` per TF preset |

## Calibration & Confidence Mapping

- `build_production_calibrated_adapter()` wraps orchestrator
- `build_mapped_production_risk()` maps confidence → risk size
- Phase 15H confidence mapping in production adapter chain

## Bundle Validation

- `verify_bundle_integrity()` — phase9_9 feature order + predict test
- `validate_trend_checksum()` — SHA256 vs metadata
- `verify_ml_live_ready.py` — pre-LIVE gate
- `health_gate.require_health()` — per-decision

## Rollback

```python
# phase17d/versioning.py
TREND_MODEL_VERSION=v40  → resolve_active_trend_engine_id() → trend_rf_v40
# No code change; env only
```

## Caching

| Cache | Class | Purpose |
|-------|-------|---------|
| Registry singleton | PipelineCache | EngineRegistry, bundles |
| Feature cache | PipelineCache._feature_cache | Unified frame by bar key |
| Prediction cache | PipelineCache._prediction_cache | UnifiedSignal by row_key |

Thread-safe via `threading.Lock`.

## Monitoring Outputs (live)

- `data/ml/live/kernel_decisions.jsonl`
- `data/ml/live/decision_latency.jsonl`
- `data/ml/live/engine_health.json`
- `data/ml/live/health_status.json`

## Fallback Triggers

`MLKernelRegistry` catches `KernelFallbackError` → increments `fallback_count` → `LegacyStrategyRegistry.generate_signal()`.

Triggers: missing engines, empty unified frame, health fail, pipeline timeout (>500ms).

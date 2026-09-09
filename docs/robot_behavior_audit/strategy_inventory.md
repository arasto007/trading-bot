# Strategy Inventory

> **HISTORICAL (2026-07 audit).** Claims Adaptive/VOL as the live default.
> Current live truth is `docs_v2/` (MultiEngineRouter + `PA_PRODUCTION_LOCK` → Price Action).
> Do not treat this file as the active live contract. Historical analysis below is unchanged.

**Repository:** `TradingBot new`  
**Live selection logic:** `tradingbot/ml/integration/factory.py` → `build_strategy_registry()`

Priority order:
1. ADAPTIVE_REGIME (if enabled, ML off) ← **current default**
2. VOL_REGIME (if adaptive off, ML off)
3. ML Kernel (if USE_ML_KERNEL=true)
4. Legacy Price Action / Unconfigured

---

## Production Engines (Live-Selectable)

### 1. ADAPTIVE_REGIME (Active Default)

| Field | Value |
|-------|-------|
| **Market type** | Multi: TREND + RANGE + HIGH_VOL + CONFLUENCE |
| **Timeframes** | M5 signal; H1 trend from frame prep |
| **Features** | atr_pct, ema20/50, h1_trend, rsi14, hour_utc, spread_proxy (frame only) |
| **Reachable live?** | **YES** — `AdaptiveRegimeStrategyRegistry` |
| **Recent replay/backtest** | `data/backtest_last.json`: 13 trades, PF 0.32, -30.14% (14d confluence) |

**Sub-strategies (inside `adaptive_regime.py`):**

| Sub-ID | Type | When used | Signal source |
|--------|------|-----------|---------------|
| CONFLUENCE | TREND+VOL | Default mode; atr 30–70% | MTF + VOL agree |
| HIGH_VOL_MOMENTUM | BREAKOUT/MOMENTUM | atr ≥ 72%; HVM+MTF agree | `_high_vol_momentum_signal()` |
| MTF_TREND | TREND | Non-confluence mode only | `_multi_tf_trend_signal()` |
| VOL_REGIME sub | VOL_REGIME | Non-confluence mode | `_volatility_regime_signal()` |

**Registry file:** `tradingbot/adapters/adaptive_regime_strategy_registry.py`  
**Logic file:** `tradingbot/strategies/adaptive_regime.py`  
**Frame prep:** `tradingbot/strategies/vol_regime_signal.py` → `edge_discovery_round2._prepare_frame_round2()`

---

### 2. VOL_REGIME (Standalone — Fallback)

| Field | Value |
|-------|-------|
| **Market type** | VOL_REGIME (medium volatility scalp) |
| **Timeframes** | M5 only |
| **Features** | atr_pct 30–70%, EMA structure from L2 frame |
| **Reachable live?** | **NO** while ADAPTIVE_REGIME enabled (factory priority) |
| **Recent replay** | 14d backtest: 38 trades, PF 0.55, -33.34% (conversation evidence) |

**Registry:** `tradingbot/adapters/vol_regime_strategy_registry.py`  
**Signal logic:** `tradingbot/strategies/vol_regime_signal.py`

---

### 3. ML Kernel Stack

| Field | Value |
|-------|-------|
| **Market type** | Routed: RANGE / TREND / HIGH_VOL / NO_TRADE |
| **Timeframes** | M5 primary; multi-TF features in pipeline cache |
| **Features** | Unified ML frame: regime, trend v41, calibrated probabilities |
| **Reachable live?** | **NO** — `USE_ML_KERNEL=false` in `.env.example` and daemon default |
| **Recent replay** | NOT PROVEN in this audit |

**Components:**
- `tradingbot/ml/integration/kernel_adapter.py` — `KernelAdapter`
- `tradingbot/ml/decision_engine/orchestrator.py` — `DecisionOrchestrator`
- `tradingbot/ml/phase15a/engine_registry.py` — engine registry

---

### 4. phase9_9 Range Engine (ML Sub-Engine)

| Field | Value |
|-------|-------|
| **Market type** | RANGE |
| **Timeframes** | M5 (ML pipeline) |
| **Features** | Range model features via `PipelineCache` |
| **Reachable live?** | **NO** — ML kernel off |
| **Recent replay** | NOT PROVEN |

**ID:** `RANGE_ENGINE_ID` / `phase9_9` in `engine_registry.py` L108–115

---

### 5. Trend RF v41

| Field | Value |
|-------|-------|
| **Market type** | TREND |
| **Timeframes** | M5 + higher TF features |
| **Features** | trend_features, phase17b top5, ema slopes |
| **Reachable live?** | **NO** — ML only; `.env` TREND_MODEL_VERSION not read by adaptive |
| **Recent replay** | NOT PROVEN |

**ID:** `TREND_ENGINE_V41_ID` in `engine_registry.py` L138–155

---

### 6. Trend RF v40

| Field | Value |
|-------|-------|
| **Market type** | TREND |
| **Reachable live?** | **NO** — ML fallback when v41 bundle missing |
| **Recent replay** | NOT PROVEN |

---

### 7. Range Recovery Logic

| Field | Value |
|-------|-------|
| **Market type** | RECOVERY / RANGE |
| **File** | `tradingbot/ml/research/phase15i/recovery_adapter.py` |
| **Reachable live?** | **NO** — wired in ML stack `build_range_recovery_orchestrator()` |
| **Recent replay** | NOT PROVEN |

---

### 8. Legacy Price Action (SMC)

| Field | Value |
|-------|-------|
| **Market type** | TREND / RANGE / SCALP (SMC setups) |
| **Timeframes** | M5, M15, H4 (configurable) |
| **Features** | Structure, BOS, liquidity sweeps — `tradingbot/domain/price_action.py` |
| **Reachable live?** | **NO** — requires adaptive off, vol off, ML off or legacy fallback |
| **Recent replay** | NOT PROVEN |

**Registry:** `LegacyStrategyRegistry` → `engine/strategy_manager.py`  
**Config:** `tradingbot/config/strategies.py` — `priceaction=True`

---

## L2 Research Hypotheses (edge_discovery_round2)

Defined in `HYPOTHESES_R2` — not all used by adaptive:

| Hypothesis | Type | Used by adaptive? |
|------------|------|-------------------|
| `_multi_tf_trend_signal` | TREND | **YES** |
| `_volatility_regime_signal` | VOL_REGIME | **YES** |
| `_high_vol_momentum_signal` (in adaptive_regime.py) | MOMENTUM | **YES** |
| PULLBACK_VWAP | TREND | **NO** |
| LONDON_KZ | SESSION | **NO** |
| NY_REVERSAL | REVERSAL | **NO** |
| BOS_RETEST | BREAKOUT | **NO** |
| SPREAD_SESSION | FILTER | **NO** |

---

## Regime Router (ML Only)

| Field | Value |
|-------|-------|
| **File** | `tradingbot/ml/decision_engine/strategy_selector.py` |
| **Function** | `select_engine()`, `routing_action()` |
| **Reachable live?** | **NO** (ML off) |

---

## Engine Selection Summary Table

| Engine | Market Type | TF | Live Reachable | Backtest Evidence |
|--------|-------------|-----|----------------|-------------------|
| ADAPTIVE_REGIME | Multi-regime | M5+H1 | **YES** | PF 0.32, -30% (14d) |
| VOL_REGIME | VOL_REGIME | M5 | Shadowed | PF 0.55, -33% (14d) |
| ML Kernel | Routed | M5+ | NO | NOT PROVEN |
| phase9_9 range | RANGE | M5 | NO | NOT PROVEN |
| trend v41 | TREND | M5+ | NO | NOT PROVEN |
| trend v40 | TREND | M5+ | NO | NOT PROVEN |
| Recovery | RECOVERY | M5 | NO | NOT PROVEN |
| Price Action | SMC | M5/15/H4 | NO | NOT PROVEN |
| L2 unused hypotheses | Various | M5 | NO | NOT PROVEN |

---

## Factory Evidence

```python
# tradingbot/ml/integration/factory.py build_strategy_registry()
if adaptive_on and not ml_enabled:
    return AdaptiveRegimeStrategyRegistry(legacy_config)
if vol_regime_on and not ml_enabled:
    return VolRegimeStrategyRegistry(legacy_config)
if ml_enabled:
    return MLKernelRegistry(...)
```

**Daemon default:** `scripts/start_live_daemon.ps1` sets `ADAPTIVE_REGIME_ENABLED=true`, `USE_ML_KERNEL=false` if unset.

**Live symbols/TF forced:** `get_live_config()` sets `SYMBOLS=['XAUUSD']`, `TIMEFRAMES=['5m']` when adaptive or vol on.

# Duplicate Work Detection

**Priority:** Highest  
**Repository:** `TradingBot new`  
**Default live path:** `AdaptiveRegimeStrategyRegistry` → `adaptive_regime.py` → `edge_discovery_round2.py`

This report lists every place the same concept is computed more than once, whether values match, and which copy actually controls live trading.

**Legend:**
- **LIVE-ADAPTIVE** — used when `ADAPTIVE_REGIME_ENABLED=true` (current default)
- **LIVE-KERNEL** — pipeline stages all signals pass through
- **LIVE-ML** — only when `USE_ML_KERNEL=true`
- **RESEARCH** — offline / not executed in current live config

---

## 1. ADX (Average Directional Index)

| # | Implementation | File / Function | Used in live? |
|---|----------------|-----------------|---------------|
| 1 | Kernel indicators | `tradingbot/domain/indicators.py` → `add_adx()` | LIVE-KERNEL (IndicatorStage) |
| 2 | Scalar ADX for filters | `tradingbot/domain/market_filters.py` → `compute_adx()` | LIVE-PA only (skipped for adaptive) |
| 3 | WPSQF numpy ADX | `tradingbot/services/wpsqf_features.py` → `_fast_adx()` | LIVE-KERNEL if WPSQF ON (default OFF) |
| 4 | ML regime features | `tradingbot/ml/research/regime_detector/regime_features.py` → `_adx_series()` | LIVE-ML only |
| 5 | ML trend features | `tradingbot/ml/research/trend_strategy/trend_features.py` → `_adx_series()` | LIVE-ML only (duplicate of #4) |
| 6 | L2 research | `tradingbot/ml/research/live_l2/edge_discovery.py` → `_adx()` | RESEARCH |

| Comparison | First vs Second | Identical? | Live winner |
|------------|-----------------|------------|-------------|
| #1 vs #3 | Rolling ADX vs numpy fast ADX | **Slightly different** — same formula family, different code paths | **Neither for adaptive signals** — adaptive does not read ADX for entry |
| #1 vs #2 | Series column vs last-bar scalar | **Slightly different** — same window, different aggregation | **#1** if PA filters run; **none** for ADAPTIVE (filters skipped) |
| #4 vs #5 | regime vs trend feature builders | **Identical logic** — copy-paste | LIVE-ML only |

**Live ADAPTIVE verdict:** ADX is computed in IndicatorStage but **not used** by `adaptive_regime.py` signal logic. ADX gates in `.env` (`ENABLE_ADX_FILTER`) apply to ML path only (`ml/phase19c/filters.py`).

---

## 2. ATR (Average True Range)

| # | Implementation | File / Function | Used in live? |
|---|----------------|-----------------|---------------|
| 1 | Kernel indicators | `tradingbot/domain/indicators.py` → `add_atr()` | LIVE-KERNEL |
| 2 | ATR percentile rank | `tradingbot/domain/market_filters.py` → `atr_percentile()` | LIVE-PA (skipped adaptive) |
| 3 | Risk lot fallback | `tradingbot/domain/risk_logic.py` → `atr_from_ohlcv()` | LIVE-KERNEL RiskGate |
| 4 | SL/TP helper | `tradingbot/domain/signal_helpers.py` → `_atr()` | **LIVE-ADAPTIVE** (compute_sl_tp) |
| 5 | PA strategy | `tradingbot/domain/price_action.py` → `_atr()` | LIVE-PA only |
| 6 | WPSQF | `tradingbot/services/wpsqf_features.py` → `_fast_atr_percentile()` | WPSQF if ON |
| 7 | Vol frame prep | `tradingbot/ml/research/live_l2/edge_discovery_round2.py` → `_prepare_frame_round2()` | **LIVE-ADAPTIVE** (atr_pct column) |
| 8 | ML regime/trend | `regime_features.py`, `trend_features.py` → `_atr_series()`, `_atr_percentile_series()` | LIVE-ML |
| 9 | Trade quality | `tradingbot/ml/trade_quality/volatility_quality.py` | VOL path if TQ not skipped |

| Comparison | Values | Live winner |
|------------|--------|-------------|
| #1 `atr` column vs #7 `atr_pct` rank | **Completely different** — raw ATR vs 0–1 percentile rank over lookback | **#7** drives regime classification and vol signals |
| #4 vs #1 for SL/TP | **Slightly different** — signal_helpers may use last-bar ATR from enriched df | **#4** for stop distance at entry |
| #2 vs #7 percentile | **Slightly different** — window/rank method may differ | **#7** for adaptive |

**Danger:** RiskGate lot sizing uses #3 from enriched OHLCV; signal SL/TP uses #4; regime routing uses #7 — three ATR contexts on one trade.

---

## 3. EMA Slopes

| # | Implementation | File / Function | Definition |
|---|----------------|-----------------|------------|
| 1 | EMA levels only | `tradingbot/domain/indicators.py` → `add_moving_averages()` | ema_20, ema_50 — **no slope column** |
| 2 | ATR-normalized slope | `regime_features.py`, `trend_features.py` → `_ema_slope()` | `ema.diff(5) / atr` |
| 3 | Raw EMA delta | `tradingbot/services/wpsqf_features.py` | EMA20 now − EMA20 5 bars ago |
| 4 | EMA separation ratio | `tradingbot/strategies/adaptive_regime.py` → `_ema_sep_ok()` | `abs(ema20-ema50)/close >= 0.00055` |
| 5 | H1 trend | `edge_discovery_round2.py` → `_build_h1_trend()` | EMA50 vs EMA200 on H1 |

| Comparison | Live winner |
|------------|-------------|
| #4 vs #2 | **Completely different** metrics | **#4 and #5** for ADAPTIVE entry filters |
| #3 vs #2 | **Completely different** normalization | **#3** only if WPSQF ON |

---

## 4. RSI

| # | Implementation | File / Function | Live? |
|---|----------------|-----------------|-------|
| 1 | Kernel | `indicators.py` → `add_rsi()` → column `rsi` | IndicatorStage |
| 2 | Vol frame | `edge_discovery_round2.py` → `_rsi()` → column `rsi14` | **LIVE-ADAPTIVE** |
| 3 | High-vol momentum | `adaptive_regime.py` → `_high_vol_momentum_signal()` | Uses **rsi14** bands 28–72 |
| 4 | WPSQF | `wpsqf_features.py` → `_fast_rsi()` | WPSQF if ON |
| 5 | ML filters | `ml/phase19c/filters.py` | LIVE-ML only |

| Comparison | Identical? | Live winner |
|------------|------------|-------------|
| #1 vs #2 | **Slightly different** — separate implementations, both period-14 typical | **#2 rsi14** for adaptive signals; **#1** unused by adaptive logic |

---

## 5. Spread

| # | Implementation | File / Function | Semantics |
|---|----------------|-----------------|-----------|
| 1 | Live tick | `risk_gate.py` → `_live_spread_pips()` → `spread_pips_from_prices(ask,bid)` | **Real broker spread** |
| 2 | Session estimate | `session_logic.py` → `variable_spread_pips()` | Backtest / session model |
| 3 | Bar proxy | `edge_discovery_round2.py` → `_spread_proxy_pips()` | `(high-low)/pip` on M5 bar |
| 4 | TQ liquidity | `liquidity_quality.py` → `classify_spread()` | Thresholds 4/8 pips |
| 5 | WPSQF default | `wpsqf_features.py` | Default spread=0.3 if missing |

| Comparison | Live winner |
|------------|-------------|
| #1 vs #3 | **Completely different** — tick vs bar range | **#1** blocks at RiskGate; **#3** caused false TQ blocks in VOL_REGIME era (now skipped) |
| #2 vs #1 | **Completely different** | **#2** backtest only |

**Prior audit evidence:** Conversation logs showed `spread_proxy` ~11.8 pips vs live tick ~3.9 pips blocking TQ. Current adaptive path: `tq_skipped: True` in `adaptive_regime_strategy_registry.py` metadata.

---

## 6. Confidence

| # | Implementation | File | Output range |
|---|----------------|------|--------------|
| 1 | PA heuristic | `signal_helpers.py` → `compute_confidence()` | 0–1 heuristic |
| 2 | Fixed rule | `decision_policy.py` → `VOL_REGIME_RULE_CONFIDENCE = 0.60` | **Constant 0.60** |
| 3 | ML stack | `confidence_engine.py` → `ConfidenceEngine` | model × regime × quality |
| 4 | WPSQF score | `wpsqf_scoring.py` → `signal_quality_score()` | 0–100 (**name collision**) |
| 5 | TQ signal quality | `trade_quality/signal_quality.py` | 0–1 bands |

| Comparison | Live winner |
|------------|-------------|
| All paths | **Completely different** scales and meaning | **#2 fixed 0.60** for ADAPTIVE — confidence is not computed from market state |

---

## 7. Regime Classification

| # | Implementation | File / Function | Labels |
|---|----------------|-----------------|--------|
| 1 | Risk regime | `risk_logic.py` → `infer_regime_from_ohlcv()` | STRONG_TREND_UP/DOWN, RANGING, VOLATILE, CRISIS |
| 2 | Adaptive router | `adaptive_regime.py` → `classify_regime()` | TREND, RANGE, HIGH_VOLATILITY, LOW_VOLATILITY, NO_TRADE |
| 3 | L3 validation | `live_l3/execution_validation.py` → `_infer_regime()` | TREND, RANGE, HIGH_VOLATILITY, NO_TRADE |
| 4 | ML rules | `regime_classifier.py` → `rule_classify_row()` | Phase 13.2 ML taxonomy |
| 5 | ML selector | `strategy_selector.py` → `select_engine()` | Routes RANGE/TREND/HIGH_VOL engines |

| Comparison | Live winner |
|------------|-------------|
| #1 vs #2 | **Completely different** taxonomies and thresholds | **#2** for signal routing; **#1** still runs in RiskGate for metadata/meta (meta skipped for adaptive) |
| #2 vs #3 | **Slightly different** — #3 lacks LOW_VOLATILITY | **#2** live |

**Three incompatible regime systems** active in codebase; only #2 controls adaptive entries.

---

## 8. Trend Classification

| # | Implementation | File | Method |
|---|----------------|------|--------|
| 1 | SMC / PA | `price_action.py` | Structure, BOS, sweeps |
| 2 | MTF trend signal | `edge_discovery_round2.py` → `_multi_tf_trend_signal()` | H1 EMA50/200 + M5 structure |
| 3 | WPSQF structure | `wpsqf_features.py` → `_market_structure()` | HH/LL counts |
| 4 | ML trend rules | `trend_rules.py` → `evaluate_trend_rules()` | HH/LL + ema50_slope |

| Live winner | **#2** for ADAPTIVE (via `_multi_tf_trend_signal` wrapped with session/H1/EMA filters) |

---

## 9. Trade Quality / Quality Score

| # | Implementation | File | Active live? |
|---|----------------|------|--------------|
| 1 | ML TradeQualityEngine | `ml/trade_quality/quality_engine.py` | NO (ML off) |
| 2 | VOL TQ gate | `vol_regime_strategy_registry.py` | NO (adaptive selected; TQ skipped anyway) |
| 3 | WPSQF | `winner_population_signal_quality_filter.py` | NO (default OFF) |
| 4 | Meta-labeler | `services/meta_labeler.py` | NO (skipped for ADAPTIVE_REGIME) |
| 5 | PA market filters | `market_filters.py` | NO (skipped for adaptive) |

| Live winner | **None** — quality gates are bypassed on current adaptive path except implicit filters in `adaptive_regime.py` (_wrap session/H1/EMA/confluence) |

---

## 10. Position Sizing / Lot Calculation

| # | Implementation | File / Function |
|---|----------------|-----------------|
| 1 | Canonical | `risk_logic.py` → `lot_from_stop_distance()`, `optimal_lot_size()` |
| 2 | Live RiskGate | `risk_gate.py` → `_compute_lot()`, `_fallback_lot()` |
| 3 | Backtest duplicate | `backtest/risk.py` → `_position_size()` |
| 4 | Adaptive metadata | `adaptive_regime_strategy_registry.py` → `risk_factor=0.5` in HIGH_VOL |

| Comparison | Live winner |
|------------|-------------|
| #2 vs #1 | **Identical** when SL distance available | **#2** calls **#1** |
| #4 vs #2 | **Completely different** — metadata risk_factor **NOT wired** to `_compute_lot()` | **#2 ignores #4** — HIGH_VOL 0.5× risk factor is dead metadata |

**Evidence:** `adaptive_regime_strategy_registry.py` sets `risk_factor = 0.5 if sig.regime == "HIGH_VOLATILITY"` in metadata; `RiskGate._compute_lot()` does not read `signal.metadata["risk_factor"]`.

---

## Summary Table — Top Duplicates

| Concept | # Implementations | Match quality | What live actually uses |
|---------|-------------------|---------------|-------------------------|
| ADX | 6+ | Mixed | None for adaptive entry |
| ATR | 9+ | Mixed scales | `atr_pct` (#7) + signal_helpers (#4) + risk (#3) |
| EMA slope | 5 | Different definitions | EMA separation (#4) + H1 trend (#5) |
| RSI | 5 | Near-duplicate code | `rsi14` (#2) |
| Spread | 5 | Different semantics | Live tick (#1) at RiskGate |
| Confidence | 5 | Incompatible scales | Fixed 0.60 (#2) |
| Regime | 5 | **Incompatible taxonomies** | `classify_regime()` (#2) |
| Trend | 4 | Different methods | `_multi_tf_trend_signal()` (#2) |
| Quality | 5 | Parallel layers | All bypassed except confluence logic |
| Lot size | 4 | Backtest reimplements | `RiskGate._compute_lot()` (#2) |

---

## Consolidation Priority (Evidence-Based)

1. **Regime taxonomy** — unify `infer_regime_from_ohlcv`, `classify_regime`, `rule_classify_row` or document adapters explicitly.
2. **ATR / atr_pct** — single percentile function consumed by vol frame, risk, and SL/TP.
3. **Spread** — never use `spread_proxy` for live gates; keep tick spread as sole live source.
4. **Wire or remove `risk_factor`** — adaptive HIGH_VOL 0.5× is currently cosmetic in metadata.
5. **Rename WPSQF `signal_quality_score`** — collides with ML trade quality naming.

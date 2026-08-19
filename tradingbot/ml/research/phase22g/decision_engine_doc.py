"""Phase 22G — decision engine documentation from code."""

from __future__ import annotations


def build_decision_engine_md() -> str:
    return """# Phase 22G — Decision Engine (verified from source)

## Stack wiring

Production ML stack (`tradingbot/ml/integration/factory.py`):

```
RangeRecoveryOrchestrator.decide()
  -> DecisionOrchestrator.decide()  [inner, with RangeAwareConfidenceEngine]
  -> CalibratedDecisionAdapter.decide()  [via build_production_calibrated_adapter]
  -> AdaptiveRiskAdapter.evaluate()
  -> TradeQualityAdapter.evaluate()
  -> KernelAdapter.produce_unified_signal() [final coercion + phase19c filters]
```

## Stage 1 — Regime classification

`tradingbot/ml/research/regime_detector/regime_classifier.py`

| Condition | Regime |
|-----------|--------|
| spread >= 8 OR atr_pct >= 95 OR vol >= 5 | NO_TRADE |
| atr_pct > 90 | HIGH_VOLATILITY |
| adx > 25 AND abs(ema50_slope) >= 0.15 | TREND |
| adx < 20 AND atr_pct < 30 | RANGE |
| adx > 25 | TREND |
| else | RANGE |

## Stage 2 — Engine selection

`tradingbot/ml/decision_engine/strategy_selector.py`

| Regime | Engine ID |
|--------|-----------|
| RANGE | phase9_9 |
| TREND | trend_rf_v40 (constant TREND_MODEL_ID) |
| HIGH_VOLATILITY, NO_TRADE | None -> orchestrator HOLD |

**Note:** Inference uses `resolve_active_trend_engine_id()` in KernelAdapter, but orchestrator labels TREND as `trend_rf_v40` always.

## Stage 3 — Range engine HOLD branches

`tradingbot/ml/research/regime_router/range_engine_adapter.py`

- HOLD if features missing
- BUY if P(win) >= buy_threshold (default 0.55; Phase 22C may lower)
- SELL if P(win) <= sell_threshold (default 0.45)
- HOLD otherwise

## Stage 4 — Trend engine HOLD branches

`tradingbot/ml/research/phase13_8/recovered_trend_engine.py` + `trend_rules.py` + `trend_ml_filter.py`

- HOLD if regime != TREND
- HOLD if ADX <= 25 or structure rules fail
- BUY/SELL from EMA structure rules
- HOLD if ML proba < threshold (default 0.40)

## Stage 5 — DecisionOrchestrator

`tradingbot/ml/decision_engine/orchestrator.py`

**Branch A — engine_id is None or selected signal is None:**
- action = HOLD (lines 39-70)
- regimes NO_TRADE, HIGH_VOLATILITY

**Branch B — engine selected:**
- raw_action = selected.signal
- final_conf = ConfidenceEngine.from_context(ctx, model_conf)
- final_action = DecisionPolicy.apply(raw_action, final_conf)

### DecisionPolicy.apply (`decision_policy.py`)

| Condition | Output |
|-----------|--------|
| action not BUY/SELL | HOLD |
| confidence < min_confidence (0.55 default; 0.48 if Phase 22C) | HOLD |
| else | pass through BUY/SELL |

### RangeAwareConfidenceEngine (`phase15i/recovery_adapter.py`)

When RANGE+phase9_9 OR TREND+active trend engine AND engine signal is BUY/SELL:
- Uses directional probability with regime_strength=1.0, market_quality=1.0 (recovery path)
- Else: default compression model_conf × regime_strength × market_quality

## Stage 6 — Calibration

`CalibratedDecisionAdapter.decide()` / `ResearchCalibratedAdapter.decide()`

- Uses raw_engine_signal from metadata (NOT orchestrator final_action if it was HOLD)
- final_action = BUY/SELL if Platt gate passes AND engine_signal is BUY/SELL
- Can **promote** BUY/SELL even when orchestrator returned HOLD (confidence gate)

Production threshold from `recovered_calibration.py` — often ~0.30, capped by Phase 22C calibration_min (0.42).

## Stage 7 — Adaptive risk

`tradingbot/ml/risk_intelligence/adaptive_risk_engine.py`

Blocks (allowed=False) when:
- action is HOLD
- mapped confidence < 0.55
- regime NO_TRADE
- atr_percentile >= 90
- drawdown >= 8%

Does not change action string — blocks at kernel via quality/risk.allowed.

## Stage 8 — Trade quality

`tradingbot/ml/trade_quality/quality_engine.py`

Blocks when:
- action HOLD
- risk blocked
- signal/regime/volatility/liquidity sub-scores fail
- weighted score < threshold (0.65 default; 0.52 Phase 22C)

## Stage 9 — KernelAdapter final coercion

`tradingbot/ml/integration/kernel_adapter.py` lines 214-239

| Step | HOLD condition |
|------|----------------|
| 1 | calibrated.final_action not BUY/SELL |
| 2 | not risk.allowed OR not quality.allowed |
| 3 | phase19c filter failed (RSI/ADX) |

Hold-chain diagnostic priority (`_hold_chain_snapshot`):
1. raw_action HOLD -> decision_hold
2. calibrated not BUY/SELL -> calibration_hold
3. risk/quality block -> trade_quality_hold
4. rsi_filter / adx_filter

## Stage 10 — Meta labeler (live RiskGate only)

`tradingbot/adapters/risk_gate.py` — MetaLabeler.should_gate before order approval.
Backtest uses `BacktestRiskGate` with live_gates parity.

## Why HOLD dominates (code-level)

1. Regime classifier assigns RANGE on most bars (adx thresholds)
2. Range P(win) band 0.45-0.55 is HOLD; buy needs >= 0.55
3. Trend path requires TREND regime + rules + ML pass
4. Confidence compression on non-recovery path
5. DecisionPolicy min_confidence gate
6. Quality + risk + phase19c filters
7. RiskGate: daily loss cascade, min balance, max positions (backtest evidence)
"""

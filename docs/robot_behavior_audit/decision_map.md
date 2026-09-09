# Decision Map — BUY Signal Gates

> **HISTORICAL (2026-07 audit).** Assumes Adaptive as the live config.
> Current live truth is `docs_v2/` (MultiEngineRouter + `PA_PRODUCTION_LOCK` → Price Action).
> Do not treat this file as the active live contract. Historical gate analysis below is unchanged.

**Repository:** `TradingBot new`  
**Assumed live config:** ADAPTIVE_REGIME, CONFLUENCE_ONLY, USE_ML_KERNEL=false, WPSQF OFF, TQ skipped

For a **BUY** signal, every gate that can stop it — in order.

---

## Gate Flow

```
Signal Generation (Adaptive)
  → WPSQF (SignalFilterStage)
  → RiskGate Live Gates
  → LiveRiskTracker
  → risk_logic.can_trade
  → Meta-Labeler
  → Lot sizing / Execution pre-checks
  → MT5 order_send
```

---

## Phase A — Signal Generation (Before Pipeline Risk)

These gates run inside `AdaptiveRegimeStrategyRegistry` / `adaptive_regime.py`. If any fails, **no signal enters the pipeline**.

| Gate | Threshold | File | Function | ACTIVE? | Prior audit blocking? |
|------|-----------|------|----------|---------|----------------------|
| Symbol filter | XAUUSD only | `adaptive_regime_strategy_registry.py` | `generate_signal()` L62 | **YES** | NOT PROVEN |
| Timeframe filter | M5 only | same | L62 | **YES** | NOT PROVEN |
| Session window | 12–17 UTC | `adaptive_regime.py` | `_in_session()` | **YES** | **YES** — most hours produce no signal |
| Regime classify | NO_TRADE if bad data | `adaptive_regime.py` | `classify_regime()` | **YES** | NOT PROVEN |
| EMA separation | ≥ 0.055% of price | `adaptive_regime.py` | `_ema_sep_ok()` | **YES** | NOT PROVEN |
| H1 trend alignment | h1_trend ≥ 0 for BUY | `adaptive_regime.py` | `_h1_aligned()` | **YES** | NOT PROVEN |
| CONFLUENCE MTF+VOL | Both agree, atr_pct 30–70% | `adaptive_regime.py` | `evaluate_adaptive_at_index()` L159–174 | **YES** (default) | **YES** — primary idle reason |
| HIGH_VOL fallback | atr ≥ 72%, HVM+MTF agree | same | L175–188 | **YES** (conditional) | **YES** — observed live HIGH_VOL_MOMENTUM BUY |
| Fixed confidence | 0.60 constant | `decision_policy.py` | `VOL_REGIME_RULE_CONFIDENCE` | N/A (not a gate) | No |

---

## Phase B — ML Signal (Not Active)

| Gate | Threshold | File | Function | ACTIVE? | Prior audit? |
|------|-----------|------|----------|---------|--------------|
| ML Kernel signal | DecisionPolicy min confidence | `decision_engine/decision_policy.py` | `apply()` | **NO** | N/A |
| Phase19c RSI filter | RSI 35–65 (phase22c) | `ml/phase19c/filters.py` | `apply_profitability_filters()` | **NO** | N/A |
| Phase19c ADX filter | ADX 10–55 | same | same | **NO** | N/A |
| Engine routing | phase9_9 / trend v41 | `engine_registry.py` | `build_default()` | **NO** | N/A |

---

## Phase C — Calibration (ML Only)

| Gate | Threshold | File | ACTIVE? | Prior audit? |
|------|-----------|------|---------|--------------|
| Calibrated adapter | PHASE22C_CALIBRATION_MIN_CONFIDENCE=0.42 | `recovered_calibration.py` | **NO** | N/A |

---

## Phase D — Confidence (Adaptive)

| Gate | Threshold | File | ACTIVE? | Prior audit? |
|------|-----------|------|---------|--------------|
| MIN_CONFIDENCE | 0.55 in live.py | `live.py` | **NO** — uses fixed 0.60 | No |
| ML confidence engine | Dynamic | `confidence_engine.py` | **NO** | N/A |

---

## Phase E — TradeQuality

| Gate | Threshold | File | Function | ACTIVE? | Prior audit? |
|------|-----------|------|----------|---------|--------------|
| TradeQualityEngine | quality ≥ 0.52 (phase22c) | `quality_engine.py` | `evaluate()` | **NO** (ML off) | **YES** — blocked VOL_REGIME when TQ on (spread_proxy) |
| VOL TQ skip | VOL_REGIME_SKIP_TQ=true | `vol_regime_strategy_registry.py` | TQ branch | **N/A** — adaptive bypasses | **YES** — fix applied |
| Adaptive metadata | tq_skipped=True | `adaptive_regime_strategy_registry.py` | metadata | **Skipped entirely** | No |

---

## Phase F — RSI Filter (.env)

| Gate | Threshold | File | ACTIVE? | Prior audit? |
|------|-----------|------|---------|--------------|
| ENABLE_RSI_FILTER | RSI 40–60 (.env.example) | `phase19c/filters.py` | **NO** (ML path) | N/A |
| Adaptive HVM RSI | 45–72 for BUY | `adaptive_regime.py` `_high_vol_momentum_signal()` | **YES** (high-vol path only) | NOT PROVEN |

---

## Phase G — ADX Filter (.env)

| Gate | Threshold | File | ACTIVE? | Prior audit? |
|------|-----------|------|---------|--------------|
| ENABLE_ADX_FILTER | ADX 15–50 | `phase19c/filters.py` | **NO** (ML path) | N/A |

---

## Phase H — WPSQF

| Gate | Threshold | File | Function | ACTIVE? | Prior audit? |
|------|-----------|------|----------|---------|--------------|
| WPSQF | score ≥ 77.56 | `signal_filter_stage.py` | `SignalFilterStage.run()` | **NO** — default OFF | NOT PROVEN blocking |

Env: `TRADINGBOT_SIGNAL_FILTER` unset → OFF (`signal_filter_mode.py` L24).

---

## Phase I — RiskGate (Live Gates)

| Gate | Threshold | File | Function | ACTIVE? | Prior audit? |
|------|-----------|------|----------|---------|--------------|
| Max positions total | ≤ 3 (adaptive capped to **1**) | `risk_gate.py` | `_live_gates()` → `check_max_positions()` | **YES** | NOT PROVEN |
| Max per symbol | ≤ 2 (adaptive capped to **1**) | same | same | **YES** | NOT PROVEN |
| News blackout | 30 min if USE_NEWS_FILTER | `live_gates.py` | `check_news_gate()` | **YES** | NOT PROVEN |
| Friday no entry | after hour **17** | `live_gates.py` | `check_friday_gate()` | **YES** | NOT PROVEN |
| Spread check | ≤ **15** pips (XAU floor) | `risk_gate.py` L98–100 | `check_spread_gate()` | **YES** | Rare — live tick used |
| No opposite position | no SELL if BUY open | `live_gates.py` | `check_no_opposite_position()` | **YES** | NOT PROVEN |
| HTF alignment | M15/H4 bias | `live_gates.py` | `check_htf_alignment()` | **NO** — skipped L277–278 | N/A |
| PA market filters | ADX/RSI/ATR bands | `market_filters.py` | `check_market_filters()` | **NO** — skipped | N/A |

---

## Phase J — LiveRiskTracker

| Gate | Threshold | File | Function | ACTIVE? | Prior audit? |
|------|-----------|------|----------|---------|--------------|
| Cooldown | **12** M5 bars (~60 min) | `live_risk_tracker.py` | `check_entry_allowed()` | **YES** | NOT PROVEN |
| Max trades/day | **3** | same | same | **YES** | NOT PROVEN |
| Daily loss budget | **4%** MAX_DAILY_RISK | same + `risk_logic.py` | `compute_daily_loss_budget()` | **YES** | NOT PROVEN |
| Consecutive loss pause | 3 losses → 30 bar cooldown | same | same | **YES** | NOT PROVEN |

Config source: `live.py` VOL_REGIME_COOLDOWN_BARS=12, VOL_REGIME_MAX_TRADES_PER_DAY=3.

---

## Phase K — risk_logic.can_trade

| Gate | Threshold | File | ACTIVE? | Prior audit? |
|------|-----------|------|---------|--------------|
| Max daily loss | 4% | `risk_logic.py` | **YES** | NOT PROVEN |
| Max weekly loss | 12% | same | **YES** | NOT PROVEN |
| Max monthly loss | 18% | same | **YES** | NOT PROVEN |
| Max consecutive losses | 3 | same | **YES** | NOT PROVEN |
| Max leverage | 10 (relaxed 2× in can_trade) | same | **YES** | NOT PROVEN |

---

## Phase L — Meta-Labeler

| Gate | Threshold | File | ACTIVE? | Prior audit? |
|------|-----------|------|---------|--------------|
| Meta probability | ≥ 0.40 default | `risk_gate.py` L174–206 | **NO** — skipped for ADAPTIVE_REGIME | N/A |

---

## Phase M — Execution Pre-Checks

| Gate | Threshold | File | ACTIVE? | Prior audit? |
|------|-----------|------|---------|--------------|
| MT5 connected | — | `mt5_execution.py` | **YES** | NOT PROVEN |
| Algo Trading enabled | — | `mt5_health.py` | **YES** | NOT PROVEN |
| Order validation | lot/price rules | `order_logic.py` | **YES** | NOT PROVEN |
| Demo account guard | unless TRADINGBOT_ALLOW_REAL | `demo_account_guard.py` | **YES** | NOT PROVEN |

---

## Phase N — Kill Switch (Parallel, Account Level)

| Gate | Threshold | File | ACTIVE? | Prior audit? |
|------|-----------|------|---------|--------------|
| Max drawdown | 15% | `kill_switch.py` | **YES** | NOT PROVEN |
| Daily loss | 4% | same | **YES** | NOT PROVEN |

Stops **new cycles**; does not gate individual BUY inside an running cycle after trigger.

---

## Observed Blocking (Prior Session Evidence)

From conversation audit (NOT from automated log grep in this session — logs path NOT PROVEN accessible):

| Gate | Observation |
|------|-------------|
| Trade Quality (spread_proxy) | **Blocked VOL_REGIME signals** with `TQ score=0.000` when TQ enabled |
| VOL_REGIME ATR band | **No signal** when atr_pct outside 30–70% (by design) |
| CONFLUENCE | **Most cycles idle/no_signal** — MTF and VOL rarely agree |
| Session filter | Blocks outside 12–17 UTC |
| Adaptive HIGH_VOL | **Observed successful BUY** after upgrade — gate passed |

---

## BUY Path Summary (Current Config)

**Active blockers:** Session, confluence logic, EMA/H1 filters, max 1 position, cooldown 12 bars, max 3 trades/day, spread, news, Friday, daily loss, demo guard.

**Inactive (cannot block):** ML, calibration, WPSQF, TQ, meta-labeler, HTF alignment, PA market filters, RSI/ADX .env filters.

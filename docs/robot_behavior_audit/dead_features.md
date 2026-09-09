# Unused / Dead Features

> **HISTORICAL (2026-07 audit).** Assumes `ADAPTIVE_REGIME_ENABLED=true` as live config.
> Current live truth is `docs_v2/` (MultiEngineRouter + `PA_PRODUCTION_LOCK` → Price Action).
> Do not treat this file as the active live contract. Historical classifications below are unchanged.

**Repository:** `TradingBot new`  
**Live config assumed:** `ADAPTIVE_REGIME_ENABLED=true`, `USE_ML_KERNEL=false`, `TRADINGBOT_SIGNAL_FILTER` unset (OFF)

Classification:
- **SAFE_TO_DELETE** — not imported on live path, no runtime side effects proven
- **NEEDS_VERIFICATION** — import-reachable or config-present but behavior unproven
- **DO_NOT_TOUCH** — active in live trading or safety-critical

---

## 1. Files Never Imported in Production (Research)

**Method:** BFS import graph from `live_runner.py` + `tradingbot/__main__.py` + `run_live_watchdog.py`.

| Metric | Count | Evidence |
|--------|-------|----------|
| Research `.py` files under `tradingbot/ml/research/` | ~740 | Glob count |
| Reachable from live entry | ~61 | Mostly via `factory.py` ML wiring |
| **Unreachable (dead)** | **~679** | Never imported when ML kernel off |

### Representative dead folders (SAFE_TO_DELETE after verification)

| Path | Notes | Mark |
|------|-------|------|
| `tradingbot/ml/research/advanced_discovery/` | Offline discovery | SAFE_TO_DELETE |
| `tradingbot/ml/research/live_l1/` | Superseded by L2/L3 | SAFE_TO_DELETE |
| `tradingbot/ml/research/live_l4/` | Not on live path | SAFE_TO_DELETE |
| `tradingbot/ml/research/phase14_10/` through `phase32i/` | Historical phase experiments | SAFE_TO_DELETE |
| `tradingbot/ml/research/hypothesis.py`, `experiment_runner.py` | Research runners | SAFE_TO_DELETE |

### Research files that ARE used at runtime (DO_NOT_TOUCH)

| Path | Why |
|------|-----|
| `tradingbot/ml/research/live_l2/edge_discovery_round2.py` | Adaptive signal frame + MTF/VOL rules |
| `tradingbot/ml/research/live_l2/edge_discovery.py` | Helper imports from round2 |
| `tradingbot/strategies/vol_regime_signal.py` | Frame prep for adaptive |

**Note:** Live adaptive engine lives inside `tradingbot/strategies/` but **depends on research module** `live_l2/edge_discovery_round2.py`. Deleting research L2 breaks live trading.

---

## 2. Classes Never Instantiated (Live Path)

| Class | File | Mark | Evidence |
|-------|------|------|----------|
| `MLKernelRegistry` | `ml/integration/ml_kernel_registry.py` | SAFE_TO_DELETE *from live concern* | Only when `USE_ML_KERNEL=true` |
| `VolRegimeStrategyRegistry` | `adapters/vol_regime_strategy_registry.py` | NEEDS_VERIFICATION | Shadowed by adaptive; still valid fallback |
| `LegacyStrategyRegistry` / Price Action | `adapters/legacy_strategy_registry.py` | NEEDS_VERIFICATION | Fallback if all regime flags off |
| `UnconfiguredEngineRegistry` | `factory.py` | DO_NOT_TOUCH | Returns None — prevents silent legacy |
| `MonitoredKernelAdapter` | `ml/monitoring/observer.py` | SAFE_TO_DELETE (ML only) | ML monitoring wrapper |
| `PositionProtector` (legacy) | background services | SAFE_TO_DELETE *when adaptive on* | Explicitly disabled `live_runner.py` L206–208 |
| `PositionRecoveryService` | background services | SAFE_TO_DELETE *when adaptive on* | Explicitly disabled |

---

## 3. Functions Never Called (Config / Dead Keys)

| Config key | File defined | References elsewhere | Mark |
|------------|--------------|---------------------|------|
| `SIGNAL_TIMEOUT` (90) | `live.py` L60 | **Zero** | SAFE_TO_DELETE |
| `NIGHTLY_OPTIMIZATION` | `live.py` L126 | **Zero** | SAFE_TO_DELETE |
| `ADAPTIVE_OPTIMIZATION` | `live.py` L128 | **Zero** | SAFE_TO_DELETE |
| `EMERGENCY_MAX_LOSS_PIPS` in live.py | `live.py` L59 | Position manager reads from **PRICE_ACTION** / constructor default | NEEDS_VERIFICATION — live.py key may be dead |
| `get_timeframe_config()` | `live.py` L199 | Only defined, no live consumer | SAFE_TO_DELETE |
| `get_strategy_config()` | `live.py` L195 | Empty `STRATEGY_CONFIGS` | SAFE_TO_DELETE |
| `TIMEFRAME_CONFIGS` | `live.py` L147–173 | Unused in live chain | SAFE_TO_DELETE |

---

## 4. Filters That Never Block Anything (Current Config)

| Filter | Default | Blocks trades? | Mark |
|--------|---------|----------------|------|
| WPSQF | OFF (`signal_filter_mode.py` L24) | **No** | DO_NOT_TOUCH — intentional default |
| Meta-labeler | Active code but skipped for ADAPTIVE | **No** | DO_NOT_TOUCH |
| Trade Quality (VOL TQ) | `VOL_REGIME_SKIP_TQ=true` | **No** | DO_NOT_TOUCH |
| HTF alignment (RiskGate) | Skipped for adaptive | **No** | DO_NOT_TOUCH |
| PA market filters | Skipped for adaptive | **No** | DO_NOT_TOUCH |
| ML phase19c RSI/ADX | ML off | **No** | SAFE_TO_DELETE from live concern |
| `ENABLE_RSI_FILTER` / `ENABLE_ADX_FILTER` in `.env.example` | true | **No effect on adaptive** | NEEDS_VERIFICATION |

---

## 5. Config Options Ignored (Adaptive Active)

| Flag | Defined | Ignored because | Mark |
|------|---------|-----------------|------|
| `VOL_REGIME_ENABLED` | `live.py` L105 | Adaptive wins in `factory.py` L163 | NEEDS_VERIFICATION |
| `MIN_CONFIDENCE` (0.55) | `live.py` L58 | Adaptive uses fixed 0.60 | SAFE_TO_DELETE *for adaptive* |
| `VOL_REGIME_ATR_SL_MULT`, `VOL_REGIME_TP_RR` | `live.py` L110–111 | Hardcoded in `vol_regime_signal.py` / adaptive presets | NEEDS_VERIFICATION |
| `TREND_MODEL_VERSION=v41` | `.env.example` L26 | ML-only `phase17d/versioning.py` | SAFE_TO_DELETE from live concern |
| `PHASE22C_*` thresholds | `.env.example` | ML kernel + phase22c hold chain | SAFE_TO_DELETE when ML off |
| `TRAILING_STOP_ATR_MULTIPLIER` etc. | `live.py` L63–65 | Position manager uses PRICE_ACTION presets | NEEDS_VERIFICATION |

---

## 6. Research Modules Accidentally Loaded at Startup

| Module | Loaded? | Executes? | Mark |
|--------|---------|-----------|------|
| `factory.build_ml_kernel_stack()` | Only if ML on | No with ML off | SAFE_TO_DELETE from startup |
| `PipelineCache.warm_datasets()` | ML stack init | No with ML off | SAFE_TO_DELETE from startup |
| `edge_discovery_round2` | **Yes** — via adaptive | **Yes** — frame prep each signal | DO_NOT_TOUCH |
| `startup_diagnostics.log_engine_selection()` | Yes | Logs only | DO_NOT_TOUCH |

**Finding:** ML factory imports ~61 research modules into import graph even when ML disabled, increasing startup import time. They do not execute signal logic unless `USE_ML_KERNEL=true`.

---

## 7. Backtest-Only Code (Cannot Affect Live)

| Component | File | Mark |
|-----------|------|------|
| `BacktestEngine` | `tradingbot/backtest/engine.py` | SAFE_TO_DELETE from live |
| `BacktestPositionManager` | `tradingbot/backtest/position_manager.py` | SAFE_TO_DELETE from live |
| `_position_size()` duplicate | `tradingbot/backtest/risk.py` | SAFE_TO_DELETE from live concern |
| `variable_spread_pips()` backtest spread | `session_logic.py` | DO_NOT_TOUCH — backtest parity |
| Scripts `scripts/backtest_*.py` | scripts/ | SAFE_TO_DELETE from live |

---

## 8. Engines Present But Unreachable Live

| Engine | Reachable? | Mark |
|--------|------------|------|
| phase9_9 range ML | Only via ML kernel | SAFE_TO_DELETE from live |
| trend_rf v41 / v40 | Only via ML kernel | SAFE_TO_DELETE from live |
| Standalone VOL_REGIME registry | Shadowed by adaptive | NEEDS_VERIFICATION — keep as fallback |
| Price Action legacy | Requires all regime+ML off | NEEDS_VERIFICATION |
| L2 hypotheses: PULLBACK_VWAP, LONDON_KZ, NY_REVERSAL, BOS_RETEST, SPREAD_SESSION | Defined in round2, never called from adaptive | SAFE_TO_DELETE *if adaptive-only forever* |

---

## 9. Safety-Critical — DO_NOT_TOUCH

| Item | Reason |
|------|--------|
| `KillSwitchService` | Account drawdown / daily loss halt |
| `demo_account_guard` | Blocks real accounts unless `TRADINGBOT_ALLOW_REAL` |
| `guarded_order_send()` | Order send wrapper |
| `emergency_stop_state` | Persisted halt across restarts |
| `manual_stop.flag` | User stop via STOP_BOT |
| `RiskGate` live gates (spread, cooldown, max positions) | Active protection |
| `Mt5PositionManager` emergency/EOD | Position safety |
| `edge_discovery_round2.py` | Live adaptive dependency |

---

## Summary Counts

| Category | Approx count | Action |
|----------|--------------|--------|
| Dead research files | ~679 | Archive after team review |
| Ignored live.py keys | 8+ | Document or remove |
| Filters inactive (by design) | 5 | Document in config_truth |
| Backtest-only modules | 10+ | Keep for validation |

**NOT PROVEN:** Exact import count without running static analysis tool in this audit session — counts from exploratory BFS agent report; re-verify with `python -m scripts.import_audit` if such script exists (NOT PROVEN).

# Full Repository Source of Truth (Phase 1.5.61)

**Document status:** SUPPORTING AUDIT SNAPSHOT (not the ChatGPT entry)  
**Canonical entry:** `docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md`  
**Live impact:** none — inspect and document only  
**Last verified:** 2026-09-01  
**Method:** static source inspection + isolated research runners + filesystem inventory  
**Does not replace:** executable code. Hierarchy remains `CODE > runtime evidence > tests > generated analysis > docs`.  
**Does not start:** Phase 1.5.62  

Machine-readable twin: `data/ml/reports/full_repository_audit/`.

This document exists so an external reasoning agent can understand the repository without inferring live behavior from filenames, historical ML logs, or stale docs.

---

## 1. Executive summary

This repository is a Python MetaTrader 5 trading system. The **default live daemon path** is **Price Action only** on **`XAUUSD_i` M5**, selected by `MultiEngineRouterRegistry` while `PA_PRODUCTION_LOCK` defaults **true**. VOL and Adaptive are **probed and logged, never selected**. The ML kernel is **off** on the daemon default (`USE_ML_KERNEL=false` if unset). The ML live gate is **closed**. v41 remains **class C / calibration 1.0 / research-watch**. Isolated PA rule-replay is **class B** (uncosted, identity unproven).

**Requested vs effective is a first-class distinction.** CLI defaults (`--symbol XAUUSD`, `--tf M15`), base `PRICE_ACTION_CONFIG` (preset `quality`), and ~~`BacktestConfig.timeframe="M1"`~~ **`BacktestConfig.timeframe="M5"`** (Phase 25B; was M1 pre-25B) differ from the live daemon contract only where CLI/`__main__` defaults apply. The live contract is daemon env + `get_live_config()` + M5 gold preset `gold_ny_sweep`.

**Do not treat `data/ml/live/` or `TREND_MODEL_ID=trend_rf_v40` as proof that ML owns live signals.** Live owner is PA. `trend_rf_v40` is the frozen rollback / calibrator label. `resolve_active_trend_engine_id()` defaults to `trend_rf_v41` **only if the ML kernel path is actually used**.

Operator `.env` was **not** read (secrets). Process-env snapshots in the JSON are **this audit process**, not a running daemon.

---

## 2. Repository map

### 2.1 Top-level layout (verified by walk)

| Area | Role | Classification |
|------|------|----------------|
| `tradingbot/` | Canonical application package | PRODUCTION_CANDIDATE + RESEARCH under `ml/research/` |
| `engine/` | Legacy strategy implementations still called live (`PriceActionStrategy`) | PRODUCTION-AFFECTING |
| `scripts/` | Start/stop, watchdog, research runners, dashboard | MIXED |
| `start/` | Operator BAT wrappers (`START_BOT.bat`) | PRODUCTION entry |
| `tests/` | Pytest suite (~230 `test_*.py`) | TEST |
| `docs_v2/` | Current documentation set | DOCS (mixed currency) |
| `docs/` | Legacy / robot_behavior_audit | HISTORICAL / STALE in parts |
| `data/` | Datasets, reports, journals, bundles | ARTIFACT / gitignored in parts |
| `models/` | Meta-labeler pickles | PRODUCTION-CANDIDATE (gating) + RESEARCH |
| `memory/` | Project index dumps | GENERATED |

Evidence: inventory in `data/ml/reports/full_repository_audit/files.json` and `summary.json`.

### 2.2 Python packages

Every directory under `tradingbot/` containing `__init__.py` is a package. The tree is large because `tradingbot/ml/research/phase*` is one package per historical research phase. Live trading does **not** import most of those packages.

Important live packages:

| Package | Purpose |
|---------|---------|
| `tradingbot.application` | `bootstrap.build_kernel_live`, `live_runner.run_live_loop` |
| `tradingbot.kernel` | `TradingKernel` pipeline loop |
| `tradingbot.pipeline` | Data → Indicators → Signal → SignalFilter → Risk → Execution |
| `tradingbot.adapters` | MT5, router, RiskGate, registries |
| `tradingbot.config` | live / PA / strategies / dotenv |
| `tradingbot.domain` | gold strategies, PA setup, signals |
| `tradingbot.services` | meta, kill switch, startup, runtime_truth |
| `tradingbot.ml.integration` | factory, kernel adapter, flags |
| `tradingbot.ml.research.*` | offline only |

### 2.3 Entry-point files

| File | Role |
|------|------|
| `tradingbot/__main__.py` | `python -m tradingbot` CLI |
| `scripts/start_bot.py` | One-click start; loads dotenv; launches daemon |
| `scripts/start_live_daemon.ps1` | Sets unset env defaults; starts watchdog `--execute` |
| `scripts/run_live_watchdog.py` | Restarts `python -m tradingbot --loop --execute` |
| `start/START_BOT.bat` | Operator wrapper → `start_bot.py` |
| `scripts/stop_live_daemon.ps1` | Stop path |

### 2.4 Configuration loaders

| Loader | File | What it does |
|--------|------|----------------|
| `load_dotenv` | `tradingbot/config/dotenv_loader.py` | Best-effort `.env` → `os.environ` **only if key unset** |
| `LIVE_TRADING_CONFIG` | `tradingbot/config/live.py` | Live defaults + env-derived flags |
| `get_live_config` | `tradingbot/config/live.py` | Copy + prop preset; **forces `TIMEFRAMES=["5m"]` when router/adaptive/vol on** |
| `get_price_action_config` | `tradingbot/config/price_action.py` | Base PA + `PA_SYMBOL_TF_PRESETS` override |
| `load_legacy_config` | `tradingbot/adapters/legacy_loader.py` | Merges live + engine + PA into kernel extra |
| `kernel_settings_from_legacy` | `tradingbot/config/legacy_settings.py` | Kernel symbols/TFs/interval |
| `is_ml_kernel_enabled` | `tradingbot/ml/integration/config.py` | True only if `USE_ML_KERNEL` **explicitly set** and truthy |
| `engine_settings` | `tradingbot/config/engine_settings.py` | **Contains hardcoded MT5 credential fallbacks** — do not treat as SOT; env must override. Values not copied here. |

`.env` exists as a source. **This audit did not read it.**

### 2.5 Production vs research vs test (file class)

Classification used in JSON (`files.json`):

- `TEST` — `tests/`
- `RESEARCH` — `tradingbot/ml/research/`, `scripts/run_phase*`, `scripts/phase*`
- `DOCS` — `docs*`, `memory/`
- `ARTIFACT` — `data/ml/reports/`
- `PRODUCTION_CANDIDATE` — `tradingbot/`, `engine/`, `scripts/start*`
- `OTHER` — remainder

**Candidate ≠ live-affecting.** See §5.

---

## 3. Runtime entry points

Classes used below:

| Class | Meaning |
|-------|---------|
| **A** | Default live daemon |
| **B** | Paper / backtest |
| **C** | Shadow (log-only) |
| **D** | ML research (may set `USE_ML_KERNEL=1` **inside the script only**) |
| **E** | Isolated research (v41 / PA audit) |
| **F** | Test / stub / healthcheck |

### 3.1 A — Default live daemon

```text
start/START_BOT.bat
  → scripts/start_bot.py          # load_dotenv(); waits for MT5 process; launches daemon
  → scripts/start_live_daemon.ps1 # if unset: USE_ML_KERNEL=false, ENABLE_ML_SHADOW=true,
                                  # MULTI_ENGINE_ROUTER_ENABLED=true,
                                  # ADAPTIVE_REGIME_ENABLED=false, VOL_REGIME_ENABLED=false,
                                  # META_LABEL_THRESHOLD=0.38
  → scripts/run_live_watchdog.py --execute
  → python -m tradingbot --loop --execute
  → tradingbot/__main__.py::main
  → tradingbot/application/live_runner.py::run_live_loop
  → TradingKernel.run_forever / run_global_cycle
```

Evidence: `start/START_BOT.bat`, `scripts/start_bot.py`, `scripts/start_live_daemon.ps1:24–41`, `scripts/run_live_watchdog.py`, `tradingbot/__main__.py`.

### 3.2 A′ — Single live cycle (not daemon)

`python -m tradingbot --live [--execute]` → `bootstrap.run_live_cycle` → `build_kernel_live`. Same registry/risk/execution wiring. No watchdog.

### 3.3 B — Paper / backtest

| Path | Owner | Notes |
|------|--------|------|
| `python -m tradingbot --paper` | `__main__.py` + `execution_mode` | Real ticks, simulated fills, no broker orders (`Mt5ExecutionAdapter.execute` paper branch) |
| `python -m tradingbot --backtest` | `tradingbot/backtest/engine.py::BacktestEngine` | Default `BacktestConfig.timeframe="M5"` (Phase 25B; was M1 pre-25B) — **aligned with live M5** |
| `tradingbot/ml/backtest/engine.py::BacktestConfig` | ML backtest | Default timeframe **M5** (different class) |

### 3.4 C — Shadow

| Path | Owner | Live order impact |
|------|--------|-------------------|
| `ENABLE_ML_SHADOW=true` (daemon default if unset) | `factory._maybe_wrap_shadow` → `ShadowStrategyRegistry` | **None** — inner signal unchanged |
| Router VOL/Adaptive probe | `MultiEngineRouterRegistry.generate_signal` | **None** while `PA_PRODUCTION_LOCK` |
| `META_OBSERVER_MODE=true` | `apply_pa_meta_decision` | **None** — never rejects |

Code-default `is_ml_shadow_enabled()` is **false** if env unset (`tradingbot/ml/integration/config.py`). Daemon sets `ENABLE_ML_SHADOW=true`. **Requested/code-default ≠ operational default.**

### 3.5 D — ML research

`scripts/run_phase*.py`, `tradingbot/ml/research/phase*` often **set `USE_ML_KERNEL=1` in-process**. That does not change the daemon unless an operator exports the same env. Do not copy research env into live.

### 3.6 E — Isolated research

| Package | Purpose | Live impact |
|---------|---------|-------------|
| `tradingbot/ml/research/v41_isolated/` | Frozen v41 replay / cost / decision | None |
| `tradingbot/ml/research/pa_live_audit/` | Live PA path + uncosted replay | None |
| `tradingbot/ml/research/full_repo_audit/` | This inventory | None |

### 3.7 F — Test-only

| Path | Notes |
|------|--------|
| `python -m tradingbot --strategies` | Stub data, `run_strategies_cycle`, no MT5 |
| `python -m tradingbot --healthcheck` | Heartbeat file only |
| `tests/` | Must not start MT5/bot |

---

## 4. Default live execution chain

Verified hop-by-hop (file → symbol → next):

1. `scripts/start_bot.py` → launches `scripts/start_live_daemon.ps1`
2. `scripts/start_live_daemon.ps1` → `Start-Process python scripts/run_live_watchdog.py --execute`
3. `scripts/run_live_watchdog.py` → `python -m tradingbot --loop --execute`
4. `tradingbot/__main__.py::main` → `run_live_loop`
5. `tradingbot/application/live_runner.py::run_live_loop` / `LiveRunner` → builds `_ReliabilityKernel` (stale-bar freeze) using the same adapters as `bootstrap.build_kernel_live`
6. `tradingbot/application/bootstrap.py::build_kernel_live`  
   - market: `Mt5MarketDataAdapter`  
   - indicators: `TechnicalIndicatorEngine`  
   - strategies: `build_strategy_registry`  
   - risk: `create_risk_gate` → `RiskGate`  
   - executor: `Mt5ExecutionAdapter`  
   - positions: `Mt5PositionManager`
7. `tradingbot/ml/integration/factory.py::build_strategy_registry`  
   - ML gate-downgrade if `USE_ML_KERNEL` but `evaluate_ml_live_gate` not allowed  
   - **router_on** (`MULTI_ENGINE_ROUTER_ENABLED`, default true) **and not ml_enabled** → `MultiEngineRouterRegistry`  
   - optional `ShadowStrategyRegistry` wrap
8. `tradingbot/adapters/multi_engine_router.py::MultiEngineRouterRegistry.generate_signal`  
   - always computes PA, VOL, Adaptive  
   - if `is_pa_production_lock` → select **PA only** (`priority_pa`)
9. `tradingbot/adapters/legacy_strategy_registry.py::LegacyStrategyRegistry.generate_signal`
10. `engine/strategy_manager.py::StrategyManager.generate_combined_signals` (via legacy registry)
11. `engine/strategies/price_action_strategy.py::PriceActionStrategy.generate_signals`
12. `tradingbot/pipeline/signal_stage.py::SignalStage` — `exclude_forming_bar` (closed bar)
13. `tradingbot/domain/gold_strategies/router.py::evaluate_gold_setup`  
    - M5 preset mode `london_sweep` → `evaluate_m5_london_sweep`
14. `tradingbot/domain/gold_strategies/m5_london_sweep.py::evaluate_m5_london_sweep`
15. `tradingbot/domain/pa_hardening.py::apply_setup_hardening`
16. `tradingbot/domain/signal_helpers.py::build_trading_signal`
17. `tradingbot/pipeline/risk_stage.py` → `RiskGate.evaluate`
18. `tradingbot/adapters/risk_gate.py::RiskGate.evaluate` (spread / news / Friday / positions / cooldown / ATR filters / optional meta reject)
19. `tradingbot/pipeline/execution_stage.py` → `Mt5ExecutionAdapter.execute`

**ML kernel path is not on this chain** while `USE_ML_KERNEL` is false or the live gate is closed.  
`PIPELINE_TIMEOUT_MS = 500.0` (`tradingbot/ml/integration/kernel_adapter.py`) applies to the **ML kernel adapter**, not this PA pipeline.

---

## 5. Production vs research boundary

### 5.1 PRODUCTION-AFFECTING (can change live orders if invoked on daemon path)

| Component | Why |
|-----------|-----|
| `TradingKernel`, six pipeline stages | Owns the live cycle |
| `build_strategy_registry` / `MultiEngineRouterRegistry` | Selects the live signal |
| `PA_PRODUCTION_LOCK` / `is_pa_production_lock` | Blocks VOL/Adaptive selection |
| `LegacyStrategyRegistry` + `PriceActionStrategy` | Live signal owner |
| `evaluate_gold_setup` / `evaluate_m5_london_sweep` / `apply_setup_hardening` | Entry logic |
| `RiskGate` / `create_risk_gate` | Mandatory new-entry gate |
| `MetaLabeler` + `apply_pa_meta_decision` | **Can reject** PA when `should_gate()` and not observer |
| `Mt5ExecutionAdapter` | Broker `order_send` when `--execute` and not dry-run/paper |
| `Mt5MarketDataAdapter` / `Mt5PositionManager` | Quotes and open positions |
| `KillSwitchService`, emergency/manual stop, `entries_frozen` | Can block entries |
| `load_dotenv` + `LIVE_TRADING_CONFIG` + PA presets | Effective live parameters |
| `ACTIVE_STRATEGIES["priceaction"]=True` | Only enabled legacy strategy |
| `engine_settings.py` credential fallbacks | **Can affect MT5 attach if env missing** — treat as hazard, not documented secrets |

### 5.2 RESEARCH / OFFLINE-ONLY

| Component | Why |
|-----------|-----|
| `tradingbot/ml/research/**` including `v41_isolated`, `pa_live_audit`, `full_repo_audit` | Not imported by `build_kernel_live` |
| `scripts/run_phase*.py` / `scripts/phase*.py` | Offline runners |
| Frozen bundles `data/ml/research/trend_rf_bundle*` | Loaded only if ML kernel path used |
| Isolated replays, cost JSON under `data/ml/reports/phase15_*` | Evidence, not runtime |
| `tradingbot/ml/training/**`, walk-forward, paper research | Offline |
| Most `tests/` | Do not run the daemon |

### 5.3 SHADOW (wired live, no selection / no orders)

| Component | Behavior |
|-----------|----------|
| VOL + Adaptive inner generate on router | Logged; not selected under PA lock |
| `ShadowStrategyRegistry` | Log-only ML comparison |
| `META_OBSERVER_MODE` | Counterfactual only |

### 5.4 Ambiguous (explain, do not resolve)

| Component | Why ambiguous |
|-----------|----------------|
| **Meta-labeler** | Code can reject; continuous current-day enforcement **NOT PROVEN** (historical `data/meta_decisions.jsonl` sample only). |
| **`DEMO_DISABLE_SESSION_FILTER`** | Default false in code; operator `.env` unknown. If true, session window is bypassed. |
| **`ADAPTIVE_REGIME_ENABLED`** | **Not a key** in `LIVE_TRADING_CONFIG`. Factory uses `live_cfg.get(..., False)`. `AdaptiveRegimeStrategyRegistry` defaults **`enabled=True` if missing** (`adaptive_regime_strategy_registry.py`). On default daemon the env is set false; if someone constructs Adaptive without that env, behavior differs. |
| **ML IDs v40/v41** | Present in production files (`engine_calibrator`, `phase15a/config`) but **dead on default live path**. |
| **`PIPELINE_TIMEOUT_MS`** | Production constant; **unused on PA path**. |
| **WPSQF `SignalFilterStage`** | Wired; default OFF (`signal_filter_mode`). |
| **M15/H4 PA presets** | Implemented; **not iterated** when `get_live_config()` forces `["5m"]`. |
| **`data/ml/live/`** | Historical ML-kernel artifacts; **not** current PA owner. |

### 5.5 Special attention items

| Topic | Live status |
|-------|-------------|
| ML kernel | **DEAD** on default path |
| v40 | Frozen rollback / `TREND_MODEL_ID`; calibration owner; not live selector |
| v41 | Active ML id **if kernel on**; class C; **1.0**; not live |
| Adaptive | Shadow probe only |
| VOL | Shadow probe only |
| Price Action | **LIVE owner** |
| MultiEngineRouter | **LIVE selector** (PA lock) |
| RiskGate | **LIVE mandatory** |
| Execution | **LIVE** when `--execute` |
| Calibration | v41 1.0; v40 factors must not be copied |
| Shadow systems | Log only |
| Monitoring | Observability; does not place orders |
| Research replay | Offline |

---

## 6. Configuration truth

### 6.1 Requested vs effective (live daemon)

| Setting | Requested / code default | Effective live (daemon if unset) | Consumer | Controls |
|---------|--------------------------|-----------------------------------|----------|----------|
| `USE_ML_KERNEL` | unset → `is_ml_kernel_enabled()` **false** | daemon sets `"false"` | `factory.build_strategy_registry` | ML vs inner engine |
| `ENABLE_ML_SHADOW` | code default **false** | daemon **true** | `_maybe_wrap_shadow` | Shadow wrap |
| `MULTI_ENGINE_ROUTER_ENABLED` | `live.py` **true** | daemon **true** | factory | Router vs Adaptive/VOL/legacy |
| `PA_PRODUCTION_LOCK` | env default **true** | true unless operator overrides | `is_pa_production_lock` | PA-only selection |
| `ADAPTIVE_REGIME_ENABLED` | **absent** from `LIVE_TRADING_CONFIG`; get default false | daemon **false** | factory / Adaptive registry | Adaptive as selected engine |
| `VOL_REGIME_ENABLED` | `live.py` **false** | daemon **false** | factory / router | VOL as selected engine |
| `META_LABEL_THRESHOLD` | `live.py` / preset **0.38** | daemon **0.38** | RiskGate meta | PA reject threshold |
| `META_OBSERVER_MODE` | **false** | false unless env | `apply_pa_meta_decision` | Reject vs log |
| `PRIMARY_SYMBOL` | `"XAUUSD_i"` | `XAUUSD_i` | kernel / MT5 | Broker symbol |
| Kernel TFs | `LIVE_TRADING_CONFIG['TIMEFRAMES']` = 5m/15m/4h | `get_live_config()` → **`["5m"]`** when router on | kernel loop | Which bars are traded |
| CLI `--symbol` | `XAUUSD` | **not used** by daemon | `__main__.py` backtest/cli | Requested only |
| CLI `--tf` | `M15` | **not used** by daemon | `__main__.py` | Requested only |
| `PRICE_ACTION_CONFIG.PRESET` | `"quality"` | M5 override **`gold_ny_sweep`** | `get_price_action_config` | Live M5 rules |
| `GOLD_STRATEGY_MODE` | name `london_sweep` | NY 15–16 UTC, London **off** | `evaluate_gold_setup` | Which evaluator |
| `MIN_CONFIDENCE` live dict | 0.55 | PA M5 **0.52** | signal build | Confidence floor |
| `RISK_PER_TRADE` | 0.005 | 0.005 unless prop/tier | RiskGate sizing | Risk fraction |
| `LOOP_INTERVAL` | 30 | 30 | kernel | Cycle sleep |
| `PIPELINE_TIMEOUT_MS` | 500.0 | 500.0 | **ML adapter only** | ML timeout |
| `TREND_MODEL_ID` | `trend_rf_v40` | unused on PA path | calibrator | Frozen label |
| `resolve_active_trend_engine_id` | `trend_rf_v41` | unused on PA path | ML registry | Active ML engine id |
| `DEMO_DISABLE_SESSION_FILTER` | false | **UNKNOWN** (env) | PA session | Can bypass NY window |
| `DEMO_MODE` | **true** in `LIVE_TRADING_CONFIG` | still true in code dict | mixed | **Does not by itself block `--execute`** |

### 6.2 Live M5 PA preset (effective)

Source: `tradingbot/config/pa_symbol_tf_presets.py` key `XAUUSD` / `M5` (canonical key; `XAUUSD_i` normalizes to `XAUUSD`).

| Key | Value |
|-----|--------|
| PRESET | `gold_ny_sweep` |
| GOLD_STRATEGY_MODE | `london_sweep` |
| MIN_CONFIDENCE | 0.52 |
| MIN_RR / TP_RR | 1.5 |
| SL_ATR_MULT | 0.35 |
| Asian | 00–08 UTC |
| London session | **OFF** |
| NY entry | 15–16 UTC |
| COOLDOWN_BARS | 18 |
| MAX_TRADES_PER_DAY | 3 |
| MIN_QUALITY_SCORE | 55 |
| META_LABEL_THRESHOLD | 0.38 |
| ENABLE_CHOCH_CONTINUATION | False |
| M5_REQUIRE_REJECTION | False |
| REQUIRE_HTF_ALIGNMENT_M5 | False |

### 6.3 Feature flags (live-relevant)

| Flag | Default | Live effect |
|------|---------|-------------|
| `PA_PRODUCTION_LOCK` | true | PA only |
| `VOL_DIRECTION_FILTER_ENABLED` | false | Off |
| `VOL_REGIME_SKIP_TQ` | true | VOL path only |
| `DISABLE_HIGH_VOL_FOR_MICRO` | true | Micro HIGH_VOL block |
| `ADAPTIVE_QUALITY_ENGINE` | false | Off |
| `ALLOW_LEGACY_FALLBACK` | false | ML fail → HOLD if kernel on |
| `TRADINGBOT_DRY_RUN` / `TRADINGBOT_PAPER` | unset | See `execution_mode` |
| `TRADINGBOT_SIGNAL_FILTER` | OFF | WPSQF off |

---

## 7. Strategy truth

### 7.1 Live: Price Action (`priceaction`)

| Field | Evidence |
|-------|----------|
| Identifier | `"priceaction"` (`ACTIVE_STRATEGIES`, `PA_STRATEGY_NAME`) |
| Implementation | `engine/strategies/price_action_strategy.py` + `evaluate_m5_london_sweep` |
| Live | **Yes** (default daemon + PA lock) |
| Shadow | No (it is the selected engine) |
| Research-only | No |
| Activation | Router selects PA → Legacy → StrategyManager → PriceActionStrategy |
| Timeframe | **M5 only** on default live loop |
| Symbol | Live `XAUUSD_i`; presets keyed `XAUUSD` |
| Entry | Asian range sweep + NY 15–16 UTC close back inside; hardening filters |
| Exit | Broker SL/TP (and position manager / EOD / Friday close — separate from signal) |
| SL | Sweep extreme ± `0.35 * ATR` (`SL_ATR_MULT`) |
| TP | max(other Asian bound, 1.5R) (`MIN_RR`/`TP_RR` 1.5) |
| RR | 1.5 minimum in preset |
| Confidence | 0.52 |
| Quality | ≥ 55 |
| Cooldown | 18 bars; `PA_DEDUP_COOLDOWN_MINUTES` 10 |
| Session | NY 15–16 UTC; London **off** |
| Filters | ATR percentile 12–94; regime/market filters on; ADX off; CHoCH off; rejection candle off; HTF M5 not required |
| Meta | Can reject if gating; threshold 0.38 |

Do not invent undocumented entry/exit. M15 `intraday` and H4 `h4_swing` exist (`evaluate_m15_intraday`, `evaluate_h4_swing`) but are **not looped** when TFs=`["5m"]`. `evaluate_m5_scalp` is **not** the live mode.

### 7.2 Shadow: VOL_REGIME / ADAPTIVE_REGIME

Probed every bar by `MultiEngineRouterRegistry.generate_signal`. Not selected when `is_pa_production_lock`. VOL params live in `LIVE_TRADING_CONFIG` (`VOL_REGIME_*`) but do not size live PA trades.

### 7.3 Disabled `ACTIVE_STRATEGIES` names

All **false**: `advancedml`, `arbitrage`, `breakout`, `dynamicsizing`, `gridtrading`, `hedgingprofessional`, `meanreversion`, `ml`, `momentum`, `patternrecognition`, `pullback`, `rangebound`, `scalping`, `trendfollowing`, `trendmomentumcombo`, `volatilitybreakout`.

If implementations still exist under `engine/strategies/`, they are **not activated**.

### 7.4 ML engines (not live)

| ID | Role | Live |
|----|------|------|
| `trend_rf_v40` | Frozen rollback / `TREND_MODEL_ID` / `TREND_ENGINE_ID` | No |
| `trend_rf_v41` | Default active ML id | No (kernel off) |
| `phase9_9` | RANGE engine | No |

---

## 8. ML truth

**Do not transfer metrics between models.**

### 8.1 Live gate

`tradingbot/ml/shadow/shadow_gate.py::evaluate_ml_live_gate` — Phase 49A preferred (≥100 closed, agree PF>1.2, exp>0.15R, precision gates) else Phase D. Factory **downgrades ML** if `USE_ML_KERNEL` but gate not allowed. On default daemon ML is not requested, so the gate is **N/A**.

### 8.2 v40

| Field | Value |
|-------|--------|
| MODEL ID | `trend_rf_v40` (`TREND_MODEL_ID`, `TREND_ENGINE_ID`) |
| ARTIFACT | `trend_rf_bundle` via `TREND_BUNDLE_DIRS["v40"]` |
| CHECKSUM | See `models.json` if bundle present on disk |
| FEATURE CONTRACT | Bundle `feature_order.json` — do not assume v41 order |
| LIVE STATUS | Not selected |
| RESEARCH STATUS | Historical / rollback |
| CALIBRATION | v40-owned factors — **must not be copied to v41** |

### 8.3 v41

| Field | Value |
|-------|--------|
| MODEL ID | `trend_rf_v41` |
| ARTIFACT | `data/ml/research/trend_rf_bundle_v41/` |
| CHECKSUM | `bundle_sha256` `a433fa410604b17ad195ec80469c86bca47b3df718f4072b2c5d1dc2b153eb6b` (`checksum.json`) |
| FEATURE CONTRACT | That bundle only |
| TRAINING / VAL / TEST | See bundle `training_manifest.json` / metadata — **do not invent** |
| METRICS | Isolated replay (1.5.36–40): OOS n=3409, WR 34.44%, exp +0.033 R, PF 1.050, max DD −33 R — **that replay only** |
| COST | Class C; break-even ~0.033 R; no class-A tape (1.5.41–55) |
| CALIBRATION | **Neutral 1.0** |
| LIVE STATUS | **CLOSED / unused** |
| RESEARCH STATUS | **C — remain watch** |

### 8.4 Other models

| ID / artifact | Live | Notes |
|---------------|------|--------|
| Meta-labeler `models/meta_labeler_m5.pkl` (+ m15/h4) | **Can affect** PA via RiskGate | Loadability verified historically 2026-08-22; continuous enforcement not proven |
| RANGE `phase9_9` | No | Registry id only on ML path |
| XGBoost/LightGBM training trees | No | `ml/training` unused live |
| DQN / PPO / TFT / FinBERT | **NOT PRESENT** | `ML_STATUS.md` |

### 8.5 Feature / label / promotion pipeline (ML path only)

Offline: dataset builders under `tradingbot/ml/data/` and `ml/research/phase*`. Promotion: `phase17d` (`TREND_MODEL_VERSION` env, default active `v41`, rollback `v40`). **None of this runs on the default PA daemon.**

---

## 9. Risk truth

`RiskGate.evaluate` (`tradingbot/adapters/risk_gate.py`) is mandatory on the kernel path.

### 9.1 Gate order (code)

1. `entries_frozen()` — MT5 equity unavailable / stale-data freeze (`_ReliabilityKernel`)
2. `_capital_adaptive_gates` — micro / confluence / H1 alignment when profile requires
3. `_live_gates`:
   - max positions total / per symbol (loss-streak can cap per-symbol to 1)
   - news blackout (`USE_NEWS_FILTER`, 30 min)
   - Friday no-entry after configured hour
   - **spread**: `mt5.symbol_info_tick`; **None → 999.0 pips → reject**
   - no opposite position
   - HTF alignment if required (M5 preset: **false**)
   - `check_market_filters` (ATR percentile / regime) for non-VOL
4. Daily trades / cooldown / daily loss (`_tracker.check_entry_allowed`)
5. `risk_logic.can_trade` (limits)
6. Meta score / `apply_pa_meta_decision` for PA signals
7. Sizing / micro feasibility (`evaluate_micro_feasible_risk`) — abnormal stop, compressed stop, `MICRO_INFEASIBLE_RISK`

### 9.2 Rejection reasons (non-exhaustive, from code)

`MT5 equity unavailable`, capital-adaptive reasons, max positions, news, Friday, spread, opposite position, HTF, market filters, cooldown / max trades / daily loss, `risk_logic` denials, `meta rejected`, `MICRO_*`, `ABNORMAL_STOP_DISTANCE`, `MICRO_STOP_COMPRESSED`.

### 9.3 Sizing

`RISK_PER_TRADE` default **0.005**. Micro planner can compress lots. Exact tick-value / contract-spec formula is **broker-dependent**. Prior audit: `order_value(0.01, 2000)` **XAUUSD_i → 2,000** vs **XAUUSD → 2,000,000**. Identity **unproven**.

### 9.4 UNKNOWN risk items

Tick-value live, commission schedule, whether news calendar is populated, whether meta `should_gate()` is true **today**.

---

## 10. Execution truth

`Mt5ExecutionAdapter.execute` (`tradingbot/adapters/mt5_execution.py`):

| Mode | Condition | Broker order |
|------|-----------|--------------|
| Dry-run | `is_dry_run()` | **No** — journals `dry_run` |
| Paper | `is_paper()` | **No** — `PaperTradeRecorder` |
| Live | `--execute` and not dry/paper | **Yes** — `guarded_order_send` + `_order_send_with_retry` |

Also: MT5 connect, broker symbol reconcile, AutoTrading ready, current price, SL/TP on request. Slippage is **logged** from fill vs request when a result exists.

| Topic | Status |
|-------|--------|
| Spread handling | RiskGate pre-trade; execution uses live quote |
| Slippage | Recorded after send; **not** a pre-trade model on PA path |
| Commission | **UNKNOWN** — no class-A tape |
| Partial fills | **UNKNOWN** / not fully specified in this audit |
| Retries | `_order_send_with_retry` exists |
| Duplicate prevention | PA dedup minutes + position / opposite gates |
| Fail-closed | Missing tick → spread 999 reject; no price → no order; AutoTrading fail → no order |
| `PIPELINE_TIMEOUT_MS` | **Not** this adapter |

Daemon starts with `--execute`. That is **requested live orders** if MT5 is up and RiskGate allows.

---

## 11. Data / feature truth

### 11.1 Live

| Item | Truth |
|------|--------|
| Symbol | `PRIMARY_SYMBOL = "XAUUSD_i"` |
| Timeframe | Kernel `5m` when router on |
| Bars | `Mt5MarketDataAdapter`; **forming bar excluded** in SignalStage |
| Spread/tick stores | Live tick via MT5 at RiskGate; empty historical spread store is a research gap |
| Session | UTC hours on bar index |

### 11.2 Research

| Item | Truth |
|------|--------|
| Symbol | Typically **XAUUSD** parquet (e.g. PA replay 2004-06-11 → 2026-07-17) |
| Timeframe | M5 for isolated PA / v41 TREND |
| Labels / features | ML feature builders — **not** on PA live path |
| `spread_pips` in datasets | OHLC `(high-low)/pip` clipped — **class D vs live tick** (v41 decision audit) |

### 11.3 RESEARCH XAUUSD vs LIVE XAUUSD_i

**Not proven identical.** Economic `order_value` formulas disagree by 1000× in the isolated audit. No paired bid/ask tape. **P0 unknown.**

Look-ahead: live uses closed bars. Research replays that used `evaluate_gold_setup` on historical frames must keep the same closed-bar convention; PA audit replay documented fill=close, same-bar SL+TP→SL.

---

## 12. Test truth

~230 `test_*.py` files. Many are **historical phase** tests (phase14–phase51, ml_phase*). They prove **local contracts**, not that the daemon is profitable.

| Bucket | Examples | What they prove |
|--------|----------|-----------------|
| Isolated research | `test_v41_*`, `test_pa_live_audit.py` | Offline replay / audit invariants |
| Factory / startup | `test_startup_validator.py`, `test_phase24k.py` | Selection labels / misconfig |
| Risk / meta | `test_phase14_2b_risk.py`, `test_phase20y3_meta_observer.py` | Unit / observer |
| Kernel / pipeline | `test_phase15b_kernel_integration.py` | Often **mocked** or ML-path |
| Dashboard / HTA | `test_hta_html_fragments.py` | UI fragments; HTA mostly deleted |
| This phase | `tests/test_full_repository_audit.py` | Artifact presence + live invariants |

**Critical production paths with weak/no end-to-end tests:**

- Full daemon `START_BOT` → MT5 `order_send` (intentionally not run here)
- Live meta `should_gate()` on current account
- XAUUSD_i contract spec vs research XAUUSD
- Spread/slippage/commission realism

**Do not treat green research tests as live edge.**

Stale risk: tests that assume VOL-default or Adaptive-default live engine (see KI-001). Prefer factory tests that follow **effective** selection.

---

## 13. Documentation truth

| Document | Class | Notes |
|----------|-------|--------|
| `docs_v2/01_truth/FULL_REPOSITORY_SOURCE_OF_TRUTH.md` | **CURRENT** (this audit) | Overlay 2026-09-01 |
| `docs_v2/01_truth/SOURCE_OF_TRUTH.md` | **MIXED** | Hierarchy still valid; dated **2026-08-22**; baseline commit `57bf778c…` |
| `docs_v2/01_truth/CURRENT_STATE.md` | **MIXED** | Live path still largely correct; Last Verified **2026-08-22**; later v41/PA class results not fully merged |
| `docs_v2/01_truth/KNOWN_ISSUES.md` | **MIXED** | KI-001 Adaptive-default docs still relevant for `docs/` |
| `docs_v2/07_ml/ML_STATUS.md` | **CURRENT** for ML-off / v41 C / PA B pointers | Last Verified 2026-08-31 |
| `docs_v2/07_ml/V41_*.md` | **CURRENT** research evidence | Do not promote to live |
| `docs_v2/04_strategy/PA_LIVE_EDGE_AUDIT.md` | **CURRENT** research | PA class B |
| `docs_v2/03_runtime/STARTUP.md`, `LIVE_LOOP.md`, `CONFIGURATION.md` | **MIXED** | Verify against factory/daemon; do not assume rewritten |
| `docs_v2/04_strategy/STRATEGY.md` | **MIXED** | Confirm PA lock vs any Adaptive wording |
| `docs_v2/README.md` | **MIXED** | Read-order still lists older SOT first; this file is the 1.5.61 map |
| `docs/robot_behavior_audit/*` | **STALE / HISTORICAL** | Adaptive-as-default claims (KI-001) |
| `docs/CAPABILITIES.md`, `docs/ONBOARDING_FA.md` | **MIXED / HISTORICAL** | Not re-audited line-by-line here |
| Factory docstring | **CURRENT** after comment-only fix | Branch order: router before Adaptive/VOL — comment dirt vs older VOL-default docs |

**This phase does not rewrite those documents.** Contradictions are listed in §14.

---

## 14. Known contradictions

Discrepancy class: **A** consistent · **B** partial · **C** docs/config mismatch · **D** runtime contradiction · **E** unknown.

| ID | Class | CODE | CONFIG/ENV | DOCS | TESTS | ARTIFACTS |
|----|-------|------|------------|------|-------|-----------|
| Live PA owner | **A** | Router + PA lock | daemon + `PA_PRODUCTION_LOCK` | `CURRENT_STATE`, PA audit | factory/router tests | — |
| ML kernel off | **A** | `is_ml_kernel_enabled` | daemon false | `ML_STATUS` | — | `data/ml/live/` looks “live” but is **historical** — do not override code |
| ML shadow default | **C** | `is_ml_shadow_enabled` default **false** | daemon **true** | `CURRENT_STATE` documents the split | — | — |
| CLI TF/symbol | **C** | `__main__` defaults XAUUSD/M15 | live `XAUUSD_i` / 5m | Easy to misread | backtest tests may use CLI | — |
| BacktestConfig TF | **A** (post-25B) | `tradingbot/backtest/config.py` default **M5** | live M5 | PA audit updated Phase 26N | backtest tests | Was **C** (M1) pre-Phase-25B |
| `london_sweep` name | **C** | mode routes to `evaluate_m5_london_sweep` | London **off**, NY 15–16 | File docstring still describes London 07–10 | PA tests | — |
| Base PA `quality` | **C** | `PRICE_ACTION_CONFIG` | M5 override `gold_ny_sweep` | Comments mention M15 60d matrix | — | — |
| `MIN_CONFIDENCE` 0.55 vs 0.52 | **C** | `LIVE_TRADING_CONFIG` vs preset | effective M5 **0.52** | easy mismatch | — | — |
| `DEMO_MODE=true` vs `--execute` | **C/D** | dict says demo | daemon execute | “demo” wording | — | — |
| Adaptive flag missing from `LIVE_TRADING_CONFIG` | **C** | factory get False; Adaptive class default **True** | daemon sets false | — | — | — |
| `engine_settings` hardcoded MT5 fallbacks | **D** | fallbacks exist | env should override | live.py says credentials MUST be env | — | **do not print values** |
| Docs dated 2026-08-22 | **C** | later audits exist | — | SOT/CURRENT_STATE stale dates | — | v41/PA JSON newer |
| Legacy `docs/` Adaptive default | **C** | PA router | — | KI-001 | — | — |
| XAUUSD vs XAUUSD_i | **E** | two symbols | live `_i` | research docs XAUUSD | isolated tests | parquet vs broker |
| Meta continuous gate | **E** | wired | threshold 0.38 | ML_STATUS NOT PROVEN | observer tests | 4 historical jsonl rows |
| Dataset `spread_pips` vs tick | **D** | research proxy | live tick | V41_DECISION_AUDIT | v41 tests | phase15_51 JSON |
| Factory comment vs very old VOL-default docs | **C** | router-first | — | some research md | — | — |

No silent resolution.

---

## 15. Critical unknowns

| ID | Pri | What | Why unknown | Evidence that would resolve | MT5 / operator? |
|----|-----|------|-------------|-----------------------------|-----------------|
| operator `.env` overrides | **P0** | Whether production env flips ML, PA lock, session bypass, execute | Secrets not read | Sanitized flag dump (no passwords) | Operator |
| XAUUSD vs XAUUSD_i identity | **P0** | Economic equivalence | `order_value` split; no paired tape | `symbol_info` + bid/ask + contract size | **MT5** |
| Round-trip costs | **P0** | Spread/slip/commission | No class-A tape (n=17 entry-only fills historically) | Exported tickets + bid/ask | **MT5** |
| Meta enforcement today | **P1** | Does meta reject live PA now? | `should_gate` + current journal | Current-day `meta_decisions.jsonl` | Operator (bot already logging) |
| `DEMO_DISABLE_SESSION_FILTER` | **P1** | Session bypass | env | Sanitized flag | Operator |
| News calendar populated | **P1** | News gate always-pass vs real blackout | calendar source not proven here | Runtime news store inspect | Operator |
| Partial fills / commission | **P1** | Execution economics | adapter does not model commission | Broker spec + tickets | **MT5** |
| `engine_settings` fallbacks used? | **P1** | Hardcoded credential path | env unknown | Confirm env set; rotate if fallbacks ever used | Operator |
| Whether daemon is running | **P2** | This audit did not inspect processes for “bot started” beyond safety | — | Operator | — |
| Full import graph of all 2000+ files | **P3** | JSON has key-module AST edges, not a complete call graph | cost | Optional static graph job | No |
| Every TODO/FIXME owner | **P3** | Counts only | — | Targeted sweep | No |

---

## 16. Recommended next investigation areas

**Do not start Phase 1.5.62 from this document automatically.** Suggested investigations only:

1. Operator-sanitized env (flags only) to close P0 config unknown.  
2. MT5 `symbol_info` snapshot for `XAUUSD_i` vs research `XAUUSD` (identity).  
3. Class-A cost tape (bid/ask + tickets) before any size-up.  
4. Current-day meta journal vs `should_gate()`.  
5. Line-by-line refresh of `CURRENT_STATE.md` / `SOURCE_OF_TRUTH.md` dates (docs phase, not this one).  
6. Confirm `engine_settings` fallbacks are never used; do not commit secrets.  

**Not recommended:** activate ML, open v41 gate, copy v40 calibration, disable PA lock, change `PIPELINE_TIMEOUT_MS`, or treat PA class B / v41 class C as production size-up.

---

## Dead / incomplete / misleading (inventory, not a cleanup list)

| Item | Note |
|------|------|
| 14 disabled `ACTIVE_STRATEGIES` | Names exist; flags false |
| M15/H4 live loop | Presets exist; not iterated on router path |
| `evaluate_m5_scalp` / `evaluate_h4_swing` | Code present; not live mode |
| ML kernel + `PIPELINE_TIMEOUT_MS` | Unreachable on default path |
| `evaluate_setup_at` (if present) | Not on live PA hop list |
| Research `phase*` setting `USE_ML_KERNEL=1` | Misleading if mistaken for daemon |
| `GOLD_STRATEGY_MODE=london_sweep` | Name ≠ London session |
| `data/ml/live/` | Historical ML kernel, not PA owner |
| HTA scripts | Many deleted; leftover tests/docs |
| TODO/FIXME | Count in `summary.json` `todo_fixme` |

---

## Safety (this phase)

| Question | Answer |
|----------|--------|
| MT5 started? | **NO** (not by this audit) |
| Bot started? | **NO** |
| Orders sent? | **NO** |
| `.env` modified? | **NO** (not read) |
| ML gate opened? | **NO** |
| `PA_PRODUCTION_LOCK` changed? | **NO** |
| Router default changed? | **NO** |
| RiskGate changed? | **NO** |
| Execution changed? | **NO** |
| Adaptive live wiring changed? | **NO** |
| `PIPELINE_TIMEOUT_MS` changed? | **NO** |
| Model artifacts modified? | **NO** |
| Historical JSON rewritten? | **NO** |
| Git commit? | **NO** |

---

## Citation index (minimum)

- `tradingbot/__main__.py::main`
- `tradingbot/application/bootstrap.py::build_kernel_live`
- `tradingbot/application/live_runner.py::run_live_loop`
- `tradingbot/ml/integration/factory.py::build_strategy_registry`
- `tradingbot/adapters/multi_engine_router.py::MultiEngineRouterRegistry.generate_signal`
- `tradingbot/config/live.py::PRIMARY_SYMBOL`, `LIVE_TRADING_CONFIG`, `get_live_config`
- `tradingbot/config/pa_symbol_tf_presets.py` `XAUUSD.M5`
- `tradingbot/config/strategies.py::ACTIVE_STRATEGIES`
- `tradingbot/domain/gold_strategies/router.py::evaluate_gold_setup`
- `tradingbot/domain/gold_strategies/m5_london_sweep.py::evaluate_m5_london_sweep`
- `tradingbot/adapters/risk_gate.py::RiskGate.evaluate`
- `tradingbot/adapters/mt5_execution.py::Mt5ExecutionAdapter.execute`
- `tradingbot/ml/integration/config.py::is_ml_kernel_enabled`, `is_ml_shadow_enabled`
- `tradingbot/ml/integration/kernel_adapter.py::PIPELINE_TIMEOUT_MS`
- `tradingbot/ml/confidence_engine/engine_calibrator.py::TREND_MODEL_ID`
- `tradingbot/ml/phase15a/config.py::TREND_ENGINE_ID`, `TREND_ENGINE_V41_ID`
- `tradingbot/ml/phase17d/versioning.py::resolve_active_trend_engine_id`
- `tradingbot/ml/shadow/shadow_gate.py::evaluate_ml_live_gate`
- `scripts/start_live_daemon.ps1`
- `tradingbot/backtest/config.py::BacktestConfig`

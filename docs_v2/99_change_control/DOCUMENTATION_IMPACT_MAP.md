# Documentation Impact Map

**Status:** VERIFIED  
**Last verified:** 2026-09-01  
**Canonical-Entry:** false  
**Epistemic-Role:** OWNER of CODE → documentation impact relations.  
**Operator-effective state:** UNKNOWN  

If a listed production file changes, the named **owner** document is **STALE** until Cursor reverifies `path::symbol` claims. Derived copies in the entry and bootstrap are also STALE if they repeat the owned fact.

Verifier: `tradingbot/ml/research/documentation_freshness/` plus `documentation_consistency`.  
Freshness rule: watched-file SHA-256 ≠ canonical snapshot → **STALE**. No TTL. Tests must not rewrite the canonical snapshot.

Derived documents for almost every row: `PROJECT_SOURCE_OF_TRUTH.md`, `CHATGPT_BOOTSTRAP.md`.

| Code component | Truth domain | Owner document | Derived documents | Verifier | Safety |
|----------------|--------------|----------------|-------------------|----------|--------|
| `tradingbot/ml/integration/factory.py` | LIVE_CONTRACT / ARCHITECTURE | CURRENT_RUNTIME_STATE.md, SYSTEM_ARCHITECTURE.md | entry, bootstrap | freshness + consistency | PRODUCTION-CRITICAL |
| `tradingbot/ml/phase15a/config.py` | ML ids | MODEL_REGISTRY.md, CALIBRATION_STATE.md | ML_SYSTEM_STATE.md, bootstrap | freshness + consistency | PRODUCTION-SENSITIVE |
| `tradingbot/config/live.py` | CONFIGURATION / LIVE_CONTRACT | CONFIGURATION_TRUTH.md, CURRENT_RUNTIME_STATE.md | entry, bootstrap | freshness + consistency | PRODUCTION-CRITICAL |
| `tradingbot/ml/integration/kernel_adapter.py` | CALIBRATION | CALIBRATION_STATE.md | ML_SYSTEM_STATE.md | freshness + consistency | PRODUCTION-SENSITIVE |
| `tradingbot/adapters/risk_gate.py` | RISKGATE | RISKGATE_SPEC.md | bootstrap §6, entry | freshness + consistency | PRODUCTION-CRITICAL |
| `tradingbot/adapters/mt5_execution.py` | EXECUTION | EXECUTION_FLOW.md, RISK_AND_EXECUTION_BOUNDARY.md | bootstrap §7 | freshness + consistency | PRODUCTION-CRITICAL |
| `tradingbot/ml/confidence_engine/engine_calibrator.py` | CALIBRATION | CALIBRATION_STATE.md | ML_SYSTEM_STATE.md, bootstrap | freshness + consistency | PRODUCTION-SENSITIVE |
| `tradingbot/ml/confidence_engine/calibration_policy.py` | CALIBRATION | CALIBRATION_STATE.md | MODEL_REGISTRY.md | freshness + consistency | PRODUCTION-SENSITIVE |
| `tradingbot/ml/shadow/shadow_gate.py` | ML | ML_SYSTEM_STATE.md | bootstrap §9 | freshness + consistency | PRODUCTION-SENSITIVE |
| `tradingbot/adapters/multi_engine_router.py` | LIVE_PATH | LIVE_RUNTIME_PATH.md, PRODUCTION_RESEARCH_BOUNDARY.md | entry, bootstrap | freshness + consistency | PRODUCTION-CRITICAL |
| `tradingbot/services/pa_production_lock.py` | LIVE_CONTRACT | CURRENT_RUNTIME_STATE.md | bootstrap, KNOWLEDGE_CONTRACT.md | freshness + consistency | PRODUCTION-CRITICAL |
| `engine/strategies/price_action_strategy.py` | PA_STRATEGY | PRICE_ACTION_LIVE_SPEC.md | ACTIVE_STRATEGIES.md, bootstrap | freshness + consistency | PRODUCTION-CRITICAL |
| `tradingbot/config/pa_symbol_tf_presets.py` | PA_STRATEGY | PRICE_ACTION_LIVE_SPEC.md | CURRENT_RUNTIME_STATE.md, bootstrap | freshness + consistency | PRODUCTION-CRITICAL |
| `tradingbot/config/strategies.py` | STRATEGY_LIST | ACTIVE_STRATEGIES.md | entry | freshness + consistency | PRODUCTION-CRITICAL |
| `tradingbot/config/dotenv_loader.py` | CONFIGURATION | CONFIGURATION_TRUTH.md | bootstrap | freshness + consistency | PRODUCTION-SENSITIVE |
| `tradingbot/config/engine_settings.py` | CONFIGURATION | CONFIGURATION_TRUTH.md | KNOWN_UNKNOWNS (CX-016) | freshness + consistency | PRODUCTION-SENSITIVE |
| `tradingbot/domain/gold_strategies/m5_london_sweep.py` | PA_STRATEGY | PRICE_ACTION_LIVE_SPEC.md | bootstrap | freshness + consistency | PRODUCTION-CRITICAL |
| `tradingbot/domain/gold_strategies/router.py` | PA_STRATEGY | PRICE_ACTION_LIVE_SPEC.md | LIVE_RUNTIME_PATH.md, bootstrap | freshness + consistency | PRODUCTION-CRITICAL |
| `tradingbot/domain/pa_hardening.py` | PA_STRATEGY | PRICE_ACTION_LIVE_SPEC.md | LIVE_RUNTIME_PATH.md | freshness + consistency | PRODUCTION-CRITICAL |
| `tradingbot/domain/ohlcv.py` | DATA_CONTRACTS | DATA_CONTRACTS.md | LIVE_RUNTIME_PATH.md, bootstrap | freshness + consistency | PRODUCTION-CRITICAL |
| `tradingbot/pipeline/signal_stage.py` | LIVE_PATH | LIVE_RUNTIME_PATH.md | DATA_CONTRACTS.md, entry | freshness + consistency | PRODUCTION-CRITICAL |
| `tradingbot/adapters/legacy_strategy_registry.py` | LIVE_PATH | LIVE_RUNTIME_PATH.md | SYSTEM_ARCHITECTURE.md | freshness + consistency | PRODUCTION-CRITICAL |
| `tradingbot/adapters/mt5_market_data.py` | DATA_CONTRACTS | DATA_CONTRACTS.md | DATA_PIPELINE.md | freshness + consistency | PRODUCTION-CRITICAL |
| `tradingbot/ml/risk_intelligence/risk_types.py` | CALIBRATION | CALIBRATION_STATE.md | V41 research docs (class only) | freshness + consistency | PRODUCTION-SENSITIVE |
| `tradingbot/services/kill_switch.py` | LIVE_PATH | STARTUP_AND_SHUTDOWN.md | LIVE_RUNTIME_PATH.md | freshness + consistency | PRODUCTION-SENSITIVE |
| `scripts/start_bot.py` | LIVE_PATH | STARTUP_AND_SHUTDOWN.md | LIVE_RUNTIME_PATH.md, entry | freshness + consistency | PRODUCTION-SENSITIVE |
| `scripts/start_live_daemon.ps1` | CONFIGURATION / LIVE_PATH | STARTUP_AND_SHUTDOWN.md, CONFIGURATION_TRUTH.md | CURRENT_RUNTIME_STATE.md, bootstrap | freshness + consistency | PRODUCTION-CRITICAL |
| `scripts/run_live_watchdog.py` | LIVE_PATH | STARTUP_AND_SHUTDOWN.md | LIVE_RUNTIME_PATH.md | freshness + consistency | PRODUCTION-CRITICAL |
| `tradingbot/application/bootstrap.py` | LIVE_PATH | LIVE_RUNTIME_PATH.md | PRODUCTION_RESEARCH_BOUNDARY.md | freshness + consistency | PRODUCTION-CRITICAL |
| `tradingbot/application/live_runner.py` | LIVE_PATH | STARTUP_AND_SHUTDOWN.md | LIVE_RUNTIME_PATH.md | freshness + consistency | PRODUCTION-CRITICAL |
| `tradingbot/ml/integration/config.py` | ML / CONFIGURATION | CONFIGURATION_TRUTH.md | ML_SYSTEM_STATE.md, bootstrap | freshness + consistency | PRODUCTION-CRITICAL |
| `tradingbot/__main__.py` | LIVE_PATH | LIVE_RUNTIME_PATH.md | STARTUP_AND_SHUTDOWN.md, CX-015 | freshness + consistency | PRODUCTION-CRITICAL |
| `start/START_BOT.bat` | LIVE_PATH | STARTUP_AND_SHUTDOWN.md | LIVE_RUNTIME_PATH.md, entry, bootstrap | freshness + consistency | PRODUCTION-CRITICAL |
| `start/_load_env.bat` | CONFIGURATION | CONFIGURATION_TRUTH.md | STARTUP_AND_SHUTDOWN.md | freshness + consistency | PRODUCTION-SENSITIVE |

After edits: update owner doc → refresh **derived** entry/bootstrap copies if flags/path/SL/TP/hops changed → run freshness + consistency tests. Canonical snapshot regeneration is **explicit** (`--regenerate-baseline`), never a side effect of pytest.

**Symbol / responsibility** for each watched file: `tradingbot/ml/research/documentation_freshness/scanner.py::WATCH_REASONS`.

### DO_NOT_WATCH (explicit, not omitted)

| Path | Class | Justification |
|------|--------|----------------|
| `tradingbot/domain/gold_strategies/m5_scalp.py` | UNUSED-ON-DEFAULT-LIVE | Mode dispatch in watched `router.py`. |
| `tradingbot/domain/gold_strategies/m15_intraday.py` | UNUSED-ON-DEFAULT-LIVE | Default live TF is M5 only. |
| `tradingbot/domain/gold_strategies/h4_swing.py` | UNUSED-ON-DEFAULT-LIVE | Default live TF is M5 only. |
| `tradingbot/ml/research/**` | RESEARCH_ONLY | Must not import into `build_kernel_live`. |
| `tradingbot/ml/research/documentation_freshness/scanner.py` | RESEARCH_ONLY | Watcher must not watch itself. |

If `GOLD_STRATEGY_MODE` / `_resolve_mode` changes, `router.py` (watched) plus this map must be updated.

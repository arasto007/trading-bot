# Documentation Watched-Code Audit

**Status:** VERIFIED  
**Last verified:** 2026-09-01  
**Canonical-Entry:** false  
**Epistemic-Role:** OWNER of FRESHNESS (which files are watched, why, STALE/BROKEN/UNKNOWN). Not a runtime SOT.  
**Operator-effective state:** UNKNOWN  
**JSON:** `data/ml/reports/documentation_memory_hardening_v2/watched_code_audit.json`

This file does not own runtime facts. CODE remains supreme. Files are classified **WATCH**, **DO_NOT_WATCH**, **RESEARCH_ONLY**, or **UNKNOWN**.

Freshness WATCHED lives in `tradingbot/ml/research/documentation_freshness/scanner.py::WATCHED`.

---

## Rule

WATCH only if a change can materially alter ChatGPT's documented understanding of live strategy, routing, PA, RiskGate, execution, configuration precedence, ML activation, calibration, daemon startup, kernel construction, data contracts, or safety locks.

Do not watch unused evaluators merely because they exist. Do not watch `tradingbot/ml/research/**`.

---

## Decisions

| Path | Decision | Domain | Owner | Safety | Reason |
|------|----------|--------|-------|--------|--------|
| `tradingbot/ml/confidence_engine/calibration_policy.py` | WATCH | CALIBRATION | CALIBRATION_STATE.md | PRODUCTION-SENSITIVE | Impact-map gap closed. Constants on ML path. |
| `tradingbot/domain/gold_strategies/router.py` | WATCH | PA_STRATEGY | PRICE_ACTION_LIVE_SPEC.md | PRODUCTION-CRITICAL | `evaluate_gold_setup` live dispatch. |
| `tradingbot/domain/pa_hardening.py` | WATCH | PA_STRATEGY | PRICE_ACTION_LIVE_SPEC.md | PRODUCTION-CRITICAL | `apply_setup_hardening` can drop setups. |
| `tradingbot/pipeline/signal_stage.py` | WATCH | LIVE_PATH | LIVE_RUNTIME_PATH.md | PRODUCTION-CRITICAL | `SignalStage.run` → `exclude_forming_bar`. |
| `tradingbot/__main__.py` | WATCH | LIVE_PATH | LIVE_RUNTIME_PATH.md | PRODUCTION-CRITICAL | `--loop --execute`; CLI `--tf` M15 vs live M5. |
| `start/START_BOT.bat` | WATCH | LIVE_PATH | STARTUP_AND_SHUTDOWN.md | PRODUCTION-CRITICAL | Documented Windows start. |
| `start/_load_env.bat` | WATCH | CONFIGURATION | CONFIGURATION_TRUTH.md | PRODUCTION-SENSITIVE | Loads `.env` into cmd; values UNKNOWN. |
| `tradingbot/ml/risk_intelligence/risk_types.py` | WATCH | CALIBRATION | CALIBRATION_STATE.md | PRODUCTION-SENSITIVE | factory import; v40 quality factor key. |
| `tradingbot/adapters/mt5_market_data.py` | WATCH | DATA_CONTRACTS | DATA_CONTRACTS.md | PRODUCTION-CRITICAL | Live bar source. |
| `tradingbot/adapters/legacy_strategy_registry.py` | WATCH | LIVE_PATH | LIVE_RUNTIME_PATH.md | PRODUCTION-CRITICAL | Router inner PA hop. |
| `tradingbot/services/kill_switch.py` | WATCH | LIVE_PATH | STARTUP_AND_SHUTDOWN.md | PRODUCTION-SENSITIVE | Documented hop 21. |
| `tradingbot/config/engine_settings.py` | WATCH | CONFIGURATION | CONFIGURATION_TRUTH.md | PRODUCTION-SENSITIVE | Cited fallbacks (CX-016). Secrets not documented. |
| `tradingbot/domain/gold_strategies/m5_scalp.py` | DO_NOT_WATCH | PA_STRATEGY | PRICE_ACTION_LIVE_SPEC.md | UNUSED-ON-DEFAULT-LIVE | Mode dispatch is in watched router. |
| `tradingbot/domain/gold_strategies/m15_intraday.py` | DO_NOT_WATCH | PA_STRATEGY | PRICE_ACTION_LIVE_SPEC.md | UNUSED-ON-DEFAULT-LIVE | Not default live. |
| `tradingbot/domain/gold_strategies/h4_swing.py` | DO_NOT_WATCH | PA_STRATEGY | PRICE_ACTION_LIVE_SPEC.md | UNUSED-ON-DEFAULT-LIVE | Not default live. |
| `tradingbot/ml/research/**` | RESEARCH_ONLY | PRODUCTION_BOUNDARY | PRODUCTION_RESEARCH_BOUNDARY.md | RESEARCH | Must not import into `build_kernel_live`. |
| complete production call graph | UNKNOWN | LIVE_PATH | LIVE_RUNTIME_PATH.md | UNKNOWN | No complete static graph. |

Previously watched factory, live.py, RiskGate, execution, router, PA lock, presets, m5_london_sweep, ohlcv, daemon scripts, bootstrap, live_runner, ML flags/calibrator/shadow remain WATCH.

---

## Completeness

Every WATCH path above is required in `WATCHED` and in `DOCUMENTATION_IMPACT_MAP.md`.

Remaining UNKNOWN: files not listed here may still affect live behavior. That gap is **UNK-011** (complete import graph) and must not be guessed away.

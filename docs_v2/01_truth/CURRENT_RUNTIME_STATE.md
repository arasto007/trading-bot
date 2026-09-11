# Current Runtime State

**Canonical-Entry:** false  
**Status:** VERIFIED (code-default live contract; not a live process probe)  
**Last verified:** 2026-09-09  
**Epistemic-Role:** OWNER of LIVE_CONTRACT.  
**Operator-effective state:** UNKNOWN  

> Supersedes `CURRENT_STATE.md` as the LIVE_CONTRACT owner entry (`PROJECT_SOURCE_OF_TRUTH.md` navigation; `documentation_memory_hardening_v2` `REQUIRED_OWNERS`).

This document owns **what is selected on the documented default live path** as **CODE DEFAULT** vs **daemon-if-unset**. It does **not** claim operator-effective `.env` values or that a daemon/MT5 session is running now.

**CODE DEFAULT ≠ DAEMON IF UNSET ≠ OPERATOR EFFECTIVE ≠ CURRENT RUNTIME PROCESS.**

---

## 1. Live selection (CODE DEFAULT)

| Item | CODE DEFAULT | Daemon if unset | Operator effective | Current process | Evidence |
|------|--------------|-----------------|--------------------|-----------------|----------|
| Symbol | `XAUUSD_i` | same | UNKNOWN | UNKNOWN — needs operator input | `tradingbot/config/live.py::PRIMARY_SYMBOL` |
| Kernel timeframes | `["5m"]` when router/adaptive/vol on | same | UNKNOWN | UNKNOWN | `get_live_config()` |
| Strategy | `priceaction` only | same | UNKNOWN | UNKNOWN | `ACTIVE_STRATEGIES`; `factory.py::build_strategy_registry` |
| Preset | `gold_ny_sweep` | same | UNKNOWN | UNKNOWN | `pa_symbol_tf_presets.py` |
| Session | NY 15–16 UTC; London **off** | same | UNKNOWN | UNKNOWN | same preset; `PRICE_ACTION_LIVE_SPEC.md` |
| Loop interval | 30s | same | UNKNOWN | UNKNOWN | `LIVE_TRADING_CONFIG['LOOP_INTERVAL']` |

Source peers: `CHATGPT_BOOTSTRAP.md` §2; `CONFIGURATION_TRUTH.md`; superseded snapshot `CURRENT_STATE.md` (dates lag; code citations re-checked 2026-09-09).

---

## 2. Flags (CODE DEFAULT vs daemon-if-unset)

| Flag | CODE DEFAULT | Daemon if unset | Operator | Evidence |
|------|--------------|-----------------|----------|----------|
| `USE_ML_KERNEL` | unset → false | `"false"` | UNKNOWN | `is_ml_kernel_enabled`; `CONFIGURATION_TRUTH.md` |
| `PA_PRODUCTION_LOCK` | true | not set (code default applies) | UNKNOWN | `is_pa_production_lock` |
| `MULTI_ENGINE_ROUTER_ENABLED` | true | true | UNKNOWN | factory / daemon |
| `ENABLE_ML_SHADOW` | false | true | UNKNOWN | shadow wrap log-only |
| `VOL_REGIME_ENABLED` | false | false | UNKNOWN | router probe, not selected under lock |
| `ADAPTIVE_REGIME_ENABLED` | absent from dict; factory False | false | UNKNOWN | `CONFIGURATION_TRUTH.md` |
| `PIPELINE_TIMEOUT_MS` | 500.0 | unused on PA path | n/a | `live.py` |

`is_pa_production_lock` = lock **and** Adaptive off **and** VOL off (`CHATGPT_BOOTSTRAP.md` §5).

---

## 3. Engine selection narrative

On the default daemon path with PA production lock held:

- Selected live owner: **Price Action** (`priceaction` / `gold_ny_sweep`).
- VOL and Adaptive signals may be **generated** on the router and are **not selected** while the lock holds (`multi_engine_router.py`; `PROJECT_SOURCE_OF_TRUTH.md` §4).
- ML kernel is **off** unless explicitly enabled; shadow wrap is log-only if enabled (`CHATGPT_BOOTSTRAP.md` §9).

Pipeline: Data → Indicators → Signal → SignalFilter → Risk → Execution (`PROJECT_SOURCE_OF_TRUTH.md` §3). Forming bar dropped via `exclude_forming_bar`.

---

## 4. Components on the default production path

| Component | CODE DEFAULT status | Evidence |
|-----------|---------------------|----------|
| `TradingKernel` | wired | `live_runner.py` |
| `MultiEngineRouterRegistry` | wired when router on | `factory.py::build_strategy_registry` |
| `RiskGate` | mandatory on kernel path | `RiskGate.evaluate` |
| `Mt5ExecutionAdapter` | wired; orders only in live `--execute` | `EXECUTION_FLOW.md` |
| `SignalFilterStage` (WPSQF) | implemented; **default OFF** | `signal_filter_mode.py`; `CURRENT_STATE.md` |
| `PositionProtector` | **default off** | `live_runner.py` (cited in `CURRENT_STATE.md`) |
| ML kernel | disabled | daemon + `is_ml_kernel_enabled()` |
| Meta-labeler | wired; current-day enforcement **NOT PROVEN** | `RISKGATE_SPEC.md`; `CHATGPT_BOOTSTRAP.md` §6 |

---

## 5. Execution modes (code-defined)

| Mode | Activation | Broker orders |
|------|------------|---------------|
| Live execute | `--execute` + no dry-run/paper | Yes |
| Dry-run | no `--execute`, or dry-run env | No |
| Paper | `--paper` / paper env | Simulated |

Daemon startup passes `--execute`. Whether operator `.env` forces dry-run/paper: **UNKNOWN** (not read). Source: `CHATGPT_BOOTSTRAP.md` §7; `CURRENT_STATE.md` Execution Mode.

---

## 6. Unknowns (do not invent)

- Operator `.env` effective values (UNK-001) — **UNKNOWN**
- Whether a daemon / MT5 terminal is running **now** — **UNKNOWN — needs operator input**
- Demo `XAUUSD_i` vs Real `XAUUSD` **contract/economic** equivalence — **NOT PROVEN** / UNK-002
- Round-trip spread/commission completeness — UNK-003
- Current account balance / broker identity — **UNKNOWN — needs operator input**

Registry: `KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md`.

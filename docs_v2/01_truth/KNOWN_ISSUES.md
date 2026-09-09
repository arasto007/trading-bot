# Known Issues

> **Contradiction registry moved (2026-09-01):** `docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md`. This file is kept. KI-001 Adaptive-default docs remains valid for `docs/`.

## Status

- **Status:** VERIFIED (documented conflicts and code-identified risks)
- **Last Verified:** 2026-08-22
- **Verification Method:** Source-code inspection and comparison with legacy `docs/` claims
- **Verified against commit:** `57bf778c23cefffe508bb49079688b177796f67e`

## Scope

Documented problems, contradictions, and operational risks **observed in the repository**. This document does not propose fixes.

---

## P0 — Critical

### KI-001: Legacy documentation describes wrong live engine

| Field | Value |
|-------|-------|
| **Subsystem** | Strategy / documentation |
| **Description** | `docs/robot_behavior_audit/strategy_inventory.md` and `configuration_truth.md` state ADAPTIVE_REGIME is the active default live engine. Code default daemon path uses `MultiEngineRouterRegistry` with `PA_PRODUCTION_LOCK`, selecting Price Action only. |
| **Evidence** | `docs/robot_behavior_audit/strategy_inventory.md` (ADAPTIVE default claim); `scripts/start_live_daemon.ps1:34–38`; `tradingbot/adapters/multi_engine_router.py`; `tradingbot/services/pa_production_lock.py` |
| **Severity** | P0 |
| **Status** | OPEN — stale legacy docs; docs_v2 supersedes for current truth |

### KI-002: Misleading operator banner

| Field | Value |
|-------|-------|
| **Subsystem** | Operations |
| **Description** | `scripts/start_bot.py` previously printed `"START BOT — VOL_REGIME LIVE"` while the daemon set `VOL_REGIME_ENABLED=false`. Banner is now `"START BOT — PA ROUTER LIVE"`. |
| **Evidence** | `scripts/start_bot.py` (~line 95); `scripts/start_live_daemon.ps1:37–38` |
| **Severity** | P0 (operator confusion) |
| **Status** | RESOLVED — banner aligned with router + PA lock |

### KI-003: Silent no-trade misconfiguration path

| Field | Value |
|-------|-------|
| **Subsystem** | Strategy factory |
| **Description** | If `USE_ML_KERNEL` is **not set**, and router/adaptive/vol are all off, `UnconfiguredEngineRegistry` returns `None` for every signal — bot runs but never trades. |
| **Evidence** | `tradingbot/ml/integration/factory.py:235–236`, `UnconfiguredEngineRegistry.generate_signal` |
| **Severity** | P0 when misconfigured |
| **Status** | OPEN — by design when env unset; daemon mitigates by setting `USE_ML_KERNEL=false` |

---

## P1 — High

### KI-004: Dual position-management implementations

| Field | Value |
|-------|-------|
| **Subsystem** | Position management |
| **Description** | Both `Mt5PositionManager` (kernel) and `PositionProtector` / `PositionRecoveryService` (background) can send MT5 orders. Default path disables background services when router/adaptive/vol enabled. Enabling `--protector` without understanding ownership risks duplicate management. |
| **Evidence** | `tradingbot/application/live_runner.py:341–347`; `tradingbot/services/startup_validator.py` duplicate-ownership check; `mt5_position_manager.py` vs `position_protector.py` |
| **Severity** | P1 |
| **Status** | OPEN — mitigated on default config |

### KI-005: Meta-labeler artifact absence claim (RESOLVED — stale documentation)

| Field | Value |
|-------|-------|
| **Subsystem** | Risk / ML / documentation |
| **Description** | Prior docs stated `models/*.pkl` not found. Runtime files audit (2026-08-22) found `meta_labeler_m5.pkl`, `meta_labeler_m15.pkl`, `meta_labeler_h4.pkl`, and legacy `meta_labeler.pkl` under `models/`. Read-only load test: M5/M15/H4 loadable; `is_ready=True`. |
| **Evidence** | `models/` directory; E025–E027; `data/meta_decisions.jsonl` (4 historical decisions) |
| **Severity** | P1 (was); documentation drift |
| **Status** | **RESOLVED — STALE DOCUMENTATION** |

**Remaining operational distinction (not solved by artifact presence):**

- Continuous live meta-labeler enforcement is **NOT PROVEN** (only 4 historical decision records; last 2026-08-12).
- Current live trading is **NOT PROVEN** (see E029 healthcheck).

### KI-005b: Meta-labeler continuous live enforcement not proven

| Field | Value |
|-------|-------|
| **Subsystem** | Risk / ML |
| **Description** | Artifacts exist and historical rejections were logged, but sample size is tiny and stale relative to audit date. Cannot infer current rejection rate or that meta gating is actively enforcing today. |
| **Evidence** | `data/meta_decisions.jsonl`; E028, E029 |
| **Severity** | P2 |
| **Status** | OPEN — **NOT PROVEN** |

### KI-006: Entry freeze can skip all new trades while loop continues

| Field | Value |
|-------|-------|
| **Subsystem** | Runtime reliability |
| **Description** | `entries_frozen()` and stale M5 bar detection skip market cycles but position management still runs — appears "alive" without new entries. |
| **Evidence** | `tradingbot/services/runtime_truth.py`; `tradingbot/application/live_runner.py::_ReliabilityKernel`; `tradingbot/kernel/trading_kernel.py:168–174` |
| **Severity** | P1 |
| **Status** | OPEN — intentional safety behavior |

### KI-007: Real account blocked at startup

| Field | Value |
|-------|-------|
| **Subsystem** | Execution / safety |
| **Description** | Live execute mode requires demo account unless `TRADINGBOT_ALLOW_REAL=1`. |
| **Evidence** | `tradingbot/services/demo_account_guard.py`; `tradingbot/services/startup_validator.py:246–254` |
| **Severity** | P1 (may be intended) |
| **Status** | OPEN — documented behavior |

---

## P2 — Medium

### KI-008: `docs/CAPABILITIES.md` contradicts live timeframe behavior

| Field | Value |
|-------|-------|
| **Description** | Section 1 now states kernel M5-only when router is on. Residual later lines still mention M5/M15/H4 as “active” (presets, not simultaneous kernel cycle). |
| **Evidence** | `docs/CAPABILITIES.md`; `tradingbot/config/live.py:215–222` |
| **Severity** | P2 |
| **Status** | PARTIAL — header corrected; leftover MIXED wording remains |

### KI-009: Factory docstring says "VOL_REGIME default live"

| Field | Value |
|-------|-------|
| **Description** | `build_strategy_registry` docstring previously implied a VOL-default live path. |
| **Evidence** | `tradingbot/ml/integration/factory.py` now documents router-first branch order |
| **Severity** | P2 |
| **Status** | RESOLVED — docstring matches factory order |

### KI-010: Duplicate regime and spread implementations

| Field | Value |
|-------|-------|
| **Description** | Multiple regime classifiers and spread measurements exist across PA, VOL, adaptive, and RiskGate paths. Risk metadata regime may differ from signal routing context. |
| **Evidence** | `tradingbot/domain/risk_logic.py`; `tradingbot/strategies/adaptive_regime.py`; `tradingbot/adapters/risk_gate.py` |
| **Severity** | P2 |
| **Status** | OPEN — architectural debt |

### KI-011: `data/` gitignored — runtime evidence not in Git

| Field | Value |
|-------|-------|
| **Description** | Trade journal, runtime_truth, heartbeat files live under `data/` which is gitignored. Repository-only audits cannot see live runtime history. |
| **Evidence** | `.gitignore` (`data/`) |
| **Severity** | P2 |
| **Status** | BY DESIGN |

---

## P3 — Low

### KI-012: Single-commit Git history

| Field | Value |
|-------|-------|
| **Description** | Only one commit (`Initial snapshot - TradingBot New`). Change archaeology is limited. |
| **Evidence** | `git log` |
| **Severity** | P3 |
| **Status** | INFORMATIONAL |

### KI-013: Large research surface area

| Field | Value |
|-------|-------|
| **Description** | Hundreds of `scripts/phase*.py` and `tradingbot/ml/research/phase*` modules are not on the default live path but increase navigation noise. |
| **Evidence** | Repository tree |
| **Severity** | P3 |
| **Status** | INFORMATIONAL — not dead code proof for each file |

---

## Documentation vs Code Conflicts (Summary)

| Legacy doc claim | Code truth | Issue ID |
|------------------|------------|----------|
| ADAPTIVE_REGIME active default | Router + PA lock | KI-001 |
| VOL_REGIME default true | Default false in `live.py` | KI-001 |
| M5+M15+H4 simultaneous live | M5 only with router | KI-008 |
| PositionRecovery default on | Off when router on | KI-004 |
| 5-stage pipeline | 6 stages (SignalFilter exists) | See `PIPELINE.md` |

---

## Unknowns Requiring Runtime Evidence

- Whether meta-labeler actively rejects trades **today** (historical: 1 rejection in 4 records; last 2026-08-12)
- Whether `.env` overrides daemon defaults
- Live profitability or recent trade counts beyond journal aggregates
- Test suite current pass rate (**NOT RUN**)
- Demo vs real account type
- Whether bot is **currently** live trading (**NOT PROVEN** — heartbeat shows MT5 disconnected)

---

## Change Impact

Any fix to issues KI-001 through KI-013 requires updating this file and affected subsystem docs.

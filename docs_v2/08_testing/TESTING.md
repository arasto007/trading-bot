# Testing

## Status

- **Status:** PARTIALLY VERIFIED
- **Last Verified:** 2026-08-22
- **Verification Method:** Test inventory; tests **not executed** in this pass
- **Verified against commit:** `57bf778c23cefffe508bb49079688b177796f67e`

## Scope

Test infrastructure and coverage **as present** in the repository.

## Framework

- **pytest** inferred from `.pytest_cache/` presence and test file patterns
- No `pytest.ini` or `pyproject.toml` found at repository root in this audit
- Standard invocation likely: `pytest tests/` — **UNKNOWN** CI configuration

## Test Inventory

| Metric | Value | Evidence |
|--------|-------|----------|
| Test files | **231** | `tests/test_*.py` count |
| Naming | `test_phase*.py`, `test_ml_*.py`, component tests | Directory listing |

## Categories (by filename patterns)

| Category | Examples | Live path relevance |
|----------|----------|---------------------|
| Phase certification | `test_phase18b_go_live.py`, `test_phase20c_broker_validation.py` | Partial — broker/go-live |
| ML integration | `test_ml_phase10_1_kernel_bridge.py`, `test_phase15d_shadow.py` | ML paths |
| Live loop health | `test_phase20y1_live_loop_health.py` | **Direct** — heartbeat/stall |
| VOL registry | `test_vol_regime_registry.py` | VOL engine (not default live) |
| Legacy loader | `test_legacy_loader.py` | Config merge |
| Dashboard | `test_dashboard_server.py`, HTA tests | Ops UI |
| PA / phase1a | `test_phase1a_pa.py` | Strategy |
| Backtest / ML research | Many `test_ml_research_*`, `test_phase14_*` | Research parity |

## Integration / Runtime Tests

| Test area | File | What it suggests |
|-----------|------|------------------|
| Broker validation | `test_phase20c_broker_validation.py` | MT5 integration checks |
| Go live checklist | `test_phase18b_go_live.py` | Startup readiness patterns |
| Live loop health | `test_phase20y1_live_loop_health.py` | Heartbeat freshness logic |
| Smoke (script) | `scripts/smoke_test_execution.py` | Manual execution check — not pytest |

## Execution Tests

- Broker validation tests exist
- Many research tests **forbid** `order_send` strings in research modules (not production adapter tests)
- **Gap:** No single pytest found that asserts full `START_BOT.bat → order_send` E2E against live MT5 in CI

## Risk Tests

- Fault injection references in `ml/research/phase6a/fault_injection_live.py`
- Dataset hardening: `test_dataset_hardening.py` imports RiskGate
- Dedicated RiskGate unit test file: **not identified** as standalone; logic tested via phase tests

## ML Tests

Heavy coverage (~100+ ML-related test files). Validates research pipelines, shadow modes, kernel bridge — **does not prove ML is active live** when disabled.

## Tests Not Run

This documentation pass did **not** execute pytest to avoid modifying `.pytest_cache` and without user request.

| Item | Status |
|------|--------|
| Pass rate | **UNKNOWN** |
| Flaky tests | **UNKNOWN** |
| Stale tests | **UNKNOWN** — some may reference removed phases |

## Missing Critical Coverage (Identified Gaps)

| Gap | Severity |
|-----|----------|
| Default router+PA lock integration test | Medium |
| Meta-labeler gating with/without `.pkl` | Medium |
| Full watchdog restart E2E | Medium |
| Operator `.env` matrix | Low |
| UnconfiguredEngineRegistry misconfig alarm | Low |

## Active Evidence Value

Tests provide **supporting** evidence for subsystems but do not override source-code reachability analysis per SOURCE_OF_TRUTH hierarchy.

## Change Impact

Any change to tested modules; adding `pytest.ini` or CI workflow

## Verification

```text
(Get-ChildItem tests -Filter test_*.py -Recurse).Count
# Optional future: pytest tests/ -q
```

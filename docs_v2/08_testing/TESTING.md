# Testing

**Status:** VERIFIED (documentation-test commands); full-tree pytest of every file **UNKNOWN** unless a named suite is run  
**Last verified:** 2026-09-01  
**Canonical-Entry:** false  
**Epistemic-Role:** OWNER of TESTING (how to verify docs/memory offline).  
**Operator-effective state:** UNKNOWN  
**Artifact class:** CURRENT DOCUMENTATION for documentation/memory tests. Historical inventory below is HISTORICAL.

Do **not** start MT5, the bot, or the daemon from this file. Do **not** read `.env`.

---

## Canonical offline commands (no MT5)

Documentation / memory (preferred single entry):

```text
python -m tradingbot.ml.research.documentation_verification.run
pytest tests/test_documentation_verification.py tests/test_documentation_freshness.py tests/test_documentation_consistency.py tests/test_documentation_memory_hardening_v2.py tests/test_project_decision_baseline.py tests/test_chatgpt_memory_integrity.py -q
```

Related (still offline):

```text
pytest tests/test_documentation_system_audit.py tests/test_full_repository_audit.py tests/test_pa_live_audit.py tests/test_v41_decision_audit.py tests/test_v41_calibration_evidence.py tests/test_v41_isolated_trend_replay.py tests/test_v41_cost_robustness.py tests/test_v41_cost_followup.py tests/test_phase22h.py -q
```

Freshness snapshot: tests **must not** rewrite `data/ml/reports/documentation_freshness/snapshot.json`. Explicit only:

```text
python -m tradingbot.ml.research.documentation_freshness.run --regenerate-baseline
```

---

## Categories

| Category | Examples | May run without MT5? | Must not start bot? |
|----------|----------|----------------------|---------------------|
| Documentation consistency | `test_documentation_consistency.py` | Yes | Yes |
| Freshness | `test_documentation_freshness.py` | Yes | Yes |
| Memory / ChatGPT load | `test_chatgpt_memory_integrity.py`, `test_documentation_memory_hardening_v2.py`, `test_project_decision_baseline.py` | Yes | Yes |
| Audit | `test_full_repository_audit.py`, `test_documentation_system_audit.py` | Yes | Yes |
| Research-only (v41/PA) | `test_v41_*.py`, `test_pa_live_audit.py` | Yes (isolated) | Yes |
| Production safety invariants | lock/ML-off/v41-1.0 asserts in consistency tests | Yes | Yes |
| Broker / go-live | `test_phase20c_broker_validation.py` | **UNKNOWN** / may need MT5 | Must not start from a docs prompt |
| Full `tests/` tree | 200+ files | UNKNOWN without listing | Must not start MT5 |

External evidence tests (broker tape, `.env`, live orders) are **out of scope** for documentation phases.

---

## Snapshot rules

- Canonical snapshot = `data/ml/reports/documentation_freshness/snapshot.json`
- `baseline_kind` must be `canonical` or `explicit_regeneration`, never `test_fixture`
- Missing snapshot → freshness **UNKNOWN**, not PASS
- Pytest uses isolated fixture snapshots

---

## HISTORICAL (2026-08-22 inventory)

The following counts and “tests not executed” statements are a **HISTORICAL** snapshot. They do not describe the current documentation-test runs.

- Test files ~231 (`tests/test_*.py`) — VERIFIED FROM FILES at that date
- That pass did not execute pytest
- No claim that the entire tree is green today

**Do not treat the historical inventory as current pass/fail.**

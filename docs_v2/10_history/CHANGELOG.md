# Changelog

## Status

- **Status:** DRAFT — initial docs_v2 population entry
- **Last Updated:** 2026-08-22

## Scope

Record of **documentation** changes in `docs_v2/`. This file does not claim trading logic changes unless separately verified in Git.

---

## 2026-08-22 — Documentation v2 baseline population

### Documentation

- Populated empty `docs_v2/` subsystem documents from repository source-code audit:
  - `01_truth/CURRENT_STATE.md`
  - `01_truth/KNOWN_ISSUES.md`
  - `02_architecture/ARCHITECTURE.md`, `MODULE_MAP.md`, `PIPELINE.md`
  - `03_runtime/CONFIGURATION.md`, `LIVE_LOOP.md`, `STARTUP.md`
  - `04_strategy/STRATEGY.md`, `SIGNAL_FLOW.md`
  - `05_risk/RISK.md`, `POSITION_LIFECYCLE.md`
  - `06_data/DATA_PIPELINE.md`
  - `07_ml/ML_ARCHITECTURE.md`, `ML_STATUS.md`
  - `08_testing/TESTING.md`
  - `09_operations/OBSERVABILITY.md`, `RUNBOOK.md`
- Verification method: static source analysis at commit `57bf778c23cefffe508bb49079688b177796f67e`
- Tests not executed during this documentation pass

### Findings recorded (documentation only)

- Default live path: MultiEngineRouter + PA production lock (not ADAPTIVE_REGIME as claimed in legacy `docs/`)
- Six pipeline stages including SignalFilterStage
- ML kernel disabled; ML shadow enabled by daemon default
- Legacy documentation conflicts catalogued in `KNOWN_ISSUES.md`

### Code changes

**None** — documentation-only pass per project rules.

### SOURCE_OF_TRUTH.md

Not modified. Recommended follow-up: populate Section 6 repository identity and Section 43 baseline status fields from `CURRENT_STATE.md` (see final audit report).

---

## Template for future entries

```markdown
## YYYY-MM-DD — Short title

### Subsystem (Runtime / Strategy / Risk / …)

Description of verified behavior change.

Affected source:
- `path/to/file.py`

Affected documentation:
- `docs_v2/...`

Verification status: VERIFIED | PARTIAL | UNKNOWN
```

---

## Historical behavior

Prior project history before commit `57bf778` is **UNKNOWN** (single Git commit in repository).

Legacy documents under `docs/` may describe earlier intended behavior — treat as **HISTORICAL** unless re-verified.

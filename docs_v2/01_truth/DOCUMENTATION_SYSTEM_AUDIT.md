# Documentation System Audit (Phase 1.5.62)

**Status:** VERIFIED (inventory)  
**Last verified:** 2026-09-01  
**Live impact:** none  
**Canonical-Entry:** false  

This audit classifies existing documentation. It does **not** delete files. Machine-readable twin: `data/ml/reports/documentation_system_audit/`.

**Single canonical entry (after 1.5.63):** `docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md`

---

## 1. Documentation inventory

Approximate markdown locations (see `files.json` for the full list):

| Area | Role |
|------|------|
| `docs_v2/` | Intended current docs (mixed currency; 2026-08-22 dates vs later audits) |
| `docs/` | Legacy FA / robot_behavior_audit / phase reports |
| Root `README.md`, `AUTONOMOUS_MODE.md`, `DEMO_TEST_OVERRIDES.md`, `دستورات_اجرایی.md` | Operator / mixed |
| `tradingbot/ml/research/phase*/**/*.md` | Research-inline architecture dumps |
| `memory/classification_summary.md` | Generated index |
| `docs_v2/01_truth/FULL_REPOSITORY_SOURCE_OF_TRUTH.md` | Phase 1.5.61 detailed audit snapshot |

### 1.1 Architecture

| Document | Verdict |
|----------|---------|
| `docs_v2/02_architecture/ARCHITECTURE.md` | MIXED / superseded by `SYSTEM_ARCHITECTURE.md` |
| `docs_v2/02_architecture/MODULE_MAP.md` | SUPPORTING |
| `docs_v2/02_architecture/PIPELINE.md` | SUPPORTING |
| `docs/ARCHITECTURE_FA.md` | HISTORICAL |
| `docs/PROCESSING_MAP.md` | HISTORICAL |
| `docs/WHITEBOARD_FA.md` | HISTORICAL |
| `tradingbot/ml/research/phase22a/*.md` | RESEARCH_INLINE |

### 1.2 Current runtime truth

| Document | Verdict |
|----------|---------|
| `docs_v2/01_truth/CURRENT_STATE.md` | MIXED (2026-08-22); superseded by `CURRENT_RUNTIME_STATE.md` |
| `docs_v2/03_runtime/STARTUP.md` | MIXED / keep as supporting after pointer |
| `docs_v2/03_runtime/LIVE_LOOP.md` | MIXED |
| `docs_v2/03_runtime/CONFIGURATION.md` | MIXED; superseded by `CONFIGURATION_TRUTH.md` |
| `FULL_REPOSITORY_SOURCE_OF_TRUTH.md` | SUPPORTING audit snapshot (1.5.61) |

### 1.3 Historical decisions

`docs/robot_behavior_audit/*`, `docs/PHASE2_*`, `docs/phase*`, `docs_v2/10_history/CHANGELOG.md`.

### 1.4 Research

`docs_v2/07_ml/V41_*.md`, `docs_v2/04_strategy/PA_LIVE_EDGE_AUDIT.md`, `tradingbot/ml/research/**`. **Do not rewrite.**

### 1.5 Stale / contradict code

| Document | Problem | Class |
|----------|---------|-------|
| `docs/robot_behavior_audit/strategy_inventory.md` | Adaptive as default live engine | C vs code |
| `docs/robot_behavior_audit/configuration_truth.md` | Same Adaptive-default claim | C |
| `docs/CAPABILITIES.md` | MIXED capability claims | C |
| `docs_v2/01_truth/SOURCE_OF_TRUTH.md` | Dated 2026-08-22; overlapping SOT | C (age) |
| `m5_london_sweep.py` module docstring | Describes London 07–10; live preset NY 15–16 | C (docstring vs preset) |

### 1.6 Heavy overlap

- Three “source of truth” files existed/exist: `SOURCE_OF_TRUTH.md`, `FULL_REPOSITORY_SOURCE_OF_TRUTH.md`, plus this system’s `PROJECT_SOURCE_OF_TRUTH.md`.
- Runtime: `STARTUP.md` + `LIVE_LOOP.md` + `CURRENT_STATE.md` + 1.5.61 audit.
- ML: `ML_STATUS.md` + `ML_ARCHITECTURE.md` + six V41 evidence docs.
- Config: `CONFIGURATION.md` + `docs/runtime_config_diff.md` + robot_behavior `configuration_truth.md`.

**Rule after this batch:** one entry file. Others keep content but are labeled supporting / superseded / historical.

---

## 2. Proposed hierarchy

```text
CODE (executable)
  → runtime evidence (when collected; none in this batch)
  → tests
  → CANONICAL docs_v2 (this memory layer)
  → SUPPORTING (detailed audits, research evidence, ops)
  → SUPERSEDED_KEEP (old docs_v2 with pointer banners)
  → HISTORICAL (docs/, phase markdown)
```

ChatGPT read order:

1. `PROJECT_SOURCE_OF_TRUTH.md` (always first)
2. Subsystem canonical file for the decision at hand
3. Supporting evidence only if needed
4. Cursor re-audit only for P0/P1 unknowns or new code

---

## 3. Canonical documents

See `CANONICAL` in `tradingbot/ml/research/documentation_system_audit/run.py`.

## 4. Supporting documents

1.5.61 full-repo audit, V41/PA research evidence, `ML_STATUS.md`, runbook, testing, pipeline/module maps.

## 5. Historical documents

All of `docs/` except treat as non-authoritative. Keep on disk.

## 6. Deprecated (do not delete)

Mark with a pointer banner: `SOURCE_OF_TRUTH.md`, `CURRENT_STATE.md`, `KNOWN_ISSUES.md` as **entry** docs; `ARCHITECTURE.md`, `STRATEGY.md`, `RISK.md` as **subsystem** docs. Status: SUPERSEDED_KEEP.

## 7. Contradiction classes

A consistent · B partial · C docs/config mismatch · D runtime contradiction · E unknown.

See `KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md` (1.5.69).

## 8. Missing documentation (before this batch)

| Gap | Filled by |
|-----|-----------|
| Single ChatGPT entry | `PROJECT_SOURCE_OF_TRUTH.md` |
| Code-cited live PA spec | `PRICE_ACTION_LIVE_SPEC.md` |
| RiskGate hop list | `RISKGATE_SPEC.md` |
| Component classification | `PRODUCTION_RESEARCH_BOUNDARY.md` |
| Config precedence map | `CONFIGURATION_TRUTH.md` |
| Contradiction registry | `KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md` |
| Doc update protocol | `DOCUMENTATION_UPDATE_PROTOCOL.md` |
| Model registry | `MODEL_REGISTRY.md` |
| Data contracts | `DATA_CONTRACTS.md` |

## 9. Duplication problems

Multiple SOT files; Adaptive-default in `docs/` vs PA lock in code; CLI M15 vs live M5; `london_sweep` name vs NY window. **Do not silently merge facts.** Point to the canonical interpretation and list the contradiction.

## 10. Update ownership

| Kind | Owner |
|------|--------|
| Canonical docs | Cursor after code-cited verification |
| Research evidence | Frozen unless a new research phase writes a **new** file |
| Historical `docs/` | Leave in place; optional pointer only |
| `docs_v2/_generated/` | Generator only (if used) |
| Production Python | Not a documentation file — do not change to make docs easier |

## 11. Evidence rules

- Cite `path` + `symbol` (class/function/constant).
- Comments/docstrings < executable code.
- `.env` values = UNKNOWN (do not read secrets).
- Daemon-if-unset ≠ process env of an audit run.

## 12. Maintenance rules

See `docs_v2/99_change_control/DOCUMENTATION_UPDATE_PROTOCOL.md`.

**No important code change without documentation impact analysis.**

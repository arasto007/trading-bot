# Documentation Memory Baseline (Phase 1.5.71)

**Status:** VERIFIED (inspection of the 1.5.62–70 layer; this file does not “fix” gaps)  
**Last verified:** 2026-09-01  
**Kind labels:** FACT · DERIVED FACT · ASSUMPTION · UNKNOWN · CONTRADICTION · HISTORICAL · RESEARCH-ONLY  

Machine-readable: `data/ml/reports/documentation_memory_hardening/baseline.json`.  
Later files in **1.5.72–1.5.78** address listed gaps; they do not rewrite this baseline’s findings.

---

## A. Is PROJECT_SOURCE_OF_TRUTH.md sufficient as canonical entry?

**DERIVED FACT:** **Yes as navigation.** **No as a one-screen session load.**

It states identity, live path, shadow vs research, PA, RiskGate 999, execution modes, data identity UNKNOWN, ML off / v41 C 1.0, config table, P0 unknowns, named contradictions, and links to deeper specs. Evidence: file itself, `Canonical-Entry: true` unique among `docs_v2` at inspection time.

It does **not** contain: NEVER-assume list, change-class decision tree, ownership of duplicated facts, git state, or a machine freshness rule.

## B. Can a fresh reasoning model understand the robot from docs alone?

**DERIVED FACT:** **Mostly yes, with caveats.**

If it reads the **canonical** tree (entry → runtime → PA spec → RiskGate → ML_SYSTEM_STATE → contradictions), it can answer default live owner, symbol, TF, preset, ML off, v41 inactive/C/1.0, RiskGate role, production/research split, and listed unknowns.

**Caveats (not collapsed):**

| Kind | Item |
|------|------|
| HISTORICAL | `SOURCE_OF_TRUTH.md` / `CURRENT_STATE.md` dated 2026-08-22; `docs/` Adaptive-as-default |
| UNKNOWN | operator `.env`; live broker costs; whether daemon is running |
| ASSUMPTION (forbidden) | treating `london_sweep` as London hours; treating `data/ml/live/` as current owner |
| CONTRADICTION | CX registry; duplication of live facts across several canonical files |

**Must not change** is stated (RiskGate, lock, ML, bundle) in protocol + ML/risk docs, but not as a single safety card until bootstrap (1.5.73).

## C. In code/audits but thin/absent in the *entry*

- KillSwitch `sys.exit(2)` — `live_runner.py` / `STARTUP_AND_SHUTDOWN.md`
- `_ReliabilityKernel` stale freeze — `LIVE_RUNTIME_PATH.md`
- WPSQF default OFF — `CURRENT_RUNTIME_STATE.md`
- PositionProtector default off — same
- Testing map — `docs_v2/08_testing/TESTING.md` not in ChatGPT required read order
- Git dirty tree — not a canonical domain
- Ownership / freshness / ChatGPT workflow — missing before 1.5.72–77
- PA uncosted class **B** — in `PA_LIVE_EDGE_AUDIT.md` / PRICE_ACTION_LIVE_SPEC header, easy to miss

## D. Duplication (divergence risk)

Live path, PA NY window, v41 1.0, PA lock, `USE_ML_KERNEL` appear in multiple canonical files. Owner-of-truth was **not** machine-enforced before 1.5.74.

## E. Weak evidence

Entry cites many `path::symbol` values. File-only citations remain for BAT/PS1 hops (acceptable for non-Python). “Fourteen other strategies” is a **DERIVED FACT** from `ACTIVE_STRATEGIES` without listing them in the entry (list lives in `ACTIVE_STRATEGIES.md`).

## F. Stale / misleading if banners ignored

| File | Kind |
|------|------|
| `docs_v2/01_truth/SOURCE_OF_TRUTH.md` | HISTORICAL / SUPERSEDED_KEEP |
| `docs_v2/01_truth/CURRENT_STATE.md` | HISTORICAL / MIXED date |
| `docs/robot_behavior_audit/strategy_inventory.md` | HISTORICAL CONTRADICTION vs PA lock |
| `docs/robot_behavior_audit/configuration_truth.md` | HISTORICAL |
| `docs_v2/06_data/DATA_PIPELINE.md` body | Last verified 2026-08-22; pointer added 2026-09-01 |

## Claim-kind discipline

This baseline does **not** treat daemon-if-unset as operator-effective (that would be ASSUMPTION). Operator override = **UNKNOWN**. Research class B/C = **RESEARCH-ONLY**, not live FACT.

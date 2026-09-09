# TradingBot Documentation v2

**Canonical ChatGPT entry (required first read):**

`docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md`

Do not start with `SOURCE_OF_TRUTH.md` or `CURRENT_STATE.md` — those are superseded-keep snapshots.

---

## Read Order

1. `01_truth/PROJECT_SOURCE_OF_TRUTH.md`
2. Subsystem canonical file for the decision (see that entry)
3. Supporting evidence (`FULL_REPOSITORY_SOURCE_OF_TRUTH.md`, `V41_*`, `PA_LIVE_EDGE_AUDIT.md`) only if needed
4. Historical `docs/` never overrides code

Maintenance: `99_change_control/DOCUMENTATION_UPDATE_PROTOCOL.md`

---

## Documentation Structure

| Folder | Purpose |
|--------|---------|
| 01_truth | Canonical memory: entry, runtime, config, contradictions, boundary |
| 02_research | Research-only performance / validation evidence (not live authorization) |
| 02_architecture | System / data flow / component boundaries |
| 03_runtime | Live path, startup/shutdown, execution |
| 04_strategy | Active strategies + PA live spec |
| 05_risk | RiskGate + execution boundary |
| 06_data | Pipeline + contracts |
| 07_ml | ML state, registry, calibration + frozen research evidence |
| 08_testing | Tests |
| 09_operations | Runbook / observability |
| 10_history | Changelog |
| 99_change_control | Doc update protocol |
| _generated | Auto-generated. Never edit manually. |
| _system | Engine rules |

---

## Documentation States

- VERIFIED
- GENERATED
- HISTORICAL
- DRAFT
- SUPERSEDED_KEEP (pointer + old body)

---

## Update Policy

`_system/DOCUMENTATION_RULES.md` plus `99_change_control/DOCUMENTATION_UPDATE_PROTOCOL.md`.

Code changes must trigger documentation impact analysis.

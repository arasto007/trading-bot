# Research Ledger

Event-level frozen tape: `logs/phase40_raw_setups.jsonl` + `data/XAUUSD_i_5m_phase38.parquet`.
Baseline: Phase 40–67 unchanged. Official expectancy includes the +31.84R event.
OOS is reported in diagnostics and is **not** used to select hypotheses or the Phase 73 target.

| ID | Date | Phase | Data range | N | Baseline | Result | OOS touched | Decision from OOS | Next |
|---|---|---|---|---|---|---|---|---|---|
| H68-01 | 2026-09-08 | 68 | frozen Phase38/40 | 419 | event tape 419 resolved | majority LOSS_SL first favorable | reported | NO | 69 |
| H68-02 | 2026-09-08 | 68 | frozen Phase38/40 | 419 | event tape 419 resolved | C_PROFIT_PROTECTION | reported | NO | 69 |
| H69-01 | 2026-09-08 | 69 | frozen Phase38/40 | 419 | event tape 419 resolved | same SL/TP path | NO | NO | 70 |
| H69-02 | 2026-09-08 | 69 | frozen Phase38/40 | 419 | event tape 419 resolved | B_RARE_LEGITIMATE_STRUCTURAL | NO | NO | 70 |
| H70-A | 2026-09-08 | 70 | frozen Phase38/40 | 419 | event tape 419 resolved | LOSS_AFTER_0.5R descriptive | reported | NO | 71 |
| H70-B | 2026-09-08 | 70 | frozen Phase38/40 | 419 | event tape 419 resolved | breakeven-reach descriptive; SL not moved | reported | NO | 71 |
| H70-C | 2026-09-08 | 70 | frozen Phase38/40 | 419 | event tape 419 resolved | capture ratio descriptive | reported | NO | 71 |
| H70-D | 2026-09-08 | 70 | frozen Phase38/40 | 419 | event tape 419 resolved | time-to-reversal descriptive | reported | NO | 71 |
| H70-E | 2026-09-08 | 70 | frozen Phase38/40 | 419 | event tape 419 resolved | hold-window descriptive | reported | NO | 71 |
| H70-F | 2026-09-08 | 70 | frozen Phase38/40 | 419 | event tape 419 resolved | regime exit descriptive | reported | NO | 71 |
| H70-G | 2026-09-08 | 70 | frozen Phase38/40 | 419 | event tape 419 resolved | session exit descriptive | reported | NO | 71 |
| H70-H | 2026-09-08 | 70 | frozen Phase38/40 | 419 | event tape 419 resolved | side exit descriptive | reported | NO | 71 |
| H70-I | 2026-09-08 | 70 | frozen Phase38/40 | 419 | event tape 419 resolved | volatility labels descriptive | reported | NO | 71 |
| H71-01 | 2026-09-08 | 71 | frozen Phase38/40 | 419 | event tape 419 resolved | B_RARE_LEGITIMATE_STRUCTURAL | reported | NO | 72 |
| H72-01 | 2026-09-08 | 72 | frozen Phase38/40 | 419 | event tape 419 resolved | PROFIT_GIVEBACK | reported | NO | 73 |
| H73-01 | 2026-09-08 | 73 | frozen Phase38/40 | 419 | event tape 419 resolved | PROFIT_PROTECTION_RESEARCH | reported | NO | spec only; not implemented |

**HYPOTHESES_TESTED:** 16
**DIAGNOSTICS_RUN:** 23
**NEXT_RESEARCH_TARGET:** `PROFIT_PROTECTION_RESEARCH` (not implemented).

## Phases 74–81

| ID | Date | Phase | Data range | N | Baseline | Result | OOS touched | Decision from OOS | Next |
|---|---|---|---|---|---|---|---|---|---|
| H74-01 | 2026-09-08 | 74 | frozen Phase38/40 | 419 | event tape 419 resolved | 0.9161073825503355 | reported | NO | giveback path |
| H75-A | 2026-09-08 | 75 | frozen Phase38/40 | 419 | event tape 419 resolved | NEUTRAL | reported | NO | predeclared CF |
| H76-01 | 2026-09-08 | 76 | frozen Phase38/40 | 419 | event tape 419 resolved | UNSUPPORTED | reported | NO | SL vs protection |
| H77-01 | 2026-09-08 | 77 | frozen Phase38/40 | 419 | event tape 419 resolved | LEGITIMATE_TAIL_OF_HYBRID_GEOMETRY_UNIQUE_FILL | reported | NO | RR geometry |
| H78-01 | 2026-09-08 | 78 | frozen Phase38/40 | 419 | event tape 419 resolved | PARTIALLY_SUPPORTED | reported | NO | time buckets |
| H79-01 | 2026-09-08 | 79 | frozen Phase38/40 | 419 | event tape 419 resolved | PARTIALLY_SUPPORTED | reported | NO | side/regime |
| H80-01 | 2026-09-08 | 80 | frozen Phase38/40 | 419 | event tape 419 resolved | LEGITIMATE_TAIL_OF_HYBRID_GEOMETRY_UNIQUE_FILL | reported | NO | extreme audit |
| H81-01 | 2026-09-08 | 81 | frozen Phase38/40 | 419 | event tape 419 resolved | PROFIT_PROTECTION_DESIGN | reported | NO | gate; not implemented |

**NEXT_RESEARCH_TARGET:** `PROFIT_PROTECTION_DESIGN` (not implemented).

## Phases 82–89

| ID | Date | Phase | Data range | N | Baseline | Result | OOS touched | Decision from OOS | Next |
|---|---|---|---|---|---|---|---|---|---|
| H82-01 | 2026-09-08 | 82 | frozen Phase38/40 | 419 | event tape 419 resolved | TAXONOMY_READY | reported | NO | taxonomy; no search |
| H83-01 | 2026-09-08 | 83 | frozen Phase38/40 | 419 | event tape 419 resolved | NONE | reported | NO | predeclared CF |
| H84-01 | 2026-09-08 | 84 | frozen Phase38/40 | 419 | event tape 419 resolved | DESTROYED | reported | NO | tail diagnostic |
| H85-01 | 2026-09-08 | 85 | frozen Phase38/40 | 419 | event tape 419 resolved | rescue_vs_destruction | reported | NO | not expectancy-only |
| H86-01 | 2026-09-08 | 86 | frozen Phase38/40 | 419 | event tape 419 resolved | NEGATIVE | reported | NO | TRAIN/VAL/OOS report |
| H87-01 | 2026-09-08 | 87 | frozen Phase38/40 | 419 | event tape 419 resolved | interaction_diagnosis | reported | NO | no side parameters |
| H88-01 | 2026-09-08 | 88 | frozen Phase38/40 | 419 | event tape 419 resolved | INSUFFICIENT_EVIDENCE | reported | NO | spec; not implemented |
| H89-01 | 2026-09-08 | 89 | frozen Phase38/40 | 419 | event tape 419 resolved | MORE_PROFIT_PROTECTION_FORENSICS | reported | NO | gate; not implemented |

**NEXT_RESEARCH_TARGET:** `MORE_PROFIT_PROTECTION_FORENSICS` (not implemented).

## Phases 90–97

| ID | Date | Phase | Data range | N | Baseline | Result | OOS touched | Decision from OOS | Next |
|---|---|---|---|---|---|---|---|---|---|
| H90-01 | 2026-09-08 | 90 | frozen Phase38/40 | 419 | event tape 419 resolved | True | reported | NO | path classes A-G |
| H91-01 | 2026-09-08 | 91 | frozen Phase38/40 | 419 | event tape 419 resolved | timing_forensics | reported | NO | no timeout chosen |
| H92-01 | 2026-09-08 | 92 | frozen Phase38/40 | 419 | event tape 419 resolved | mfe_conditional | reported | NO | no threshold search |
| H93-01 | 2026-09-08 | 93 | frozen Phase38/40 | 419 | event tape 419 resolved | NOT_ESTABLISHED | reported | NO | outlier kept |
| H94-01 | 2026-09-08 | 94 | frozen Phase38/40 | 419 | event tape 419 resolved | signals_not_independent | reported | NO | event unit |
| H95-01 | 2026-09-08 | 95 | frozen Phase38/40 | 419 | event tape 419 resolved | [] | reported | NO | four families |
| H96-01 | 2026-09-08 | 96 | frozen Phase38/40 | 419 | event tape 419 resolved | [] | reported | NO | qualitative gate |
| H97-01 | 2026-09-08 | 97 | frozen Phase38/40 | 419 | event tape 419 resolved | MORE_PROFIT_PROTECTION_FORENSICS | reported | NO | gate; not implemented |

**NEXT_RESEARCH_TARGET:** `MORE_PROFIT_PROTECTION_FORENSICS` (not implemented).

## Phases 98–105

| ID | Date | Phase | Data range | N | Baseline | Result | OOS touched | Decision from OOS | Next |
|---|---|---|---|---|---|---|---|---|---|
| H98-01 | 2026-09-08 | 98 | frozen Phase38/40 | 419 | event tape 419 resolved | see separators | reported | NO | causal snapshots |
| H99-01 | 2026-09-08 | 99 | frozen Phase38/40 | 419 | event tape 419 resolved | persistence | reported | NO | not a rule |
| H100-01 | 2026-09-08 | 100 | frozen Phase38/40 | 419 | event tape 419 resolved | retrace_expansion | reported | NO | outlier kept |
| H101-01 | 2026-09-08 | 101 | frozen Phase38/40 | 419 | event tape 419 resolved | EXIT_REMAINS_DOMINANT | reported | NO | signal unchanged |
| H102-01 | 2026-09-08 | 102 | frozen Phase38/40 | 419 | event tape 419 resolved | cluster_timing | reported | NO | event unit |
| H103-01 | 2026-09-08 | 103 | frozen Phase38/40 | 419 | event tape 419 resolved | [] | reported | NO | predeclared structure |
| H104-01 | 2026-09-08 | 104 | frozen Phase38/40 | 419 | event tape 419 resolved | NO_FAMILIES | reported | NO | counterfactual only |
| H105-01 | 2026-09-08 | 105 | frozen Phase38/40 | 419 | event tape 419 resolved | NON_OHLC_DISCRIMINATOR_RESEARCH | reported | NO | gate; not implemented |

**DISCRIMINATOR_STATUS:** `UNSUPPORTED`
**NEXT_RESEARCH_TARGET:** `NON_OHLC_DISCRIMINATOR_RESEARCH` (not implemented).
**Q12:** `NON_OHLC_DISCRIMINATOR_RESEARCH`

## Phases 106–113

| ID | Date | Phase | Data range | N | Baseline | Result | OOS touched | Decision from OOS | Next |
|---|---|---|---|---|---|---|---|---|---|
| H106-01 | 2026-09-09 | 106 | frozen Phase38/40 | 419 | event tape 419 resolved | PARTIAL_LOCAL_FILES_INCOMPLETE_EVENT_COVERAGE | reported | NO | local inventory |
| H107-01 | 2026-09-09 | 107 | frozen Phase38/40 | 419 | event tape 419 resolved | DATA_MISSING | reported | NO | no fabricated ticks |
| H108-01 | 2026-09-09 | 108 | frozen Phase38/40 | 419 | event tape 419 resolved | DATA_MISSING | reported | NO | no broker inference |
| H109-01 | 2026-09-09 | 109 | frozen Phase38/40 | 419 | event tape 419 resolved | UNSUPPORTED | reported | NO | M15 as-of; strategy unchanged |
| H110-01 | 2026-09-09 | 110 | frozen Phase38/40 | 419 | event tape 419 resolved | DATA_MISSING | reported | NO | no API |
| H111-01 | 2026-09-09 | 111 | frozen Phase38/40 | 419 | event tape 419 resolved | DATA_MISSING | reported | NO | no brute force |
| H112-01 | 2026-09-09 | 112 | frozen Phase38/40 | 419 | event tape 419 resolved | UNSUPPORTED | reported | NO | candidate gate |
| H113-01 | 2026-09-09 | 113 | frozen Phase38/40 | 419 | event tape 419 resolved | FULL_HORIZON_NON_OHLC_DATA_ACQUISITION | reported | NO | gate; not implemented |

**DISCRIMINATOR_STATUS:** `UNSUPPORTED`
**NEXT_RESEARCH_TARGET:** `FULL_HORIZON_NON_OHLC_DATA_ACQUISITION` (not implemented).
**Q19:** `FULL_HORIZON_NON_OHLC_DATA_ACQUISITION`

## Phase 114

| ID | Date | Phase | Data range | N | Baseline | Result | OOS touched | Decision from OOS | Next |
|---|---|---|---|---|---|---|---|---|---|
| H114-01 | 2026-09-09 | 114 | frozen Phase38/40 | 419 | event tape 419 resolved | True | reported | NO | contract; not acquired |

**ACQUISITION_READY:** `True`
**NEXT_RESEARCH_TARGET:** `OPERATOR_AUTHORIZED_XAUUSD_I_INGEST` (not started).

## Phase 115

| ID | Date | Phase | Data range | N | Baseline | Result | OOS touched | Decision from OOS | Next |
|---|---|---|---|---|---|---|---|---|---|
| H115-01 | 2026-09-09 | 115 | frozen Phase38/40 | 419 | event tape 419 resolved | False | reported | NO | ingest; Phase 116 not started |

**PHASE115_STATUS:** `PASS`
**ACQUISITION_STATUS:** `LOCAL_SIDECARS_ONLY`
**TICK_COMPLETE_LIFECYCLE_EVENTS:** `3`
**PHASE116_READY:** `False`

## Phase 116

| ID | Date | Phase | Data range | N | Baseline | Result | OOS touched | Decision from OOS | Next |
|---|---|---|---|---|---|---|---|---|---|
| H116-01 | 2026-09-09 | 116 | frozen Phase38/40 | 419 | event tape 419 resolved | READY_WITH_OPERATOR_ACTION | reported | NO | source plan; not acquired |

**ACQUISITION_PATH_STATUS:** `READY_WITH_OPERATOR_ACTION`
**PHASE117_RECOMMENDATION:** `OPERATOR_SOURCE_RESOLUTION_RESEARCH` (not started).

## Phase 117

| ID | Date | Phase | Data range | N | Baseline | Result | OOS touched | Decision from OOS | Next |
|---|---|---|---|---|---|---|---|---|---|
| H117-01 | 2026-09-09 | 117 | frozen Phase38/40 | 419 | event tape 419 resolved | OPERATOR_ACTION_REQUIRED | reported | NO | operator export; Phase 118 not started |

**PHASE117_STATUS:** `PASS`
**ACQUISITION_STATUS:** `OPERATOR_ACTION_REQUIRED`
**DATA_ACQUIRED:** `False`


## Phase 118

| ID | Date | Phase | Data range | N | Baseline | Result | OOS touched | Decision from OOS | Next |
|---|---|---|---|---|---|---|---|---|---|
| H118-01 | 2026-09-09 | 118 | operator export 2026-07-23..2026-09-07 | 419 | frozen Phase38/40 | PARTIAL | reported | NO | partial ingest; full horizon still missing |

**HISTORY_RANGE_STATUS:** `PARTIAL`
**TICK_EVENT_COVERAGE:** `12`
**OUTLIER_31_84R_COVERAGE:** `False`
**AMBIGUOUS_394_REMAINING:** `382`


## Phase 119

| ID | Date | Phase | Data range | N | Baseline | Result | OOS touched | Decision from OOS | Next |
|---|---|---|---|---|---|---|---|---|---|
| H119-01 | 2026-09-09 | 119 | missing 2023-02-26T15:40:00Z..2026-07-23T01:00:59Z | 419 | Phase116-118 | OPERATOR_CONTACT_REQUIRED | reported | NO | operator support contact |

**FULL_HORIZON_SOURCE_STATUS:** `MISSING`
**CANONICAL_SOURCE_AVAILABLE:** `False`
**NEXT_ACTION:** `REQUEST_LITEFINANCE_XAUUSD_I_HISTORICAL_TICK_DUMP`


## Phase 120

| ID | Date | Phase | Data range | N | Baseline | Result | OOS touched | Decision from OOS | Next |
|---|---|---|---|---|---|---|---|---|---|
| H120-01 | 2026-09-10 | 120 | new export + Phase118 union | 419 | Phase118 | coverage=27 | reported | NO | REQUEST_NEXT_SMALL_BACKWARD_XAUUSD_I_EXPORT |

**NEW_EXPORT:** `2026-05-20T01:01:00.057000Z` -> `2026-07-24T23:58:59.975000Z`
**TICK_EVENT_COVERAGE:** `27`
**OUTLIER_31_84R_TICK_COVERAGE:** `False`
**NEXT_OPERATOR_EXPORT:** `2026-03-20T01:01:00.056000Z` -> `2026-05-20T01:01:00.056000Z`


## Phase 121

| ID | Date | Phase | Data range | N | Baseline | Result | OOS touched | Decision from OOS | Next |
|---|---|---|---|---|---|---|---|---|---|
| H121-01 | 2026-09-10 | 121 | new export + P118/P120 union | 419 | Phase120 | coverage=61 outlier=True | reported | NO | REQUEST_NEXT_SMALL_BACKWARD_XAUUSD_I_EXPORT |

**NEW_EXPORT:** `2026-01-02T01:15:00.282000Z` -> `2026-05-19T23:58:59.782000Z`
**OUTLIER_31_84R_CHRONOLOGY_STATUS:** `ADVERSE_FIRST`
**NEXT_OPERATOR_EXPORT:** `2025-11-02T01:15:00.281000Z` -> `2026-01-02T01:15:00.281000Z`


## Phase 122

| ID | Date | Phase | Data range | N | Baseline | Result | OOS touched | Decision from OOS | Next |
|---|---|---|---|---|---|---|---|---|---|
| H122-01 | 2026-09-10 | 122 | new export + P118/P120/P121 union | 419 | Phase121 | coverage=77 outlier=True | reported | NO | REQUEST_NEXT_SMALL_BACKWARD_XAUUSD_I_EXPORT |

**NEW_EXPORT:** `2025-11-03T01:06:00.068000Z` -> `2026-01-02T23:58:59.935000Z`
**OUTLIER_31_84R_CHRONOLOGY_STATUS:** `ADVERSE_FIRST`
**NEXT_OPERATOR_EXPORT:** `2025-09-03T01:06:00.067000Z` -> `2025-11-03T01:06:00.067000Z`


## Phase 123

| ID | Date | Phase | Data range | N | Baseline | Result | OOS touched | Decision from OOS | Next |
|---|---|---|---|---|---|---|---|---|---|
| H123-01 | 2026-09-10 | 123 | decision review | 419 | Phase40+122 | FREEZE_CURRENT_SYSTEM_AND_BUILD_RESEARCH_V2 | reported | NO | Build Research V2 event-level dataset schema + baseline harness (labels, cluster IDs, leakage-safe splits, cost/tail sensitivity) without changing production strategy/exit/RiskGate. |

**EXIT_ACTION:** `FREEZE_EXIT_AND_REBUILD_ENTRY`
**ML_READINESS:** `NOT_READY`
**NEW_TICK_EXPORT_REQUIRED:** `FALSE`

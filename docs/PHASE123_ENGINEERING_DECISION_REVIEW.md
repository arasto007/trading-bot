# Phase 123 — Engineering Decision Review

Research/engineering decision only. No production changes. No new tick export. Phase124 not auto-started.

**DECISION_ID:** `GE-ED-123-2026-09-10`
**PRIMARY_RECOMMENDATION:** `FREEZE_CURRENT_SYSTEM_AND_BUILD_RESEARCH_V2`
**PRIMARY_ENGINEERING_TARGET:** `EVENT_LEVEL_RESEARCH_FOUNDATION`
**EXIT_ACTION:** `FREEZE_EXIT_AND_REBUILD_ENTRY`
**TAIL_POLICY:** `PRESERVE`
**ML_READINESS:** `NOT_READY`
**CANONICAL_RESEARCH_UNIT:** `LIFECYCLE_EVENT`
**FIRST_NEXT_ENGINEERING_ACTION:** Build Research V2 event-level dataset schema + baseline harness (labels, cluster IDs, leakage-safe splits, cost/tail sensitivity) without changing production strategy/exit/RiskGate.

## Gate

PHASE123_STATUS = PASS
DECISION_STATUS = DECIDED
PRIMARY_ENGINEERING_TARGET = EVENT_LEVEL_RESEARCH_FOUNDATION
ENTRY_STATUS = WEAK_FRAGILE_CLUSTERED
EXIT_STATUS = PROFIT_GIVEBACK_NO_ROBUST_DISCRIMINATOR
EXIT_ACTION = FREEZE_EXIT_AND_REBUILD_ENTRY
TAIL_POLICY = PRESERVE
ML_READINESS = NOT_READY
CANONICAL_RESEARCH_UNIT = LIFECYCLE_EVENT
PRIMARY_RECOMMENDATION = FREEZE_CURRENT_SYSTEM_AND_BUILD_RESEARCH_V2
FIRST_NEXT_ENGINEERING_ACTION = Build Research V2 event-level dataset schema + baseline harness (labels, cluster IDs, leakage-safe splits, cost/tail sensitivity) without changing production strategy/exit/RiskGate.
PRODUCTION_CHANGE_ALLOWED = False
NEW_TICK_EXPORT_REQUIRED = False
PHASE124_READY = True

## Established facts

- Canonical gold = LiteFinance CLASSIC XAUUSD_i (operator-verified).
- Phase40 frozen tape immutable: 2026-09-07T21:09:46Z / 222e75c592115c8e…
- RAW signals n=2847, expectancy_R=0.017224, WR=0.314528, PF=1.025128, DD_R=293.59309.
- Event performance expectancy_R=0.04866, WR=0.288783, PF=1.068418, DD_R=38.249969.
- Signal clustering: clustered_signal_share=0.9859501229364243.
- Primary exit mechanism = PROFIT_GIVEBACK (Phase105).
- EXIT_DESIGN_SPEC = INSUFFICIENT_EVIDENCE; not implemented in production.
- DISCRIMINATOR_STATUS = UNSUPPORTED on frozen M5 OHLC (Phase105).
- Protection research repeatedly destroyed or threatened the +31.84R tail.
- Tick union covers 77/419 events; +31.84R = ADVERSE_FIRST and legitimate.
- Incremental full-horizon tick campaign stopped by operator decision at Phase123.
- EV-EQ-01 remains NOT_PROVEN; Phase40 FINAL_GATE BLOCKED for live.

## Unknown / unsupported

- Universal exit discriminator from OHLC or partial ticks (UNSUPPORTED).
- Full-horizon tick chronology for all 419 events (DATA_LIMITED).
- Whether entry redesign alone restores OOS robustness (UNKNOWN).
- Whether deep ML (TFT/PPO/FinBERT) adds value on this strategy (UNSUPPORTED).
- Broker cost equivalence for executable evaluation (EV-EQ-01 NOT_PROVEN).
- News/session as causal separators (UNSUPPORTED at Phase110-113 gates).

## Decision matrix (verdicts)

- **A_KEEP_STRATEGY_OPS_ONLY**: REJECTED_INSUFFICIENT_FOR_EDGE — Ops polish does not address giveback, clustering, or OOS fragility.
- **B_REDESIGN_EXIT_NOW**: DEFERRED — Giveback is real, but Phases74-105 failed to find a robust family; implementing now repeats failed path.
- **C_REDESIGN_ENTRY_SIGNAL**: PRIMARY_AFTER_FOUNDATION — 98.6% clustered signals and fragile OOS indicate the research unit/entry architecture is structurally weak.
- **D_EVENT_DATASET_RESTART**: SELECTED_FIRST — Required foundation before ML or exit redesign; uses existing Phase40 events + partial ticks.
- **E_ML_AROUND_BASELINE_NOW**: REJECTED_NOT_READY — No event-level label contract, weak discriminator, high leakage risk on clustered signals.
- **F_NEW_STRATEGY_BRANCH**: PARALLEL_AFTER_BASELINE — Valid once baseline event harness exists; premature as first step.
- **G_RETIRE_STRATEGY**: NOT_YET — Positive event expectancy + legitimate structural tail remain; retire only if Research V2 falsifies entry value.

## Next research program

### WS1_EventDataset_V2
- Question: Can we construct a leakage-safe event-level dataset that preserves Phase40 outcomes and partial tick chronology?
- Success: Frozen event table with documented splits and reproducible metrics matching Phase40 event expectancy within tolerance
- Failure: Cannot reproduce event metrics or cannot prevent signal-row leakage

### WS2_EntryValue_Falsification
- Question: Do entries contain predictive value beyond random clustered opportunities before exit geometry?
- Success: Statistically detectable entry information at event unit on VAL+OOS
- Failure: Entry information indistinguishable from null after clustering correction

### WS3_TailClass_Accounting
- Question: How should metrics report core expectancy with +31.84R preserved but separately accounted?
- Success: Documented dual metric policy adopted for all future experiments
- Failure: Any experiment that silently drops the tail without policy

### WS4_ExitResearch_DeferredGate
- Question: Only if WS2 passes: is there a state-dependent exit hypothesis that preserves the tail class?
- Success: A single predeclared family improves VAL without destroying tail class
- Failure: Repeat of Phase74-105 failure modes


## Safety

All production/safety flags FALSE. NEW_TICK_DATA_REQUESTED=FALSE.

TESTS_PHASE123 = {'passed': 3, 'skipped': 0, 'failed': 0}
REGRESSION_40_43_57_63_68_123 = {'passed': 190, 'skipped': 4, 'failed': 0}

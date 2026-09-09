# Phase 73 — Exit Research Gate

**NEXT_RESEARCH_TARGET:** `PROFIT_PROTECTION_RESEARCH`

FULL-tape LOSS_SL=298: LOSS_AFTER_0.5R=157, LOSS_AFTER_1R=94, mechanism=C_PROFIT_PROTECTION, PRIMARY_CAUSE=PROFIT_GIVEBACK. The failure is give-back after meaningful MFE with no protective exit. Next work is one predeclared protection family, not SL/TP grid search.

## Spec (not implemented)

- Hypothesis `H74-01`: On the frozen event tape, a single predeclared protective-exit family (descriptive path classification: if MFE first reaches +1.0R, treat subsequent SL as a give-back failure that a breakeven-after-+1R rule would have converted) will raise TRAIN event expectancy and keep VAL confirmatory without using OOS to choose the rule.
- Single intervention family: BREAKEVEN_AFTER_PREDECLARED_PLUS_1R — one family, threshold frozen at +1.0R from the predeclared MFE diagnostic, not searched.
- Variants allowed: 1
- Success: TRAIN expectancy increases vs frozen event baseline AND VALIDATION expectancy does not reverse sign relative to its own frozen baseline AND top1-removed TRAIN expectancy is not worse than frozen top1-removed TRAIN. Gross vs modeled-cost reported separately. No profitability claim.
- Failure: VAL does not confirm TRAIN, OR the family only 'works' when the +31.84R event is required, OR implementation would need extra variants/thresholds.
- TRAIN/VAL/OOS: {'TRAIN': 'bar-index 0-150000 — may fit the single predeclared family (no search)', 'VALIDATION': '150000-200000 — confirm or reject', 'OOS': '200000-250000 — FROZEN until after VAL decision; not used to select', 'recent_180d': 'report only; never tune'}
- Multiple testing: {'families': 1, 'thresholds_searched': 0, 'bonferroni_N': 1, 'optional_second_look': 'FORBIDDEN in the next phase'}

DO_NOT_IMPLEMENT in this phase. No optimization, live, shadow, MT5, or production change.

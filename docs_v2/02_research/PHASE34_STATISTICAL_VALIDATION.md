# Phase 34 — Statistical Evidence, Bootstrap & Monte Carlo

**Status:** PASS_WITH_DEFERRAL
**Class:** RESEARCH ONLY
**Conclusion:** `INSUFFICIENT_SAMPLE`
**Live trading authorized:** NO
**Parameters optimized / searched:** NO
**Strategy/RiskGate/ML changed:** NO
**FINAL_GATE:** `BLOCKED`

STOP AFTER PHASE 34. DO NOT START PHASE 35.

Data: Phase 30 RAW, Phase 31 mechanical events, Phase 32 chronological folds.
Fingerprint `ab3e25bab0c6d6689d6654317264cc7774e1b49f88df907a3ea1bd1ade313ed5`.

---

## Units

- **Signal-level** n=24: **not** independent evidence (Phase 31 HIGH_DEPENDENCE).
- **Event-level** n=6: official inferential unit. Still below the 30-event floor.

## Bootstrap

Seed `340034`, paths `2000`. IID resample of stored R. Event-level resamples event representatives.

| Metric | Signal-level (not independent) | Event-level |
|---|---|---|
| Observed expectancy | -0.8958333333333334 | -0.5833333333333334 |
| Expectancy dist | med -0.8958333333333334 / p5 -1.0 / p95 -0.6875 | med -0.5833333333333334 / p5 -1.0 / p95 0.25 |
| Mean R dist | med -0.8958333333333334 / p5 -1.0 / p95 -0.6875 | med -0.5833333333333334 / p5 -1.0 / p95 0.25 |
| Median R dist | med -1.0 / p5 -1.0 / p95 -1.0 | med -1.0 / p5 -1.0 / p95 0.25 |
| WR dist | med 0.041666666666666664 / p5 0.0 / p95 0.125 | med 0.16666666666666666 / p5 0.0 / p95 0.5 |
| PF dist | med 0.06521739130434782 / p5 0.0 / p95 0.21428571428571427 | med 0.3 / p5 0.0 / p95 1.5 |
| Max DD dist | med 21.5 / p5 17.0 / p95 24.0 | med 4.0 / p5 2.0 / p95 6.0 |
| Loss streak dist | med 19.0 / p5 10.0 / p95 24.0 | med 4.0 / p5 2.0 / p95 6.0 |
| P(exp < 0) | 1.0 | 0.937 |
| CI contains 0 | False | True |

## Monte Carlo

Deterministic seeded simulations on stored R only. No OHLC re-walk. Shuffle permutes order (expectancy invariant; DD/streak path metrics). Bootstrap (above) is the resampling Monte Carlo. P(maxDD >= 10.0R) and P(maxDD >= 20.0R) are descriptive drawdown thresholds, not broker-margin ruin.

Shuffle P(final R < 0) signal `1.0` / event `1.0`.  
P(DD ≥ 10R) / P(DD ≥ 20R) are **not** broker-margin ruin.

## Null checks

Sign-flip null tail probabilities are **not** classical p-values and are **not** significance.  
Phase 32 folds remain INSUFFICIENT_SAMPLE; they are not bootstrapped as evidence.

## Multiple testing

Phases 28–33 reported many descriptive metrics on the same 24-setup book (RAW, event, folds, SL/RR/cost diagnostics, dependence). No parameter was searched or optimized. Sequential inspection still consumes researcher degrees of freedom. A single favorable interval or tail probability on this tape is not STATISTICALLY_SUPPORTED.

No retroactive optimization. No production change.

## CONCLUSION

**INSUFFICIENT_SAMPLE**

INSUFFICIENT_SAMPLE. Official inferential unit is the mechanical event (n=6); signal-level n=24 is dependent (Phase 31 HIGH_DEPENDENCE). Floors: resolved/events >= 30, calendar days >= 60, Phase 28.3 robustness n >= 30. Tape is ~14.9 days. Bootstrap/MC distributions are descriptive. They do not support STATISTICALLY_SUPPORTED or NOT_STATISTICALLY_SUPPORTED. One favorable metric is not significance. Shuffle DD thresholds are not broker-margin ruin.

## Safety

No MT5 trading, no `.env`, no parquet rewrite, no strategy/RiskGate/ML/parameter changes. Phase 35 was **not** started.

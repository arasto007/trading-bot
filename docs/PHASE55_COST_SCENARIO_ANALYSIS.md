# Phase 55 — Commission Scenario + Cost Survival

**Label:** `DESCRIPTIVE / SCENARIO / NOT_ACCOUNT_VERIFIED`
**Profitability verdict:** `NOT_ISSUED`

## Frozen baseline (immutable)
- Signal expectancy `0.017224` R / event `0.04866` R
- Modeled 1x spread+slip signal `-0.060787126794689415` R (commission not in that model)

## Scenario A — ECN $5/lot
- Modeled commission `0.007279` R per event
- Net event `0.041381` R
- Net signal `0.016150` R
- Net OOS signal `0.249105` R
- Net recent 180d `-0.468870` R
- Net bootstrap p5 `-0.137903` R
- Stacked with modeled 1x spread/slip: `-0.061861` R

## Scenario B/C — CLASSIC / CENT markup 14
`CLASSIC_COST_CONVERSION = UNKNOWN`  `CENT_COST_CONVERSION = UNKNOWN`

## Survival
RAW signal +0.017224R is smaller than the modeled 1x spread+slip swing to -0.060787R. ECN $5/lot is an additional SCENARIO cost of about 0.007279R/event. CLASSIC/CENT remain UNKNOWN. This is not a profitability verdict.

This is **not** the user's verified commission and **not** an executable backtest.

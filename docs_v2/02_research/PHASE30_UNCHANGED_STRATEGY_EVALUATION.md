# Phase 30 — Unchanged Strategy Long-Horizon Evaluation

**Status:** PASS_WITH_DEFERRAL
**Class:** RESEARCH ONLY
**Conclusion:** `INDETERMINATE`
**Live trading authorized:** NO
**Parameters optimized / searched:** NO
**Strategy/RiskGate/ML changed:** NO
**FINAL_GATE:** `BLOCKED`

Unchanged production `gold_ny_sweep` on the Phase 29 canonical `XAUUSD_i` M5 tape.
Phase 29 did **not** obtain a 180-day tape. This evaluation uses the frozen 15-day snapshot.

STOP AFTER PHASE 30. DO NOT START PHASE 31.

---

## Data

Fingerprint `ab3e25bab0c6d6689d6654317264cc7774e1b49f88df907a3ea1bd1ade313ed5` matches Phase 28.0–29. Empty `dataset_symbol_map`. Logical `XAUUSD` not used.

## RAW_SIGNAL_BOOK

| Metric | Value |
|---|---:|
| N | 24 |
| Events | 7 |
| Days | 5 |
| NY sessions (signal dates) | 5 |
| Wins / losses / BE | 1 / 23 / 0 |
| WR | 0.041667 |
| Expectancy R | -0.895833 |
| PF | 0.065217 |
| DD R | 22.0 |
| Loss streak | 22 |
| Median R | -1.0 |
| Avg / median duration (min) | 805.625 / 752.5 |

## EVENT LEVEL

Earliest official signal per cluster. Not an optimized pick.

| Metric | Value |
|---|---:|
| Events | 7 |
| WR | 0.142857 |
| Expectancy R | -0.642857 |
| PF | 0.25 |
| DD R | 5.0 |
| Loss streak | 5 |

## EXECUTABLE_BOOK

Candidates `24`; allowed `0`; rejected `24`.  
Attribution `{'LOT': 0, 'META': 18, 'ATR': 6, 'SPREAD': 0, 'NEWS': 0, 'SESSION': 0, 'COOLDOWN': 0, 'OTHER': 0}`.  
0 allowed is **not** a strategy failure.

## FILLED_BOOK

`NOT_OBSERVED`. n=0. No historical requested-vs-fill tape.

## COST

GROSS expectancy `-0.895833` (costs not applied).  
COST_ADJUSTED expectancy `-0.8961871383422456` labeled **MODELED** (spread/slippage MODELED_PROXY; commission/swap UNKNOWN). Not realized.

## STATISTICAL SUFFICIENCY

`DATA_INSUFFICIENT`

MIN_RESOLVED_FOR_SUFFICIENCY=30 and MIN_CALENDAR_DAYS_FOR_SUFFICIENCY=60 from Phase 28.0; unique_events uses the same 30-count independence floor. Not invented this phase.

Reasons: ['resolved_trades=24<30', 'calendar_days=14.9<60', 'unique_events=7<30']

## LOOKAHEAD

Official signals use closed M5 bars only. Exits may use later bars. SL-before-TP unchanged.

## REPRODUCIBILITY

Two evaluation passes matched: `True`.  
Strategy logic fingerprint `b0295eb95d46510d`.

## CONCLUSION

**INDETERMINATE**

INDETERMINATE. The unchanged gold_ny_sweep RAW book on the Phase 29 canonical XAUUSD_i M5 tape is DATA_INSUFFICIENT (n=24 dependent setups / 7 events / ~15 days). That does not support an edge claim and does not support a no-edge claim. EXECUTABLE allowed=0 is a RiskGate book, not a strategy verdict. No parameters were changed.

## Safety

No MT5 trading, no `.env`, no parquet rewrite, no strategy/RiskGate/ML/parameter changes. Phase 31 was **not** started.

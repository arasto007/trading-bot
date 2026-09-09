# Phase 45 — Event / OOS / Regime Robustness

**STATUS:** `PASS`
**ROBUSTNESS_VERDICT:** `FRAGILE`
**FINAL_GATE:** `BLOCKED`
**Optimization:** `NO`

Uses frozen Phase 40 artifacts only. Executable results were not available.

## Event-level

- Events: `420` (not 2847 iid signals)
- Event expectancy: `0.04866` R
- Event WR / PF / DD: `0.288783` / `1.068418` / `38.249969` R

## OOS (boundaries unchanged)

- TRAIN signal exp: `-0.032878` R (2046 signals / 283 events)
- VAL signal exp: `0.062192` R
- OOS signal exp: `0.250355` R (367 / 63)
- Count floor: SUFFICIENT. Statistical validation: **NO**.

## Time / regime / dependence

- Recent 180d: `-0.467633` R
- Clustered signal share: `0.9859501229364243`
- Top-10 event share: `0.0828942746750966`
- Bootstrap expectancy p5: `-0.1306240571545281` R (DESCRIPTIVE; CI crosses zero)

## Cost-aware

- Executable ran: `False`
- MODELED_1X: `-0.060787126794689415` R — **not validated**

Full-horizon RAW +0.017R is tiny; 2023 and 2024 yearly expectancy are negative; recent 180d is about -0.47R; 98.6% of signals are clustered; event bootstrap p5 expectancy is negative. OOS +0.25R is a later-window result, not proof of stability. Cost-aware path is MODELED/BLOCKED.

Profitability is **not** declared.

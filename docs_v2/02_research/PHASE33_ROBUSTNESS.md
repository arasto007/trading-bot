# Phase 33 — Strategy Robustness & Adversarial Reality Checks

**Status:** PASS_WITH_DEFERRAL
**Class:** RESEARCH ONLY
**Conclusion:** `INSUFFICIENT_SAMPLE`
**Live trading authorized:** NO
**Parameters optimized / searched:** NO
**Strategy/RiskGate/ML changed:** NO
**FINAL_GATE:** `BLOCKED`

STOP AFTER PHASE 33. DO NOT START PHASE 34.

Baseline: Phase 30 RAW book + Phase 32 chronological folds. Diagnostics are **not** production changes.

---

## Entry robustness

ANALYTICAL ONLY. Official entry remains the closed-bar close.

| Book | n | wins | WR | exp R | PF | material vs baseline |
|---|---:|---:|---:|---:|---:|---|
| official close | 24 | 1 | 0.041666666666666664 | -0.8958333333333334 | 0.06521739130434782 | False |
| next-bar open | 24 | 1 | 0.041666666666666664 | -0.8959544156291638 | 0.06509104456087249 | False |
| first eligible reclaim close | 24 | 1 | 0.041666666666666664 | -0.9000059347358597 | 0.06086337244953774 | False |
| small execution displacement | 24 | 1 | 0.041666666666666664 | -0.8961871383422456 | 0.06484820346896107 | False |

Displacement uses MODELED_PROXY half-spread+slippage, not OBSERVED fills.

## SL robustness

Pre-declared symmetric ±10% of the existing SL distance. Not a search.

| Book | n | wins | WR | exp R | PF | material |
|---|---:|---:|---:|---:|---:|---|
| official | 24 | 1 | 0.041666666666666664 | -0.8958333333333334 | 0.06521739130434782 | False |
| SL x0.90 | 24 | 1 | 0.041666666666666664 | -0.8888888888888887 | 0.07246376811594227 | False |
| SL x1.10 | 24 | 1 | 0.041666666666666664 | -0.9015151515151517 | 0.05928853754940695 | False |

## TP / RR robustness

Pre-declared symmetric ±0.25 around each trade's existing planned RR. Not a search. Goal is fragility, not max returns.

| Book | n | wins | WR | exp R | PF | material |
|---|---:|---:|---:|---:|---:|---|
| official | 24 | 1 | 0.041666666666666664 | -0.8958333333333334 | 0.06521739130434782 | False |
| RR -0.25 | 24 | 1 | 0.041666666666666664 | -0.90625 | 0.05434782608695652 | False |
| RR +0.25 | 24 | 1 | 0.041666666666666664 | -0.8854166666666666 | 0.07608695652173914 | False |

## Cost shocks

All MODELED / MODELED_PROXY. Commission/swap UNKNOWN. No OBSERVED broker fills.

| Book | multiplier | exp R | PF | material |
|---|---:|---:|---:|---|
| baseline | 1x | -0.8961871383422456 | 0.06484820346896107 | False |
| moderate | 2x | -0.8965385480695002 | 0.06448151505791283 | False |
| high plausible | 3x | -0.8968875867573424 | 0.06411730077494711 | False |

## Signal quality / time / events

Tertiles and weekday/week/month/regime slices are in the JSON. Slices with n < 10 are flagged. Thresholds were **not** tuned. Event-level repeats the same pre-declared diagnostics on 6 mechanical events.

## CONCLUSION

**INSUFFICIENT_SAMPLE**

INSUFFICIENT_SAMPLE. Phase 30/32 baseline is 24 dependent RAW setups / 6 mechanical events / 14.9 calendar days. Floors are Phase 28.0 resolved>= 30 and days>= 60, plus Phase 28.3 robustness n>= 30. Pre-declared diagnostics cannot support ROBUST, FRAGILE, or MIXED. Descriptive books are not a robustness proof. No parameter was optimized.

## Safety

No MT5 trading, no `.env`, no parquet rewrite, no strategy/RiskGate/ML/parameter changes. Phase 34 was **not** started.

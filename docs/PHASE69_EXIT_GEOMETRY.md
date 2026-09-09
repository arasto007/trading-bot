# Phase 69 — Exit Geometry Decomposition

**SL:** swing extreme + ATR pad (`SL_ATR_MULT=0.35`).
**TP:** hybrid `max(opposite Asian range, risk * MIN_RR)` with `MIN_RR=1.5`.
**EXTREME_WINNER_CLASSIFICATION:** `B_RARE_LEGITIMATE_STRUCTURAL`

Same evaluate_m5_london_sweep path as ordinary trades. TP is max(opposite Asian range, MIN_RR*risk). The 31.84R fill is a rare tail of that hybrid: tiny swing SL versus a distant structural TP that actually tagged. Not a conversion bug, not a different evaluator, not a rerun artifact.

Hardening does not rewrite SL/TP. Generic `price_action.py` ATR*min_rr path is not the M5 tape path.
No code was modified.

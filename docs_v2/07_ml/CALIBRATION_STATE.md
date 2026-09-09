# Calibration State

**Status:** VERIFIED  
**Last verified:** 2026-09-01  
**Epistemic-Role:** OWNER of CALIBRATION factor meaning.  
**Operator-effective state:** UNKNOWN  
**Do not calibrate v41. Do not copy v40 factors.**

## What the calibrator actually does

`tradingbot/ml/confidence_engine/engine_calibrator.py::engine_calibration_factor`:

- If `engine == "phase9_9"` and regime RANGE → RANGE span 0.8–1.3  
- If `engine == "trend_rf_v40"` (`TREND_MODEL_ID`) and regime TREND → TREND span using v40 validated constants  
- **Else → `(1.0, "neutral engine factor")`**

`trend_rf_v41` is not `TREND_MODEL_ID`, so **v41 receives 1.0** on this function. That is the production-code meaning of “v41 neutral 1.0”. It is **not** a newly fitted v41 scale.

This function is on the **ML kernel path**. Default live PA does not call it for signal ownership.

## Research classification

v41: **C**, research-watch, inactive. Evidence files: `V41_DECISION_AUDIT.md` (do not rewrite). Isolated replay metrics belong to that replay only.

## Bundle freeze

v41 checksum must remain `a433fa41…153eb6b`. This documentation batch must not rewrite the bundle.

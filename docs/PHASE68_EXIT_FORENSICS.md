# Phase 68 — Complete Exit Forensics

**EXIT_FAILURE_RATE:** `0.711217183770883`  **LOSS_SL:** `298`  **WIN_TP:** `121`
**LOSS_AFTER_0.5R:** `157`  **LOSS_AFTER_1R:** `94`
**MEDIAN_TIME_TO_REVERSAL (MFE to SL):** `25.0` minutes
**PRIMARY_MECHANISM:** `C_PROFIT_PROTECTION`

Path metrics are DERIVED from a read-only SL-before-TP walk of frozen `data/XAUUSD_i_5m_phase38.parquet`.
Jsonl MFE/MAE remain OBSERVED. Strategy was not rerun. Event tape was not altered.
The +31.84R event remains in the official baseline.

Cohorts are predeclared (not searched): LOSS_AFTER_PROFIT / 0.5R / 1R, FAST/SLOW reversal, IMMEDIATE, WIN_FAST/SLOW/EXTREME.

No optimization. No production change. No MT5.

# Phase 64 — Strategy Event Forensics

**PRIMARY:** `EXIT_PROBLEM`  **SECONDARY:** `TIME_DEPENDENCY`  **TERTIARY:** `SIDE_ASYMMETRY`
**Resolved events:** 419  **LOSS_SL:** 298  **WIN_TP:** 121
**Outlier:** `2026-01-21 15:40:00+00:00` `SELL` R=`31.836734693874295`

All resolved events classify as WIN_TP or LOSS_SL (theoretical SL/TP exits). Modeled spread+slip is ~0.00x R vs -1R SL; spread does not explain stop-outs. A large share of losers first moved favorably (MFE), then hit SL.

This SELL hit theoretical TP with planned_rr ~31.8 because SL distance was small relative to a distant TP. Median winning planned_rr is ~1.66. Only one win has planned_rr>=10. Mechanism (liquidity_sweep SL/TP geometry) is the strategy; the fill magnitude is exceptional.

No SL/TP/parameter/strategy changes. Diagnosis only.

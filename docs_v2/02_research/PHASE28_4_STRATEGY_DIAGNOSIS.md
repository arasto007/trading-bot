# Phase 28.4 — Strategy Diagnosis

**Status:** PASS_WITH_DEFERRAL
**Class:** RESEARCH ONLY
**Live trading authorized:** NO
**Parameters optimized / searched:** NO
**FINAL_GATE:** `BLOCKED`
**Official answer:** `J` — cannot determine a single proven cause

Diagnosis of the **stored** 24 RAW `gold_ny_sweep` setups. No production behavior change.

STOP AFTER PHASE 28.4. DO NOT START PHASE 28.5.

---

## Dataset

Fingerprint `ab3e25bab0c6d6689d6654317264cc7774e1b49f88df907a3ea1bd1ade313ed5` matches Phase 28.0–28.3. Canonical parquet was not rewritten.

RAW setups: 24 (BUY 16 / SELL 8; 1 win / 23 losses). EXECUTABLE: 0 allowed / 0 fills.

---

## Reconstructed RAW book

| ts UTC | dir | fold | entry | SL | TP | R | out | cluster | ATR% | regime | q | RG |
|---|---|---|---:|---:|---:|---:|---|---:|---:|---|---:|---|
| 08-20 15:35 | SELL | TRAIN | 4518.47 | 4544.54 | 4477.81 | -1.00 | loss | 0 | 100.0 | STRONG_TREND_UP | 68 | ATR |
| 08-20 15:40 | SELL | TRAIN | 4511.39 | 4544.65 | 4461.50 | -1.00 | loss | 0 | 100.0 | STRONG_TREND_UP | 68 | ATR |
| 08-20 15:45 | SELL | TRAIN | 4520.08 | 4544.72 | 4477.81 | -1.00 | loss | 0 | 100.0 | STRONG_TREND_UP | 78 | ATR |
| 08-20 15:50 | SELL | TRAIN | 4518.84 | 4544.68 | 4477.81 | -1.00 | loss | 0 | 99.6 | STRONG_TREND_UP | 68 | ATR |
| 08-24 15:45 | SELL | VALIDATION | 4646.78 | 4682.41 | 4593.33 | -1.00 | loss | 1 | 76.1 | RANGING | 76 | META |
| 08-24 15:50 | SELL | VALIDATION | 4653.23 | 4682.43 | 4594.61 | -1.00 | loss | 1 | 77.3 | RANGING | 68 | META |
| 08-24 15:55 | SELL | VALIDATION | 4648.92 | 4682.56 | 4594.61 | -1.00 | loss | 1 | 84.5 | RANGING | 68 | META |
| 08-25 15:00 | BUY | VALIDATION | 4632.07 | 4610.94 | 4696.62 | -1.00 | loss | 2 | 74.9 | RANGING | 68 | META |
| 08-25 15:05 | BUY | VALIDATION | 4632.36 | 4611.25 | 4696.62 | -1.00 | loss | 2 | 66.9 | RANGING | 68 | META |
| 08-25 15:10 | BUY | VALIDATION | 4633.13 | 4611.34 | 4696.62 | -1.00 | loss | 2 | 64.1 | RANGING | 68 | META |
| 08-25 15:15 | BUY | VALIDATION | 4638.69 | 4611.27 | 4696.62 | -1.00 | loss | 2 | 66.5 | RANGING | 68 | META |
| 08-25 15:20 | BUY | VALIDATION | 4640.53 | 4611.23 | 4696.62 | -1.00 | loss | 2 | 68.1 | RANGING | 76 | META |
| 08-25 15:25 | BUY | VALIDATION | 4639.72 | 4611.21 | 4696.62 | -1.00 | loss | 2 | 68.5 | RANGING | 68 | META |
| 08-25 15:30 | BUY | VALIDATION | 4648.72 | 4611.12 | 4705.12 | -1.00 | loss | 2 | 71.3 | RANGING | 76 | META |
| 08-27 15:00 | BUY | OOS | 4593.88 | 4566.24 | 4642.95 | -1.00 | loss | 3 | 89.2 | RANGING | 68 | META |
| 08-27 15:15 | BUY | OOS | 4597.01 | 4571.56 | 4642.95 | -1.00 | loss | 3 | 85.3 | RANGING | 68 | META |
| 08-27 15:30 | BUY | OOS | 4596.99 | 4579.11 | 4642.95 | -1.00 | loss | 3 | 83.7 | RANGING | 68 | META |
| 08-27 15:35 | BUY | OOS | 4599.48 | 4583.78 | 4642.95 | -1.00 | loss | 4 | 76.9 | RANGING | 76 | META |
| 08-27 15:40 | BUY | OOS | 4601.10 | 4584.80 | 4642.95 | -1.00 | loss | 4 | 78.5 | STRONG_TREND_UP | 88 | META |
| 08-27 15:45 | BUY | OOS | 4604.16 | 4586.11 | 4642.95 | -1.00 | loss | 4 | 77.7 | STRONG_TREND_UP | 80 | META |
| 08-27 15:50 | BUY | OOS | 4609.46 | 4586.21 | 4644.34 | -1.00 | loss | 4 | 73.7 | STRONG_TREND_UP | 88 | META |
| 08-27 15:55 | BUY | OOS | 4610.32 | 4586.27 | 4646.39 | -1.00 | loss | 4 | 69.7 | STRONG_TREND_UP | 88 | META |
| 08-28 15:00 | SELL | OOS | 4579.91 | 4640.06 | 4489.68 | 1.50 | win | 5 | 100.0 | VOLATILE | 80 | ATR |
| 08-28 15:05 | BUY | OOS | 4572.67 | 4522.48 | 4647.96 | -1.00 | loss | 6 | 98.8 | STRONG_TREND_DOWN | 68 | ATR |

Do **not** treat 24 rows as 24 independent trades. See overlap.

---

## ENTRY

Official: close of the closed signal bar. `SIGNAL_CONFIRMATION_BARS=0`.

| Book | n | wins | WR | exp R |
|---|---:|---:|---:|---:|
| Official close | 24 | 1 | 0.0417 | -0.8958 |
| Next-bar open (counterfactual) | 24 | 1 | 0.0417 | -0.8960 |
| After first reclaim close (counterfactual) | 24 | 1 | 0.0417 | -0.9000 |
| After +1 bar confirmation (counterfactual) | 24 | 1 | 0.0417 | -0.9070 |

Same-bar sweep+reclaim: `2` / 24.

These counterfactuals are **ANALYTICAL ONLY**. They reuse stored SL/TP. They are not candidate rules.

---

## SL

Median SL distance `25.96` (3.3268 ATR). Median distance beyond sweep `0.3500` ATR (configured pad 0.35).

Stopped then later touched original TP: `6` / 24 (`0.2500`).

MAE median / p95: `1.0209` / `1.1732` R.

---

## TP / RR

RR **not** changed. Planned RR median `1.7900` (min `1.5000`, max `3.0600`).

MFE before official exit: median `0.8932` R, p95 `1.9343` R. MFE ≥ 1.5R before stop: `4` / 24.

---

## SESSION

Configured NY `15-16 UTC`; Asian end `8:00` UTC. All 24 signals hour 15 UTC: `True`. Unique signal dates: `5`.

BY DESIGN the M5 window is only 15:00–15:59 UTC. All 24 official signals are in that single hour. That concentrates the RAW book into a handful of NY opens, not a round-the-clock sample. It does not prove the window is wrong.

---

## REGIME / SIGNAL QUALITY / OVERLAP

Regime counts: `{'STRONG_TREND_UP': 8, 'RANGING': 14, 'VOLATILE': 1, 'STRONG_TREND_DOWN': 1}`. ATR% median `77.4900`. ADX filter is off on M5 RAW. ATR percentile is RiskGate, not RAW.

Quality median `68.0000`; all 24 already ≥ 55. `M5_REQUIRE_REJECTION=False`.

Event clusters: `7` (singletons `2`, clustered setups `22`, largest `7`).

---

## Root-cause ranking

**PRIMARY:** `G` — Data/sample limitations  
Confidence: HIGH that inference is blocked; LOW that G 'causes' the -0.90R path

**SECONDARY:** `H` — Overlapping setups / trade independence  
Confidence: HIGH as an observation on this tape

**TERTIARY:** `I` — Combination of SL placement (C), signal repetition (A), and session window (E)  
Confidence: MEDIUM as a plausible mechanism on this tape; NOT proven out of sample

**UNRESOLVED:** ['B', 'D', 'F', 'J'] — Entry-timing (B), TP/RR realism (D), market-regime mismatch (F) as standalone primaries; and J — cannot determine a single proven structural cause

Official answer to “what primarily caused the poor RAW results?”: **J**.  
Cannot determine a single proven cause of the poor RAW path from 24 dependent theoretical setups. G is proven as an inference limit. H/C/A/E are observed or plausible on this tape only.

---

## Proven vs not proven

**Proven:** The approved XAUUSD_i M5 tape is statistically insufficient for edge or no-edge claims (28.0–28.3). All 24 official RAW timestamps fall in 15:00–15:59 UTC. The 24 rows are not independent (7 event clusters). EXECUTABLE remains 0 allowed / 0 fills (META/ATR), which is a separate book. FINAL_GATE remains BLOCKED. Fingerprint unchanged.

**Not proven:** NOT_PROVEN: that gold_ny_sweep is a bad strategy; that it is a good strategy; that close-entry, 0.35 ATR SL, 1.5 RR, or the NY 15-16 window is the unique cause; that changing any of those would improve live or longer-tape results; that META/ATR rejects prove no edge. Counterfactual books are not optimized alternatives.

## RiskGate (separate)

RiskGate attribution stays separate from RAW diagnosis. META=18 ATR=6 0 allowed / 0 fills. 0 executable ≠ no edge.

## Recommendation for a later phase (not started)

Do not start parameter optimization. If a later research phase exists, prefer (1) a longer defensible XAUUSD_i tape or (2) event-level (cluster) analysis of the same unchanged rules. Do not change SL/TP/RR/session/RiskGate from this 24-row book. Phase 28.5 was not started.

## Safety

No MT5, no `.env`, no parquet rewrite, no strategy/RiskGate/ML/parameter changes. Phase 28.5 was **not** started.

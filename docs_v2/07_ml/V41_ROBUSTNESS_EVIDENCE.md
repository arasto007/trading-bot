# V41 Robustness Evidence (Phases 1.5.48–1.5.50)

**Status:** RESEARCH / SENSITIVITY + DIAGNOSTIC ROBUSTNESS  
**Last verified:** 2026-08-31  
**Live impact:** none  
**Classification:** **C — insufficient evidence**  
**v41 production factor:** remains **neutral 1.0**

Uses **only** the frozen isolated TREND book  
`data/ml/reports/phase15_36/v41_isolated_trend_replay.json` (OOS n=3,409).  
That file was **not** rewritten. New numbers: `data/ml/reports/phase15_46/v41_cost_followup.json`.

Cost-tape findings: `docs_v2/07_ml/V41_COST_EVIDENCE_AUDIT.md`.  
These R scenarios are **not** claimed to be broker costs.

No thresholds or session/hold filters were optimized or selected for live use.

---

## Phase 1.5.48 — extended R-cost sensitivity (OOS)

Formula: `R_net_i = R_gross_i − c` for every trade. Break-even `c* = mean(R) = 0.033044 R` (OOS aggregate). Same `c*` for PF=1 on this book.

| c (R) | Trades | WR | Total R | Exp | PF | Max DD | Sharpe | Terminal R | Exp>0 | PF>1 |
|-------|--------|----|---------|-----|----|--------|--------|------------|-------|------|
| 0.00 | 3409 | 34.44% | +112.65 | +0.0330 | 1.050 | −33.02 | 0.023 | +112.65 | yes | yes |
| 0.01 | 3409 | 34.44% | +78.56 | +0.0230 | 1.035 | −34.90 | 0.016 | +78.56 | yes | yes |
| 0.02 | 3409 | 34.44% | +44.47 | +0.0130 | 1.020 | −37.68 | 0.009 | +44.47 | yes | yes |
| 0.03 | 3409 | 34.44% | +10.38 | +0.0030 | 1.005 | −42.56 | 0.002 | +10.38 | yes | yes |
| **0.04** | 3409 | 34.44% | **−23.71** | **−0.0070** | **0.990** | −56.12 | −0.005 | **−23.71** | **no** | **no** |
| 0.05 | 3409 | 34.44% | −57.80 | −0.0170 | 0.975 | −80.52 | −0.012 | −57.80 | no | no |
| 0.08 | 3409 | 34.44% | −160.07 | −0.0470 | 0.934 | −178.02 | −0.033 | −160.07 | no | no |
| 0.10 | 3409 | 34.44% | −228.25 | −0.0670 | 0.907 | −244.02 | −0.047 | −228.25 | no | no |

Conservative lab bar (PF≥1.20 and exp≥0.05): **failed at every c, including 0**.

Fold break-evens: 2025 **0.0276 R**, 2026 **0.0371 R**. Not evidence that live costs are below those values.

---

## Phase 1.5.49 — robustness (uncosted OOS unless noted)

**Verdict:** `concentrated_and_disappears_under_modest_costs`.

### Year / month

Both OOS years slightly positive uncosted. Months 2025-11, 2026-03, 2026-06 negative. Unstable month-to-month. Not a single-year artifact, not a stable edge.

### Direction

BUY n=2335 exp +0.016 PF 1.024; SELL n=1074 exp +0.070 PF 1.109. SELL stronger. **Not selected as a filter.**

### Session (UTC)

Asian (+0.144 / PF 1.23) carries the book. London, New York, overlap are **negative**. Session-dependent. **Not selected as a live filter.**

### Holding duration

1–3 bars: n=1525, exp **−0.335**, −511 R. Holds ≥4 bars carry all the profit. **Not selected as a hold filter.**

### Probability

0.60+ ≈ 0 expectancy. Best uncosted bucket 0.45–0.50. Higher v41 probability is not a better trade. **Threshold 0.4 not retuned.**

### Losing streak

Longest consecutive losses: **14**.

### Rolling trade windows (new)

Time-ordered, no reordering. Diagnostic only.

| Window | n windows | Exp p50 | Exp min / max | Frac exp>0 | PF p50 | Frac PF>1 | DD p50 |
|--------|-----------|---------|---------------|------------|--------|-----------|--------|
| 250 | 3160 | +0.020 | −0.088 / +0.188 | **66.7%** | 1.030 | 66.7% | −20 R |
| 500 | 2910 | +0.037 | −0.040 / +0.116 | **82.9%** | 1.057 | 82.9% | −26 R |

One-third of 250-trade windows lose even **uncosted**. Max PF in any 500-window is **1.185** — still below the 1.20 conservative bar. A lucky window is **not** a strategy.

### Drawdown vs expectancy

Uncosted max DD **−33 R** vs +0.033 R/trade. Incompatible. After c=0.04 R, terminal **−24 R** and DD **−56 R**.

---

## Phase 1.5.50 — classification

**C — insufficient evidence**

| Class | Why not |
|-------|---------|
| A | No full cost tape; 0.04 R kills expectancy; rolling 250-windows lose 33% of the time uncosted; DD incompatible; session/duration concentration; 17 live slips INSUFFICIENT |
| B | Extra evidence shows the residual is not modest-cost robust. Keeping B would overstate |
| D | Uncosted OOS expectancy is still slightly positive |

**v41 remains neutral 1.0.** No changes to `engine_calibrator.py`, `calibration_policy.py`, `risk_types.py`, `TREND_MODEL_ID`, or `TREND_ENGINE_ID`.

---

## Limitations

- R-grid ≠ broker costs  
- 17 live slips ≠ round-trip spread tape  
- Research symbol XAUUSD ≠ proven live `XAUUSD_i`  
- No commission tape  
- Favorable slices were **not** promoted to filters

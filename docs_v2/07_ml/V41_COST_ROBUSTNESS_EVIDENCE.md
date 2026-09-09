# V41 Cost Realism & Robustness Evidence (Phases 1.5.41–1.5.45)

**Status:** RESEARCH / SENSITIVITY ANALYSIS — not proof of live profitability  
**Last verified:** 2026-08-31  
**Live impact:** none  
**Classification:** **C — insufficient evidence**  
**Production factor:** v41 remains **neutral 1.0**  
**Real-world XAUUSD costs:** **UNKNOWN** (no historical spread/tick files)

Frozen model, book, and production calibrators were not modified. No v40 calibration factors were transferred.

Machine-readable report: `data/ml/reports/phase15_41/v41_cost_robustness.json`  
Source book: `data/ml/reports/phase15_36/v41_isolated_trend_replay.json` (10,734 trades; **3,409 OOS**)

---

## 1. Executive conclusion

The uncosted isolated TREND OOS book remains a thin **+0.033 R / PF 1.050** residual. That residual **does not survive plausible cost assumptions** taken from this repo’s own paper/backtest defaults, converted with the same ATR-14 that defines 1R.

- Median OOS ATR ≈ **4.50** gold points → 1R ≈ $4.50/oz  
- Entire OOS edge ≈ **0.033 × 4.50 ≈ 0.15 points** per trade  
- PaperBroker entry-only default (0.25 points) ≈ **0.056 R** at that ATR → OOS expectancy **−0.031 R**, PF **0.96**  
- Assumed round-trip 0.50 points ≈ **0.11 R** → expectancy **−0.095 R**, PF **0.87**  
- Break-even round-trip cost is **0.033 R** (property of this book, not a measured spread)

Historical bid/ask tape: **missing**. Results are **SENSITIVITY ANALYSIS**. Classification moves from prior **B** to **C**. v41 stays **neutral 1.0**.

---

## 2. Phase 1.5.41 — cost model audit

No broker costs were invented. `data/ml/raw/spread/` and `data/ml/raw/ticks/` exist as directories with **zero files**.

| Mechanism | Class | Why |
|-----------|-------|-----|
| Historical spread parquet | **C** | 0 files — no trustworthy bid/ask tape |
| Historical tick parquet | **C** | 0 files — cannot reconstruct fills |
| `PaperBroker` (spread 0.30 / slip 0.10 / commission 0) | **B** | paper defaults, not measured; exit spread not charged in `execute_entry` |
| `BacktestConfig` 2.5 pips + 0.8 slip, pip=0.1 for XAU | **B** | hardcoded heuristics + session multipliers |
| `execution_costs.py` | **B** | synthetic multipliers on an assumed `spread_points` |
| Phase 6A `apply_execution_stress` (4.0 pips, VOL-v2) | **B** | wrong strategy family; not v41 evidence |
| Phase 19A random 0–0.15 R / 0–0.1 R | **D** | fabricated; mixed RANGE+TREND book |
| Live MT5 slippage journal / RiskGate `tick_value` | **C** | live-only; MT5 not started |

**INSUFFICIENT EVIDENCE — NOT PROVEN** that any of the class-B defaults equal this operator’s live XAUUSD_i spread.

Reusable offline method (class B, labeled): subtract a constant round-trip **c** (in R) from every frozen-book R-multiple, and/or `cost_R_i = points / ATR_i` using ATR-14 at the trade timestamp.

---

## 3. Exact formulas

SL = ATR × 1.0, so **1R = ATR(14) in price points** (same series as the isolated replay).

Flat sensitivity (primary, book-only):

```text
R_net_i = R_gross_i − c     for every trade
expectancy_net = mean(R) − c
```

Per-trade point assumption (class B):

```text
cost_R_i = round_trip_points / ATR_i
```

Round-trip point recipes used as **labels**, not measurements:

| Label | Points | Recipe |
|-------|--------|--------|
| Paper entry-only | 0.25 | `spread/2 + entry_slip` = 0.15+0.10 |
| Paper round-trip (assumed both legs) | 0.50 | `spread + 2*slip` |
| Backtest defaults | 0.41 | `(2.5 + 2*0.8) * 0.1` pip_size |

Conservative viability bar (lab only, **not** a v40-factor copy): PF ≥ 1.20 and expectancy ≥ 0.05 R. Uncosted OOS **fails** this bar.

---

## 4. Phase 1.5.42 — cost-sensitivity (OOS 3,409 trades)

All rows are **SENSITIVITY ANALYSIS**. Trade count stays 3,409; WR stays 34.44% until c is large enough to flip +2 R winners (none of these c values do).

| Scenario | c (R) | Total R | Exp R | PF | Max DD | Sharpe | Exp>0 | PF>1 | Conservative viable |
|----------|-------|---------|-------|----|--------|--------|-------|------|---------------------|
| 0 cost (baseline) | 0.00 | +112.65 | +0.0330 | 1.050 | −33.02 | 0.023 | yes | yes | **no** |
| low | 0.01 | +78.56 | +0.0230 | 1.035 | −34.90 | 0.016 | yes | yes | **no** |
| medium | 0.03 | +10.38 | +0.0030 | 1.005 | −42.56 | 0.002 | yes | yes | **no** |
| high | 0.08 | −160.07 | −0.0470 | 0.934 | −178.02 | −0.033 | **no** | **no** | **no** |
| break-even E=0 | 0.033 | 0.00 | 0.000 | 1.000 | −46.68 | 0 | no | no | no |

### Class-B paper/backtest assumptions (ATR-scaled, 3,409 mapped, 0 missing)

Median ATR 4.50 (mean 5.31; p25 3.22; p75 6.33).

| Assumption | Mean cost R | Exp R | PF | Max DD | Exp>0 | PF>1 |
|------------|-------------|-------|----|--------|-------|------|
| Paper entry-only 0.25 pt | 0.064 | **−0.031** | 0.956 | −125 | no | no |
| Paper round-trip 0.50 pt | 0.128 | **−0.095** | 0.871 | −336 | no | no |
| Backtest default 0.41 pt | 0.105 | **−0.072** | 0.901 | −260 | no | no |

Uncosted edge at median ATR is **0.15 points**. Every class-B default in this repo is **larger than that**.

---

## 5. Phase 1.5.43 — break-even

`c*_E = mean(R)`. For this book almost all wins are +2 R and losses −1 R, so `c*_PF≈1` equals `c*_E`.

| Book | n | Gross exp | c* for E=0 | c* for PF=1 |
|------|---|-----------|------------|-------------|
| OOS aggregate | 3,409 | +0.033044 | **0.033044 R** | **0.033044 R** |
| OOS 2025 | 1,450 | +0.027570 | **0.027570 R** | **0.027570 R** |
| OOS 2026 | 1,959 | +0.037096 | **0.037096 R** | **0.037095 R** |

Plain language: after freeze end, the frozen v41 TREND book can pay about **3.3% of 1R** in round-trip costs before expectancy hits zero. At median ATR 4.50 that is **~0.15 gold points** (~$0.15/oz). Typical gold spreads are not proven here, but the repo’s own 0.30-point paper default already exceeds that. **Break-even is not evidence that live costs are below it.**

At medium c=0.03 R (just under break-even): 2025 OOS expectancy **−0.0024**, 2026 **+0.0071**. The 2025 fold dies first.

---

## 6. Phase 1.5.44 — robustness (uncosted OOS unless noted)

**Not optimized. Favorable slices are not adopted as a new strategy.**

### Year

Both OOS years slightly positive uncosted (2025 PF 1.042, 2026 PF 1.057). After 0.03 R cost, **2025 is negative**.

### Month

Negative uncosted months: **2025-11, 2026-03, 2026-06**. Other months n≥123 (all ≥30). Unstable month-to-month expectancy. Not a single-month artifact, but not stable either.

### Direction

| Side | n | Exp | PF | Max DD |
|------|---|-----|----|--------|
| BUY | 2,335 | +0.016 | 1.024 | −47 |
| SELL | 1,074 | +0.070 | 1.109 | −32 |

SELL is stronger; BUY is barely positive. **Do not drop BUY to manufacture a better book.**

### Session (UTC hour buckets from `execution_costs.session_from_hour`)

| Session | n | Exp | PF | Viable? |
|---------|---|-----|----|---------|
| asian 00–08 | 1,170 | **+0.144** | **1.232** | yes (uncosted only) |
| late 21–24 | 405 | +0.111 | 1.176 | no (PF<1.20) |
| london 08–13 | 852 | **−0.014** | 0.979 | no |
| new_york 16–21 | 528 | **−0.029** | 0.957 | no |
| overlap 13–16 | 454 | **−0.161** | 0.777 | no |

Uncosted OOS edge is **session-concentrated (Asian)**. London/NY/overlap lose. This is a robustness defect, not a license to session-filter live.

### Duration

| Hold | n | Exp | PF |
|------|---|-----|----|
| 1–3 bars | 1,525 | **−0.335** | 0.57 |
| 4–12 | 1,479 | +0.292 | 1.51 |
| 13–36 | 370 | +0.486 | 1.96 |
| 37–72 | 35 | +0.342 | 1.63 |

Fast SL cluster (1–3 bars) **destroys −511 R**. Survivors that last ≥4 bars carry the whole book. **Do not** add a hold filter post-hoc.

### Probability bucket

Highest-prob trades (0.60+) have expectancy **+0.002** (almost nothing). Best uncosted bucket is 0.45–0.50 (+0.10). **Higher v41 probability is not a better trade.** Do not retune the 0.4 threshold from this.

### TREND subtype

All book rows are already `regime=TREND`. No further subtype in the frozen book.

### Concentration / streaks / DD

- Almost all wins are **+2.0 R** (TP), losses **−1.0 R** (SL). Not a few lottery winners; it is a 1:2 RR mass.
- Top 10 winners = 20 R = **17.8%** of net +112.6 R — not a handful of outliers, but net R is a **thin residual** of large win/loss mass (gross wins ~2,348 R vs gross losses ~2,235 R).
- Longest losing streak: **14**
- Uncosted max DD **−33 R** vs expectancy **+0.033 R** ≈ **1,000 trades of edge to recover DD**. Incompatible with a 0.03 R edge.
- After any class-B point assumption, DD is **−125 to −336 R**.

---

## 7. Phase 1.5.45 — classification

Exactly one class:

**C — insufficient evidence**

| Class | Why not |
|-------|---------|
| A | Edge does not survive plausible paper/backtest costs; never clears PF≥1.20 / exp≥0.05 even uncosted; session + duration concentration; DD incompatible |
| B | Prior class assumed “more evidence needed.” That evidence now shows the thin OOS residual is **not robust to costs**. Keeping B would overstate |
| D | Uncosted OOS expectancy is still slightly positive — not a proof of zero gross edge |

**v41 remains neutral 1.0.** No writes to `engine_calibrator.py`, `calibration_policy.py`, `risk_types.py`, `TREND_MODEL_ID`, `TREND_ENGINE_ID`, factory, RiskGate, execution, live config, `.env`, or the frozen bundle.

---

## 8. Limitations / negative findings

- Real-world costs: **UNKNOWN**
- Research symbol XAUUSD ≠ live `XAUUSD_i`
- ATR conversion uses bar ATR, not tick path
- Paper/backtest defaults are class **B**, not measurements
- High/low fill model still ignores spread on the isolated replay path
- Session/duration/probability patterns are **descriptive**, not new rules
- Commission in paper/backtest configs is 0.0 — **INSUFFICIENT EVIDENCE — NOT PROVEN** that commission is zero live

---

## 9. Tests

`tests/test_v41_cost_robustness.py` — flat-cost identity, break-even = mean R, point-to-R conversion, insufficient slices, classification C when costs unknown and paper assumption negative, v41 stays neutral, no live/MT5 imports.

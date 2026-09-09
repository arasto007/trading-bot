# Phase 36 — Strategy Evidence Verdict & Research Decision

**Status:** PASS
**Class:** RESEARCH ONLY
**Strategy verdict:** `INSUFFICIENT_EVIDENCE`
**Live trading authorized:** NO
**Parameters optimized / searched:** NO
**Production changed:** NO
**FINAL_GATE:** `BLOCKED`

STOP AFTER PHASE 36. DO NOT START PHASE 37.
DO NOT OPTIMIZE. DO NOT MODIFY PRODUCTION.

This phase synthesizes Phases 28.0–35 against the current production `gold_ny_sweep`
implementation, RiskGate, cost model, provenance, and frozen dataset fingerprint.
It is **not** an optimization phase.

---

## Verdict

**INSUFFICIENT_EVIDENCE**

Allowed codes: A `EVIDENCE_SUPPORTS_EDGE` · B `EVIDENCE_DOES_NOT_SUPPORT_EDGE` · C `EVIDENCE_SUPPORTS_NO_EDGE` · D `INSUFFICIENT_EVIDENCE`.

A and C were not used: they require genuinely strong evidence.

- **A not selected:** No completed phase produced independent, cost-complete, filled, or sufficient-sample evidence of an edge. A requires genuinely strong evidence.
- **B not selected:** Not selected. Repeating the same 15-day RAW book across Phases 28–35 would upgrade an insufficient description into a strategy finding. Phase 30 already recorded that the book does not support an edge claim and does not support a no-edge claim.
- **C not selected:** Event n=6, calendar days ~14.88, event expectancy CI contains 0, cost completeness INCOMPLETE, FILLED n=0. C requires genuinely strong evidence of no edge.
- **D selected:** Sufficiency floors from Phase 28.0 are unmet (resolved>=30, events>=30, days>=60). Phase 29 did not obtain a 60- or 180-day M5 tape. Cost AND-gate is 0/8 COMPLETE. That missing evidence prevents A, B, and C.

`edge_exists_claim=false`. `no_edge_exists_claim=false`.
Theoretical performance is **not** live performance.

---

## Distinctions

| Layer | Finding |
|---|---|
| Strategy signal quality | Theoretical closed-bar gold_ny_sweep setups on this tape: 24 dependent rows, 1/23, expectancy about −0.90 R. Not live. Not cost-adjusted. Not independent. |
| RiskGate behavior | 0 allowed / 24 rejected (META 18, ATR 6). Separate from RAW. 0 allows is not a strategy verdict. |
| Execution behavior | NOT_OBSERVED. Requested/executed pairs were not fabricated. SimulatedBroker is not realized. |
| Broker costs | AND-gate INCOMPLETE. MODELED not VERIFIED. Theoretical edge surviving economics: NOT_PROVEN. |
| Data quality | Canonical OHLC has 0 duplicate/malformed/impossible candles on the frozen snapshot. Bid/Ask production parquet is PROXY. Sidecar 27.26 is OBSERVED for that window only. Provenance PARTIAL. EV-EQ-01 NOT_PROVEN. |
| Sample sufficiency | DATA_INSUFFICIENT / INSUFFICIENT_SAMPLE across Phases 28.0–34. Official inferential unit n=6 events. |

Do not blame the strategy for RiskGate rejection.
Do not blame RiskGate for RAW strategy performance.

---

## Evidence hierarchy

Repeated reports of the same 15-day book are **one** observation, not twelve independent confirmations.

### PROVEN

- Canonical M5 fingerprint is frozen and matches Phases 28.0–35.
- Defensible XAUUSD_i M5 coverage is ~14.88 days / 3000 bars, below the 60-day floor.
- Sufficiency floors (resolved>=30, events>=30, days>=60) are unmet.
- On this tape the RAW book is 24 dependent setups, 1 win / 23 losses. This is a tape description, not a population parameter.
- Phase 31 HIGH_DEPENDENCE: 24 signals collapse to 6 mechanical events. Treating signals as independent is disallowed.
- EXECUTABLE allowed=0 (META 18, ATR 6). This is a RiskGate book, not a strategy failure.
- FILLED is NOT_OBSERVED (n=0). Theoretical R is not live fill P/L.
- Cost completeness AND-gate is INCOMPLETE (0/8). Cost-adjusted validation remains forbidden.
- EV-EQ-01 remains NOT_PROVEN. Logical XAUUSD tapes were not used.
- Phase 28.4 official answer is J: no single proven structural cause of the RAW path.
- Event-level bootstrap expectancy CI contains 0 (p5=-1.00, p95=+0.25). That is not significance.
- Phases 28–35 did not optimize parameters and did not change production strategy/RiskGate/ML.
- Production FINAL_GATE remains BLOCKED. This phase does not authorize live trading.

### STRONGLY SUPPORTED

- No completed phase produced evidence that supports an edge claim (A is not available).
- On this tape, every chronological fold’s RAW expectancy is negative. Descriptive only; folds are FOLD_INSUFFICIENT.
- Live production owner remains PriceActionStrategy / gold_ny_sweep / london_sweep on XAUUSD_i M5, unchanged by this phase.

### PLAUSIBLE

- Overlapping holds, shared stops, and NY 15–16 concentration can inflate RAW loss count on this tape (Phase 28.4 H/A/C/E).
- META and ATR gates would have blocked these RAW candidates if they were live. That does not diagnose RAW signal quality.
- Broker economics, if later COMPLETE and adverse, could further reduce any hypothetical theoretical expectancy. Survival is currently NOT_PROVEN, not disproven.

### UNRESOLVED

- Whether gold_ny_sweep has a trading edge on a longer defensible XAUUSD_i tape.
- Whether any theoretical edge would survive COMPLETE broker costs.
- Whether SL, TP/RR, entry timing, session window, or regime is a structural cause.
- Live requested-vs-executed fill, partial, rejection, requote, and latency behavior.
- Account-applicable commission schedule and historical swap series.
- Genuine realized slippage (requested vs executed). MT5 deviation is not that quantity.
- EV-EQ-01 equivalence of logical XAUUSD to XAUUSD_i.

### DISPROVEN

- That 24 RAW signals are 24 independent market events.
- That 0 RiskGate allows proves the strategy has no edge.
- That RiskGate caused the RAW −0.90 R path. RAW is scored before the gate.
- That theoretical R is live or filled performance.
- That MODELED / MODELED_PROXY costs are VERIFIED.
- That this tape meets the 60-day or 180-day research floors.
- That EV-EQ-01 is proven.
- That cost-adjusted validation is authorized.
- That MT5 deviation is realized slippage.
- That short-tape zero commission or swap is a verified schedule.
- That repeating the same unsupported claim across phases upgrades its evidence grade.

---

## Canonical code (unchanged)

| Item | Value |
|---|---|
| Symbol | `XAUUSD_i` |
| Preset | `gold_ny_sweep` / `london_sweep` |
| NY window | 15–16 UTC |
| Asian end | 8:00 UTC |
| MIN_CONFIDENCE | 0.52 |
| MIN_QUALITY_SCORE | 55 |
| MIN_RR / TP_RR | 1.5 / 1.5 |
| SL_ATR_MULT | 0.35 |
| COOLDOWN_BARS | 18 |
| MAX_TRADES_PER_DAY | 3 |
| META_LABEL_THRESHOLD | 0.38 |
| Fingerprint | `ab3e25bab0c6d6689d6654317264cc7774e1b49f88df907a3ea1bd1ade313ed5` |

Citations: `PRIMARY_SYMBOL`, `PA_SYMBOL_TF_PRESETS["XAUUSD"]["M5"]`, `PriceActionStrategy`, `evaluate_m5_london_sweep`, `RiskGate`, `SimulatedBroker` (commission UNKNOWN fail-closed).

---

## If edge existed

Not applicable. A was not selected. No controlled optimization phase is opened.

## If edge does not exist

C was not selected. Cause review (evidence-supported only):

| Candidate | Status |
|---|---|
| Signal definition | UNRESOLVED — not proven; HIGH_DEPENDENCE is an independence finding. |
| Entry | UNRESOLVED — Phase 28.4 counterfactuals were analytical only. |
| SL | PLAUSIBLE on this tape (shared-stop clusters); not proven OOS. |
| TP | UNRESOLVED. |
| Session | By design all RAW timestamps are NY 15–16 UTC. That concentrates the sample; it does not prove the window is wrong. |
| Regime | UNRESOLVED — one win cannot define a regime contrast. |
| Cost | Costs are INCOMPLETE, not a proven cause of the RAW path (RAW is gross). |
| Data | PROVEN as an inference limit (G). Not proven as the generator of the −0.90 R path. |
| Identifiable single cause | PROVEN for a single structural cause — official answer J. |

Optimization supported: **NO**.

## If insufficient

Missing evidence that prevents A, B, and C:

- **Defensible XAUUSD_i M5 tape ≥ 60 calendar days (target 180).** — have `14.88 days` (source: Phase 29; floors from Phase 28.0)
- **≥ 30 independent mechanical events.** — have `6` (source: Phase 31 official event unit; Phase 28.0 floor)
- **Cost completeness AND-gate COMPLETE (symbol binding, economics, provenance, spread, commission, swap, slippage, execution).** — have `0/8 INCOMPLETE` (source: Phase 35 / Phase 27.15)
- **Genuine requested-vs-executed fill sample if claiming executable or live edge.** — have `FILLED n=0 NOT_OBSERVED` (source: Phase 30 FILLED; Phase 35 execution)
- **Chronological OOS with sufficient independent events (not 2.16 days / 3 events).** — have `OOS events=3 expectancy=-0.75` (source: Phase 32)

Do not invent another audit of the same 15-day book because this verdict is inconvenient.

---

## Research decision

- Do **not** optimize production parameters.
- Do **not** change Strategy, RiskGate, execution, sizing, RR, ML, PA lock, or calibration.
- Do **not** start Phase 37 automatically.
- Do **not** re-audit the same 24 dependent RAW rows.
- Production authorization remains **BLOCKED** unless separately and explicitly authorized by the existing production gate (`PHASE27_16_FINAL_VALIDATION_GATE.md`).
- If an operator later continues research: obtain a longer defensible `XAUUSD_i` M5 tape and COMPLETE cost evidence first. Do not search SL/TP/RR/session on this book.

---

## Safety

No live orders, no MT5 attach, no `.env`, no parquet rewrite, no production change.
Phase 37 was **not** started.

# Phase 40 — Recovery / Progress Status

**PHASE** = `40`  
**STATUS** = `INTERRUPTED`  
**REASON** = `INTERNET_CONNECTION_LOST`

This file is an audit of existing local artifacts only.  
Phase 40 was **not** restarted. No scan was rerun. No missing metric was calculated.

Factual local finding: the operator chat was interrupted, and the first collection process was killed. A second local collection process later finished and wrote complete JSON/MD artifacts. `STATUS=INTERRUPTED` is the recovery envelope. On-disk collection status is `COMPLETED`.

---

## 1. COMPLETED

On disk, sections A–R are present in `logs/phase40_full_horizon_validation.json` (`timestamp_utc`: `2026-09-07T21:09:46Z`, artifact `status`: `PASS`).

| Section | Status |
|---|---|
| A. Data verification | COMPLETED |
| B. Strategy immutability verification | COMPLETED |
| C. Full 1291-day RAW scan | COMPLETED |
| D. Mechanical-event analysis | COMPLETED |
| E. Dependence analysis | COMPLETED |
| F. Chronological walk-forward | COMPLETED |
| G. OOS analysis | COMPLETED |
| H. Yearly/quarterly/monthly stability | COMPLETED |
| I. BUY vs SELL analysis | COMPLETED |
| J. Session analysis | COMPLETED |
| K. RAW performance | COMPLETED |
| L. EXECUTABLE/RiskGate analysis | COMPLETED |
| M. Cost sensitivity | COMPLETED |
| N. Monte Carlo/bootstrap | COMPLETED |
| O. Robustness diagnostics | COMPLETED |
| P. 180-day vs full-tape comparison | COMPLETED |
| Q. Final research classification | COMPLETED |
| R. Final blocker matrix | COMPLETED |

Also written before this audit:

- `docs_v2/02_research/PHASE40_FULL_HORIZON_VALIDATION.md`
- `logs/phase40_raw_setups.jsonl` (2847 lines)
- research truth-doc pointers (`CONFIGURATION_TRUTH.md`, `PRODUCTION_RESEARCH_BOUNDARY.md`, `PROJECT_SOURCE_OF_TRUTH.md`, `KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md`)

---

## 2. PARTIALLY_COMPLETED

- Operator/chat delivery of Phase 40 results (session interrupted).
- `logs/phase40_scan_progress.json` is **STALE/INCONSISTENT**:
  - `updated_utc`: `2026-09-07T18:45:27Z`
  - `last_cursor`: `249999`
  - `completed`: `true`
  - `signals`: `1342`
  - `ny_scanned`: `6532`
  - Final JSON/JSONL: `2847` signals, `10932` NY bars.
  - Do **not** resume from this progress file.

---

## 3. NOT_STARTED

- `tests/test_phase40_full_horizon_validation.py` — not run.
- Phase 41 — not started.
- Optimization — not started.
- Trading / production changes — not started.

---

## 4. UNKNOWN

- Exact internet-drop instant inside the operator chat (not recorded in local artifacts).

---

## 5. LAST_SUCCESSFUL_CHECKPOINT

```
LAST_COMPLETED_STEP       = Final Phase 40 artifact write after full-tape analysis (JSON + MD)
LAST_COMPLETED_ARTIFACT   = logs/phase40_full_horizon_validation.json
LAST_COMPLETED_DATA_RANGE = 2023-02-24 11:10:00+00:00 → 2026-09-07 20:10:00+00:00 (250000 bars / 1291.375 days)
LAST_COMPLETED_TIMESTAMP  = 2026-09-07T21:09:46Z
```

Observed processes:

| Process | Started UTC | Ended UTC | Exit | What happened |
|---|---|---|---|---|
| First `run_phase40_collection` | `2026-09-07T18:22:14Z` | `2026-09-07T18:33:15Z` | `4294967295` (killed) | During computation; empty stdout; no artifacts from this process |
| Second `run_phase40_collection` | `2026-09-07T18:34:40Z` | `2026-09-07T21:09:48Z` | `0` | Completed collection, analysis, JSON/MD write |
| Tests | — | — | — | Not started |
| Operator chat | — | — | — | Interrupted; results not delivered |

Interruption happened **during computation** on the first process, and **during operator-session delivery** after the second process had already finished writing artifacts. It did **not** happen during the successful artifact write.

---

## 6. EXISTING_RESULTS

All values below already exist in `logs/phase40_full_horizon_validation.json`. Nothing new was computed.

### A. Data

- Tape: `data/XAUUSD_i_5m_phase38.parquet`
- Bars loaded: `250000`
- Start: `2023-02-24 11:10:00+00:00`
- End: `2026-09-07 20:10:00+00:00`
- Days: `1291.375`
- Fingerprint: `222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5`
- Duplicates: `0`
- Malformed OHLC: `0`
- Impossible OHLC: `0`
- Zero volume: `5`
- Gaps: `EXPECTED_SESSION_GAP=0`, `EXPECTED_WEEKEND_GAP=181`, `BROKER_ROLLOVER_GAP=701`, `UNKNOWN_GAP=52`
- Source modified / bars repaired / fabricated: `false`

### B. Strategy immutability

- Class: `PriceActionStrategy`
- Preset: `gold_ny_sweep`
- Symbol: `XAUUSD_i`
- `code_wins`: `true`
- `parameters_changed`: `false`
- `logic_hash`: `b0295eb95d46510d`
- `deterministic_fingerprint`: `9aa7e457b57e905b3cf339ee300f37e680137454c6e7cc055cd5d37b60ffee3a`

### C. Full-tape RAW scan

- Completed: `true`
- Horizon shortened / sampled / random sample: `false`
- `resumed`: `true`
- `reused_checkpoint`: `false`
- NY bars scanned: `10932`
- RAW signals: `2847`
- BUY: `1063`
- SELL: `1784`
- WAIT: `8648`
- JSONL lines on disk: `2847`

### D–E. Events / dependence

- Mechanical events: `420`
- Signals/event mean: `6.7785714285714285`
- Singleton events: `40`
- Clustered events: `380`
- Clustered signals: `2807`
- Same-event reentries: `2427`
- Overlapping holds: `2785`
- Independence claimed: `false`
- Event floor >=30: `true`

Event-level RAW: trades `419`, WR `0.288783`, expectancy `0.04866R`, PF `1.068418`, net `20.388433R`, max DD `38.249969R`

### F–G. Walk-forward / OOS (predeclared 60/20/20)

| Fold | Bars | Days | Signals | Events | Signal WR | Signal Exp R | Signal PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| TRAIN | 150000 | 774.8993 | 2046 | 283 | 0.327957 | -0.032878 | 0.951077 |
| VALIDATION | 50000 | 257.2292 | 434 | 74 | 0.308756 | 0.062192 | 1.089971 |
| OOS | 50000 | 259.2396 | 367 | 63 | 0.244382 | 0.250355 | 1.331325 |

OOS sufficiency: `SUFFICIENT` (`events=63`, `months=10`, `weeks=32`). This is an event-count floor, not a validity claim.

OOS event-level: WR `0.225806`, expectancy `0.418211R`, PF `1.540189`, max DD `26.981373R`

### H. Stability (existing yearly)

| Year | Signals | Events | WR | Exp R | PF | Max DD R |
|---|---:|---:|---:|---:|---:|---:|
| 2023 | 556 | 121 | 0.31295 | -0.118647 | 0.82731 | 108.644398 |
| 2024 | 1150 | 128 | 0.308696 | -0.077283 | 0.888206 | 207.049992 |
| 2025 | 775 | 109 | 0.357419 | 0.150563 | 1.234309 | 109.0 |
| 2026 | 366 | 62 | 0.242254 | 0.245088 | 1.323443 | 154.924557 |

Quarterly/monthly/regime arrays exist in JSON (`stability.monthly` = 44 rows). Not re-listed here.

### I. BUY vs SELL

| Book | Side | Setups | WR | Exp R | PF | Net R | Max DD R |
|---|---|---:|---:|---:|---:|---:|---:|
| signal | BUY | 1063 | 0.324144 | 0.017036 | 1.025207 | 17.922131 | 87.138827 |
| signal | SELL | 1784 | 0.308857 | 0.017336 | 1.025082 | 30.926539 | 228.427107 |
| event | BUY | 167 | 0.295181 | -0.00316 | 0.995517 | -0.524568 | 18.026111 |
| event | SELL | 253 | 0.284585 | 0.08266 | 1.115541 | 20.913001 | 29.600943 |

### J. Session

- Production session: `NY 15–16 UTC (unchanged)`
- `hour_utc_counts`: `{15: 2847}`
- Session boundaries were not optimized.

### K. RAW performance

- Trades: `2836` (`open=11`)
- Wins/losses: `892` / `1944`
- WR: `0.314528`
- Expectancy: `0.017224R`
- PF: `1.025128`
- Net: `48.84867R`
- Max DD: `293.59309R`
- Max consecutive losses: `91`
- Label: `RAW_THEORETICAL`
- Not cost-adjusted.

### L. EXECUTABLE / RiskGate

- Ran: `true`
- Candidates: `2847`
- Allowed: `82`
- Rejected: `2765`
- Attribution: `META=1790`, `ATR=638`, `LOT=265`, `OTHER=72`, `ALLOWED=82`
- Simulated fills: `0`
- Fills fabricated: `false`
- Status: `EXECUTABLE_BLOCKED_BY_UNKNOWN_COMMISSION`
- Gates unchanged: risk/lot/meta/atr/spread/news/cooldown/max_trades_per_day all `true`

### M. Cost sensitivity (MODELED, commission UNKNOWN)

| Scenario | Spread pips | Slip pips | Signal Exp R | Event Exp R |
|---|---:|---:|---:|---:|
| RAW_NO_COST | 0.0 | 0.0 | 0.017224495765056923 | 0.04865974435740537 |
| MODELED_1X | 2.5 | 0.8 | -0.060787126794689415 | -0.05040365947388998 |
| MODELED_2X | 5.0 | 1.6 | -0.13879874935443529 | -0.14946706330518544 |
| MODELED_3X | 7.5 | 2.4 | -0.2168103719141815 | -0.24853046713648108 |

Cost AND-gate: `0/8`, `cost_ready_for_validation=false`, `INCOMPLETE`.

### N. Bootstrap (descriptive, event-level, 2000 paths, 419 events)

- Final R median / p5 / p95: `16.526` / `-54.731` / `100.070`
- Max DD median: `40.333R`
- Expectancy median / p5 / p95: `0.039442` / `-0.130624` / `0.238830`
- PF median: `1.055571`
- WR median: `0.288783`
- `prob_final_R_negative`: `0.35`
- `prob_dd_ge_20R`: `0.967`
- Inferential/significance claimed: `false`

### O. Robustness (diagnostics only; not selected)

- Official signal/event Exp R: `0.017224` / `0.04866`
- Next-bar open signal Exp R: `0.017289686259706838`
- SL wider 5%: `-0.005647423489943481`
- RR 1.4 / 1.6: `-0.06680716543730188` / `-0.06451159522136396`
- `selected_as_preferred`: `false`
- Production unchanged: `true`

### P. 180-day vs full tape

| Window | Signals | Events | Signal WR | Signal Exp R | Signal PF |
|---|---:|---:|---:|---:|---:|
| Full tape | 2847 | 420 | 0.314528 | 0.017224 | 1.025128 |
| Latest 180d of full scan | 259 | 44 | 0.141129 | -0.467633 | 0.455526 |
| Phase 38 isolated 180d | 249 | 43 | NOT_RECORDED as WR | -0.5910847620405503 | NOT_RECORDED |

`representative=false`, `materially_different=true`, more favorable window: `full_tape`.

### Q. Classification

- Strategy RAW evidence: `B` MIXED / CONDITIONAL
- Broker-realistic evidence: `D` INSUFFICIENT EVIDENCE
- Overall: `B`
- `profitability_verdict`: `NOT_ISSUED`
- `FINAL_GATE`: `BLOCKED`

### R. Blocker matrix

Already recorded. Horizon/events/OOS/statistical sufficiency = `SUFFICIENT` or `MET_PREFERRED`. Cost AND-gate still `INCOMPLETE` (`0/8`). Commission/swap `UNKNOWN`. Bid/Ask unavailable. Symbol binding `NOT_PROVEN`.

---

## 7. TEST_STATUS

- Tests passed: none recorded
- Tests failed: none recorded
- Tests interrupted: none recorded
- Tests not run:
  - `test_frozen_tape_full_scan_and_no_silent_map`
  - `test_safety_no_env_no_phase_41`

Evidence: no Phase 40 pytest command in terminals; `.pytest_cache` has no `test_phase40_full_horizon` nodeid.

`tests/test_phase40.py` is a July 2026 ML leftover and is not this validation run.

---

## 8. DATA_INTEGRITY

Verified from existing metadata/mtimes only. Hash was **not** recomputed.

- `data/XAUUSD_i_5m_phase38.parquet`
  - mtime UTC: `2026-09-07T17:10:12Z` (before first Phase 40 start `18:22:14Z`)
  - size: `7018831`
  - artifact `source_modified`: `false`
  - artifact `datasets_changed`: `false`
- Frozen Phase 28 `data/XAUUSD_i_5m.parquet`
  - mtime UTC: `2026-08-28T17:26:53Z`
  - recorded fingerprint: `ab3e25bab0c6d6689d6654317264cc7774e1b49f88df907a3ea1bd1ade313ed5`
  - artifact `phase28_m5_unchanged`: `true`

---

## 9. PRODUCTION_SAFETY

From existing Phase 40 artifact/logs (no action taken now):

| Action | Recorded |
|---|---|
| Started MT5 | `false` (no initialize/attach in Phase 40 source or terminals) |
| Sent orders | `false` |
| Started bot | `false` |
| Started daemon | `false` |
| Changed production configuration | `false` / `NONE` |
| Changed strategy parameters | `false` |
| Changed RiskGate | `false` |
| Read `.env` | `false` |
| Phase 41 started | `false` |
| Optimized | `false` |

---

## 10. EXACT_NEXT_RESUMABLE_STEP

**Do not restart Phase 40 collection.**  
**Do not rerun the full-tape scan.**  
**Do not resume from `logs/phase40_scan_progress.json`.**

If Phase 40 is continued at all, the only remaining local step is optional tests:

```text
python -m pytest tests/test_phase40_full_horizon_validation.py -q --tb=short
```

`setUpModule` skips `run_phase40_collection` when the existing JSON shows `completed=true`, `250000` rows, and the JSONL exists.

Do not start Phase 41. Do not optimize. Do not trade. Do not modify production.

STOP.

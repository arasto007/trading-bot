# Phase 38 — Intelligent Evidence Acquisition

**STATUS:** `PASS`
**Class:** RESEARCH / DATA ACQUISITION ONLY
**MT5 launched by this phase:** `False`
**Real account interaction:** `READ_ONLY`
**Frozen dataset changed:** `False`
**Production changes:** `NONE`
**FINAL_GATE:** `BLOCKED`
**BLOCKER_REMAINING:** `YES`

STOP AFTER PHASE 38. DO NOT START PHASE 39.
DO NOT OPTIMIZE. DO NOT TRADE. DO NOT CHANGE PRODUCTION.

This phase does **not** produce a strategy profitability verdict. Phase 36 `INSUFFICIENT_EVIDENCE` is reduced only where new evidence actually landed.

---

## 1. What was discovered

Installed=True; running_before=True; selected=C:\Program Files\MetaTrader 5\terminal64.exe; launch={'launched_by_phase': False, 'already_running': True, 'ok': True, 'exe': 'C:\\Program Files\\MetaTrader 5\\terminal64.exe', 'error': None, 'wait_sec': 0}; attach=ATTACHED.

- Selected terminal: LiteFinance-MT5-Live at `C:\Program Files\MetaTrader 5\terminal64.exe`
- FIBO Group data dir observed and **not launched** (other broker)
- Logical `XAUUSD` tapes exist on disk and remain **BLOCKED** (`MISSING_EXPLICIT_MAP`, EV-EQ-01 `NOT_PROVEN`)

## 2. What evidence was acquired

M5 days=1291.3750 rows=250000; M15=OBSERVED; M1=SKIPPED_RESOURCE_BOUND; ticks=SKIPPED_RESOURCE_BOUND; bidask=NOT_OBSERVED; history deals=54 orders=52 pairs=0.

M5 research tape: `data/XAUUSD_i_5m_phase38.parquet`  
Rows: `250000` · Days: `1291.375` · Start: `2023-02-24 11:10:00+00:00` · End: `2026-09-07 20:10:00+00:00`  
Cap hit (250k M5 bars): `True` — actual broker history may be longer  
Duplicates: `0` · Impossible OHLC: `0` · Zero volume: `5`  
Gaps: weekend `181` · rollover `701` · unknown `52`  
SHA-256 file: `5c3c636079fc01fda444eac280a1a0933e20750c9c397e64bfeb550ef6bc1b62`  
SHA-256 content: `222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5`

Frozen Phase 28 `data/XAUUSD_i_5m.parquet` fingerprint unchanged: `True`

## 3. What remains missing

M5 preferred 180d horizon met on research tape; event floor met (43>=30); cost AND-gate not COMPLETE; EV-EQ-01 NOT_PROVEN; commission not VERIFIED_SCHEDULE; slippage MODELED; requested/fill pairs 0. RAW expectancy is theoretical and is not a profitability verdict.

## 4. Terminal / account (read-only)

Status: `ATTACHED`  
Launched by Phase 38: `False` (already running: `True`)  
Broker / server / env: `LiteFinance Global LLC` / `LiteFinance-MT5-Live` / `REAL`  
Open positions / orders observed, not touched: `0` / `0`

## 5. Symbols

`XAUUSD_i` existence: `YES`  
digits `2` · point `0.01` · contract `100.0` · tick `0.01`  
swap_long `-89.136` · swap_short `3.45` · rollover3days `3`  
bid `4412.17` · ask `4412.59` · quote `2026-09-07T20:29:53Z` · description `Gold vs US Dollar`

`XAUUSD` existence: `NOT_OBSERVED_ON_THIS_TERMINAL`

Absence is **terminal-scoped**. Do not conclude XAUUSD does not exist broker-wide. EV-EQ-01 remains **NOT_PROVEN**. `dataset_symbol_map` is empty. No silent mapping.

## 6. Bid/Ask / spread

Phase 38 ticks: **NOT_OBSERVED** (`SKIPPED_RESOURCE_BOUND` — gold `copy_ticks_range` hung in Phase 37/38 reconnaissance).  
Live bid/ask on attach is a **current quote**, not a historical Bid/Ask tape.  
Prior sidecar `logs/phase27_26_xauusd_i_m5_bidask.parquet` remains OBSERVED for ~15d only.  
Production parquet remains **PROXY**. OHLC-derived spread is **PROXY**, not observed Bid/Ask.

## 7. Commission / swap / slippage / execution

- Commission: `{'status': 'UNKNOWN', 'verified_schedule': False, 'all_deal_zeros': True, 'zero_is_not_verified': True, 'gold_deals': 30}`
- Swap: `{'classification': 'BROKER_RATE_ONLY', 'current_swap_long': -89.136, 'current_swap_short': 3.45, 'historical': 'UNKNOWN', 'deal_zeros_prove_historical_zero': False}` — current broker rates only; historical series **UNKNOWN**. Short-hold zeros would not prove historical swap is zero.
- Slippage: `{'status': 'MODELED', 'genuine_requested_vs_executed_pairs': 0, 'mt5_deviation_is_realized_slippage': False, 'price_open_is_requested': False}` — `deal.price` / `price_open` / deviation are **not** requested price.
- Execution: `{'grade': 'DEAL_FILL_TAPE_ONLY', 'deals': 54, 'orders': 52, 'positions_touched': False, 'orders_modified': False}`

## 8. Cost completeness AND-gate (not weakened)

Ready: `False`  
Classification: `INCOMPLETE` · complete `0/8`  
Gate weakened: `False`

Components: symbol_binding `BLOCKED` · economics `PARTIAL` · provenance `PARTIAL` · spread `BLOCKED` · commission `BLOCKED` · swap `UNKNOWN` · slippage `UNKNOWN` · execution `UNKNOWN`

## 9. Events / unchanged-strategy research scan

Scan ran: `True` · window `180.0` days of the phase38 tape (full tape `1291.375` days)  
RAW setups: `249` · mechanical events: `43` · classification: `SUFFICIENT`  
Event definition (unchanged): `(UTC date, asian_high, asian_low, side)`  
Independence manufactured: `False`

RAW book: n=`249` wins=`25` losses=`213` expectancy_R=`-0.5910847620405503` (theoretical SL/TP, not cost-adjusted)

EXECUTABLE book: ran=`True` allowed=`0` rejected=`249` fills=`0`  
RAW and EXECUTABLE are **not mixed**. Zero fills is not a no-edge proof (commission UNKNOWN fail-closed).

This is **not** a production strategy verdict.

## 10. Comparison vs Phase 36 blockers

| Requirement | Previous | Phase38 | Improvement | Status |
|---|---|---|---|---|
| M5 horizon | 14.88d frozen | 1291.38d | YES | MET_PREFERRED |
| independent events | 6 | 43 | YES | SUFFICIENT |
| M15 | NOT_OBSERVED canonical | OBSERVED | YES | OBSERVED |
| Bid/Ask | 27.26 sidecar OBSERVED ~15d; production PROXY | NOT_OBSERVED | NO | NOT_OBSERVED |
| spread | PROXY / BLOCKED | BLOCKED | NO | BLOCKED |
| commission | BLOCKED / UNKNOWN | BLOCKED | NO | UNKNOWN |
| swap | UNKNOWN historical / BROKER_RATE_ONLY current | BROKER_RATE_ONLY | PARTIAL | BROKER_RATE_ONLY |
| slippage | MODELED / 0 pairs | 0 pairs | NO | MODELED |
| execution | DEAL_FILL_TAPE_ONLY | DEAL_FILL_TAPE_ONLY | NO | DEAL_FILL_TAPE_ONLY |
| symbol binding | EV-EQ-01 NOT_PROVEN | NOT_PROVEN | NO | NOT_PROVEN |
| cost completeness | INCOMPLETE 0/8 | 0/8 INCOMPLETE | NO | INCOMPLETE |
| statistical sufficiency | INSUFFICIENT_SAMPLE | EVENT_SAMPLE_MET (n>=30 mechanical events; not a significance test) | YES | EVENT_SAMPLE_MET |

**BLOCKER_REMAINING:** `YES`

## 11. Recommended next phase

Phase 39 candidate (operator-initiated only): research walk-forward / statistical re-evaluation on the phase38 XAUUSD_i tape. Cost completeness remains INCOMPLETE. Do not start Phase 39 automatically. Do not optimize. Do not trade.

## Safety

No orders, no `.env`, no frozen parquet rewrite, no bot/daemon, no optimization, no ML activation.
Phase 39 was **not** started.

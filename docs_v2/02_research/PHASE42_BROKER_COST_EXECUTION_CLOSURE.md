# Phase 42 — Broker Cost, Execution Telemetry, Bid/Ask, Swap, Symbol Mapping

**STATUS:** `PASS`
**Class:** RESEARCH / AUDIT ONLY
**FINAL_GATE:** `BLOCKED`
**EXECUTABLE_BACKTEST_READY:** `False`
**OVERALL_VERDICT:** `INSUFFICIENT_EVIDENCE`
**PHASE40_RESCAN:** `NO`
**MT5 launched by phase:** `False`
**Fresh attach:** `True`

STOP AFTER PHASE 42. DO NOT START PHASE 43.
DO NOT OPTIMIZE. DO NOT TRADE. DO NOT CHANGE PRODUCTION.

This phase does **not** rewrite Phase 28/39/40/41 conclusions. It adds a new evidence layer.

## Executive verdict

- BROKER_EVIDENCE: `PARTIAL`
- COST_EVIDENCE: `INCOMPLETE`
- EXECUTION_EVIDENCE: `PARTIAL`
- HISTORICAL_SPREAD: `PARTIAL`
- COMMISSION: `UNKNOWN`
- SWAP: `BROKER_RATE_ONLY`
- SLIPPAGE: `MODELED`
- SYMBOL_MAPPING: `NOT_PROVEN`
- EXECUTABLE_READINESS: `BLOCKED`
- EXECUTABLE_RESULT: `NOT_RUN`
- FINAL_GATE: `BLOCKED`
- OVERALL: `INSUFFICIENT_EVIDENCE`
- Profitability: `NOT_ISSUED`

## Broker / symbol (Part A / B)

- Broker: `LiteFinance Global LLC` — label OBSERVED if freshly attached, else REUSED_PHASE39
- Server: `LiteFinance-MT5-Live`
- Environment: `REAL`
- Currency: `USD`
- Balance/equity (read-only): `0.98` / `0.98`
- CURRENT_REAL_SYMBOL: `XAUUSD_i`
- EXPECTED_USER_REAL_SYMBOL: `XAUUSD`
- CURRENT_TERMINAL_XAUUSD: `NOT_OBSERVED`
- SYMBOL_MAPPING: `NOT_PROVEN`

XAUUSD absence on this terminal is **not** broker-wide absence.

| symbol | observed | account | server | contract | tick_size | tick_value | vol_min | vol_step | exec | fill | swap_long | swap_short | timestamp |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| XAUUSD_i | YES | REAL | LiteFinance-MT5-Live | 100.0 | 0.01 | 1.0 | 0.01 | 0.01 | 2 | 1 | -89.136 | 3.45 | 2026-09-08T01:36:48Z |
| XAUUSD | NOT_OBSERVED_ON_THIS_TERMINAL | REAL | LiteFinance-MT5-Live | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |

Gold-like catalog names (filtered; Goldman-style equity names excluded):

- `XAUUSD_i` — Gold vs US Dollar (visible=True)
- `XAUPUSD_cl` — Perpetual Gold Contract vs US Dollar (visible=False)

## EV-EQ-01 (Part H)

CODE definition: `evaluate_ev_eq_01()` in `tradingbot/backtest/phase27_9_real_broker_evidence.py`.
Requires REAL environment **and both** `XAUUSD` and `XAUUSD_i` collected, then field-by-field `build_equivalence_audit`.
If one symbol is missing → `NOT_PROVEN`. Absence on this terminal ≠ broker-wide absence.

- Status: `NOT_PROVEN`
- Both symbols present: `False`
- Rationale: `both symbols were not collected`
- Inferred: `False`

Current evidence does **not** satisfy EV-EQ-01. Missing: observe `XAUUSD` on this REAL catalog or an official account-applicable equivalence statement.

## Commission (Part C)

- Status: `UNKNOWN`
- Classification: `OBSERVED_ZERO_NOT_PROVEN`
- Verified schedule: `False`
- Account product type: `UNKNOWN`
- XAUUSD_i deals this inspect: `30`
- All observed zeros: `True`

Account product/tier (ECN vs CLASSIC vs CENT) is UNKNOWN. Official ECN precious-metals $5/lot is GENERIC_SUPPORTING. Observed deal commission=0 is not a VERIFIED_SCHEDULE. Classic/Cent 'commission embedded in spread' cannot be applied without product type.

Official LiteFinance ECN page (2026-09-08 fetch): precious metals $5/lot on MT4/MT5, charged at open.
Grade remains OFFICIAL_BROKER_GENERAL_DOCUMENT / GENERIC_SUPPORTING because this account's product/tier is UNKNOWN.
Do not treat historical deal commission=0 as policy=0.

## Execution history / request-fill / slippage (Parts D / E)

- History status: `OBSERVED`
- Deals / orders / XAUUSD_i deals: `54` / `52` / `30`
- REQUEST_FILL_PAIRS: `0`
- Journal XAUUSD_i pairs: `0`
- Journal logical XAUUSD live pairs (not used): `17`
- SLIPPAGE_EVIDENCE: `UNKNOWN`
- SLIPPAGE_POLICY: `MODELED` (model unchanged: ~0.8 pips + session multiplier)

price_open, deal.price, deviation, and SL/TP are not request/fill evidence.

## Historical Bid/Ask (Part F)

- SPREAD_POLICY: `PROXY / PARTIAL`
- Evaluation tape Bid/Ask columns: `False`
- Tick probe: `OBSERVED` rows=`400` (bounded 2 minutes / 400 ticks; does not cover the 1291-day tape)

Existing sidecars were read, not overwritten. Canonical Phase 28/38 M5 parquets were not modified.

## Swap (Part G)

- CURRENT_SWAP: `OBSERVED` long=`-89.136` short=`3.45` rollover3days=`3` (Wednesday)
- HISTORICAL_SWAP: `UNKNOWN`
- Resolved Phase 40 trades: `2836`
- Share ≥8h: `0.14633286318758815`
- Share ≥9h (possible rollover): `0.14492242595204513`
- Wednesday-touch share: `0.26198871650211564`

MODELED sensitivity (not observed broker cost): one overnight on 1 lot vs median SL.
- Long drag if overnight share: `-0.018806632006786277` R
- Short credit if overnight share: `0.0007279088182486611` R

## Cost gates / executable contract (Parts I / J / L)

- cost_ready_gate_count: `0` / `8`
- Readiness: `BLOCKED`

Modeled evidence is never PASS. The existing backtest engine was not changed.
Executable evaluation was not run because commission remains UNKNOWN.

## Reconstruction (Parts K / M / N)

- Status: `BLOCKED_FOR_EXECUTABLE`
- Commission applied: `False`
- Signals regenerated: `False`
- Frozen Phase 40 fingerprint: `222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5`
- RAW expectancy (unchanged): `0.017224` R

No executable RAW vs EXECUTABLE difference table is issued. Event-level executable analysis is not available.

## Stop

STOP AFTER PHASE 42.
DO NOT START PHASE 43.

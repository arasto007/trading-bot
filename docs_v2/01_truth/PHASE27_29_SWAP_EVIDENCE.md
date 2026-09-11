# Phase 27.29 — Real Account Swap Evidence Closure

**Status:** PASS  
**Evidence grade:** `CURRENT_BROKER_RATE_ONLY`  
**Final classification:** `CURRENT_BROKER_RATE_ONLY`  
**Artifact:** `logs/phase27_29_swap_evidence.json`  
**Timestamp UTC:** `2026-09-10T07:31:08Z`

Read-only. Phase 27.13 / 27.24 artifacts were not overwritten. Production parquet was not rewritten.
`BROKER_RATE_ONLY` remains a policy gate: current rates are not a historical series.

## Real account

| Field | Value |
|---|---|
| account type | `REAL` |
| broker | `LiteFinance Global LLC` |
| server | `LiteFinance-MT5-Live` |
| terminal build | `6182` |
| symbol | `XAUUSD_i` |
| collection | `COLLECTED` |

## Current broker swap

| Field | Value |
|---|---|
| swap_long | `-89.136` |
| swap_short | `3.45` |
| rollover day | `Wednesday` |
| swap mode | `POINTS` |
| units | `POINTS` |
| timestamp | `2026-09-10T07:31:08Z` |
| historical rollover schedule | `UNKNOWN` |

Current rates are **not** historical rates.

## Deal forensics

| Field | Value |
|---|---|
| deals | `2` |
| overnight | `0` |
| rollover-crossing | `0` |
| zero swap | `2` |
| nonzero swap | `0` |
| total realized swap | `0.0` |
| range | `None` → `None` |

`HISTORICAL_SWAP_RATE_NOT_IDENTIFIABLE_FROM_DEALS` unless overnight/rollover samples exist. Realized zero ≠ historical zero.

## Historical rate

identifiable: `False`. status: `NOT_IDENTIFIABLE`.  
applicability: `False`. effective date: `UNKNOWN`.

## Classification

Grade `CURRENT_BROKER_RATE_ONLY`. Historical swap proven: `False`.  
COMPLETE policy satisfied: `False`. Policy status: `BROKER_RATE_ONLY`.

## Implementation

`BROKER_RATE_ONLY` cannot silently become historical. Default `BacktestConfig.swap_status` remains `UNKNOWN`.

## FINAL_GATE

swap_status_before: `BROKER_RATE_ONLY`  
swap_status_after: `BROKER_RATE_ONLY`  
COMPLETE_COSTS_REQUIRED remains enforced. FINAL_GATE remains `BLOCKED`.

## Next

STOP after Phase 27.29.

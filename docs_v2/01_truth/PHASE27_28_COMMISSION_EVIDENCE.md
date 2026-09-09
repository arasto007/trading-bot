# Phase 27.28 — Real Account Commission Evidence Closure

**Status:** PASS  
**Evidence grade:** `OBSERVED_ZERO_NOT_PROVEN`  
**Final classification:** `OBSERVED_ZERO_NOT_PROVEN`  
**Artifact:** `logs/phase27_28_commission_evidence.json`  
**Timestamp UTC:** `2026-09-06T08:09:14Z`

Read-only. Phase 27.22 artifact was not overwritten. Production parquet was not rewritten.
`VERIFIED_SCHEDULE` remains a policy gate, not current verification.

## Real account

| Field | Value |
|---|---|
| account type | `REAL` |
| broker | `LiteFinance Global LLC` |
| server | `LiteFinance-MT5-Live` |
| terminal build | `6182` |
| symbol | `XAUUSD_i` |
| account_product_type | **`UNKNOWN`** |

Product/tier was not inferred from zeros, symbol, broker name, leverage, balance, or trade history.

## Deal evidence

| Field | Value |
|---|---|
| deals | `50` |
| zero commission | `50` |
| nonzero commission | `0` |
| total commission | `0.0` |
| range | `2026-06-19T15:48:03+00:00` → `2026-08-12T13:41:03+00:00` |
| distribution | `{'0.0000': 50}` |

Limitation: an all-zero realized tape is **not** `commission schedule = 0`. It does not prove product tier, basis, effective date, instrument applicability, or whether commission is embedded in spread/markup.

## Schedule

| Field | Value |
|---|---|
| schedule found | `False` |
| source | `none — public pages supporting only; no account schedule` |
| class | `GENERIC_SUPPORTING` |
| basis | `UNKNOWN` |
| rate | `None` |
| currency | `USD` |
| effective date | `UNKNOWN` |
| applicability | `False` |

Public LiteFinance ECN/Classic pages remain `GENERIC_SUPPORTING`. They are not this account's schedule.

## Classification

Grade `OBSERVED_ZERO_NOT_PROVEN` → `OBSERVED_ZERO_NOT_PROVEN`.  
`VERIFIED_SCHEDULE` satisfied: `False`.  
Policy status: `BLOCKED`.

## Implementation

UNKNOWN commission cannot produce COMPLETE cost status.  
Observed zero cannot silently become ZERO.  
Default `BacktestConfig.commission_status` remains `UNKNOWN`.

## FINAL_GATE

commission_status_before: `OBSERVED_ZERO_NOT_PROVEN`  
commission_status_after: `OBSERVED_ZERO_NOT_PROVEN`  
COMPLETE_COSTS_REQUIRED remains enforced. FINAL_GATE remains `BLOCKED`.

## Next

STOP after Phase 27.28.

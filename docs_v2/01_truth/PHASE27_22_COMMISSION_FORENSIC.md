# Phase 27.22 — Commission & Account-Product Forensic Evidence

**Status:** PASS  
**Classification:** `OBSERVED_ZERO_NOT_PROVEN`  
**Artifact:** `logs/phase27_22_commission_forensic.json`  
**Collection timestamp UTC:** `2026-09-06T07:25:06Z`

Read-only. No MT5 start/restart, orders, `.env`, or production behavior changes.

## Account product evidence

This session attach: `REAL_COLLECTED`.

| Field | This session | Prior Real (27.17) |
|---|---|---|
| trade mode | `2` → `REAL` | `2` → `REAL` |
| broker | `LiteFinance Global LLC` | `LiteFinance Global LLC` |
| server | `LiteFinance-MT5-Live` | `LiteFinance-MT5-Live` |
| currency | `USD` | `USD` |
| leverage | `100` | `100` |
| margin mode | `2` | `2` |
| terminal build | `6182` | n/a |
| **account_product_type** | **`UNKNOWN`** | `UNKNOWN` |

Identifier fields scanned: `trade_mode, currency, leverage, margin_mode, limit_orders, trade_allowed`.  
Product was **not** inferred from zero commission, symbol, broker name, balance, or trade history.

## Commission evidence

| Field | Value |
|---|---|
| gold deals | `50` |
| commission samples | `50` |
| observed zero | `50` |
| observed nonzero | `0` |
| distribution | `{'0.0000': 50}` |
| symbols | `XAUUSD_i` |
| date range | `2026-06-19T15:48:03+00:00` → `2026-08-12T13:41:03+00:00` |
| tape class | **`OBSERVED_ZERO_NOT_PROVEN`** |

`BacktestConfig.commission_per_lot=0.0` was not converted to `ZERO`.

## Public documentation

LiteFinance ECN precious-metals **$5/lot** and CLASSIC/CENT markup pages remain **supporting only**. They are not this account's schedule while product type is UNKNOWN.

## Why not VERIFIED_SCHEDULE

Account product/tier is not established from MT5-visible identifiers. Public ECN/Classic pages remain supporting only. 50 gold zeros remain OBSERVED_ZERO_NOT_PROVEN and do not prove ZERO.

Final classification (exactly one): **`OBSERVED_ZERO_NOT_PROVEN`**.

## Operator action

**Required:** Confirm LiteFinance account product/tier (ECN vs CLASSIC vs CENT) from the client cabinet or contract, then supply an account-applicable schedule.

## Production

**BLOCKED.** COMPLETE_COSTS_REQUIRED was not weakened. FINAL_GATE remains `BLOCKED`. Phase 27.23+ not started.

## Next

STOP after Phase 27.22.

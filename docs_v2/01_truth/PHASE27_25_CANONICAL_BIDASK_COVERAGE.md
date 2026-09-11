# Phase 27.25 — Targeted Canonical Dataset Bid/Ask Coverage

**Status:** PASS  
**Classification:** `PARTIAL_CANONICAL_COVERAGE`  
**historical_spread:** `PARTIAL`  
**Artifact:** `logs/phase27_25_canonical_bidask_coverage.json`  
**Collection timestamp UTC:** `2026-09-10T07:30:48Z`

Read-only. No MT5 start/restart, orders, `symbol_select`, `.env`, or production parquet overwrite.

## Canonical dataset

| Field | Value |
|---|---|
| path | `data/XAUUSD_i_5m.parquet` |
| symbol | `XAUUSD_i` |
| timeframe | `M5` |
| start UTC | `2026-08-13T20:20:00Z` |
| end UTC | `2026-08-28T17:25:00Z` |
| rows | `3000` |
| timezone | `UTC` |
| fingerprint | `ab3e25bab0c6d6689d6654317264cc7774e1b49f88df907a3ea1bd1ade313ed5` |
| spread mode | `PROXY` |
| provenance | `XAUUSD_i label match; OBSERVED_BROKER_EVIDENCE economics; spread PROXY; EV-EQ-01 NOT_PROVEN for bare XAUUSD` |

## Historical Bid/Ask obtained

| Field | Value |
|---|---|
| ticks | `1862068` |
| M5 evidence bars | `1812` |
| evidence start | `2026-08-13T20:20:00Z` |
| evidence end | `2026-08-24T10:25:00Z` |
| fingerprint | `5fd2e0bf8b0b247fd42ba275e4abe8abc4fca3fadd4032caf1cd82827e980c68` |
| logs tape | `logs/phase27_25_xauusd_i_m5_bidask.parquet` |

Requested range = actual dataset range (plus one M5 bar to close the last interval). Not a generic 7-day window.

## Coverage matrix

| Field | Value |
|---|---|
| covered M5 bars | `1680` / `3000` |
| coverage percent | `56.0` |
| overlap | `2026-08-13T20:20:00Z` → `2026-08-24T10:25:00Z` |
| uncovered intervals | `12` |
| largest gap | `{'start_utc': '2026-08-24T22:00:00Z', 'end_utc': '2026-08-25T20:55:00Z', 'bars': 276, 'duration_hours': 22.917}` |
| fully covered | `False` |

## A/B/C/D

| Class | Result |
|---|---|
| A. Historical Bid/Ask exists | **PROVEN** |
| B. Canonical dataset partially covered | **PROVEN** |
| C. Canonical dataset fully covered | **BLOCKED** |
| D. Production parquet updated | **False** |

Production spread mode remains `PROXY`. PROXY was not converted to DATASET.

## Other costs

Not collected. Commission, swap, slippage, and execution remain separate blockers.

## Production

**BLOCKED.** COMPLETE_COSTS_REQUIRED was not weakened. FINAL_GATE remains `BLOCKED`. Phase 27.26+ not started.

## Next

STOP after Phase 27.25.

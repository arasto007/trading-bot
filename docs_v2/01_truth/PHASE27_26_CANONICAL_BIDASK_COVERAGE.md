# Phase 27.26 — Complete Canonical XAUUSD_i M5 Bid/Ask Coverage

**Status:** PASS  
**Classification:** `PARTIAL_CANONICAL_COVERAGE`  
**historical_spread:** `PARTIAL`  
**Artifact:** `logs/phase27_26_canonical_bidask_coverage.json`  
**Collection timestamp UTC:** `2026-09-06T07:51:09Z`

Read-only. Phase 27.25 tape was not overwritten. Production parquet was not rewritten.

## Dataset

| Field | Value |
|---|---|
| path | `data/XAUUSD_i_5m.parquet` |
| symbol | `XAUUSD_i` |
| timeframe | `M5` |
| rows | `3000` |
| start UTC | `2026-08-13T20:20:00Z` |
| end UTC | `2026-08-28T17:25:00Z` |
| fingerprint before | `ab3e25bab0c6d6689d6654317264cc7774e1b49f88df907a3ea1bd1ade313ed5` |
| fingerprint after | `ab3e25bab0c6d6689d6654317264cc7774e1b49f88df907a3ea1bd1ade313ed5` |

## Evidence

| Field | Value |
|---|---|
| ticks | `3125805` |
| invalid | `0` |
| evidence range | `2026-08-13T20:20:00Z` → `2026-08-28T17:25:00Z` |
| covered bars | `2820` / `3000` |
| coverage % | `94.0` |
| fully covered | `False` |
| largest gap | `{'start_utc': '2026-08-16T22:05:00Z', 'end_utc': '2026-08-17T01:00:00Z', 'bars': 36, 'duration_hours': 2.917, 'kind': 'mixed_or_session_break'}` |
| stop reason | `None` |
| existing 27.25 used | `True` |

## Historical spread

`PARTIAL`. PROXY remains on the production parquet. COMPLETE_COSTS_REQUIRED was not weakened. FINAL_GATE remains `BLOCKED`.

## Immutability

Production parquet changed: `False`.  
27.25 tape preserved: `True`.

## Remaining uncovered intervals (180 bars)

Daily UTC rollover (~00:00–00:55, 12 bars each, `technical_or_unavailable`):
2026-08-14, 18, 19, 20, 21, 25, 26, 27, 28.

Sunday session-break (`mixed_or_session_break`, 36 bars each):
- 2026-08-16T22:05:00Z → 2026-08-17T01:00:00Z
- 2026-08-23T22:05:00Z → 2026-08-24T01:00:00Z

These were requested; MT5 returned empty ticks. They are not unrequested periods and were not discarded.

## Next

STOP after Phase 27.26.

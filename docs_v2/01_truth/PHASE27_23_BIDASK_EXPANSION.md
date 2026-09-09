# Phase 27.23 — Historical XAUUSD_i M5 Bid/Ask Coverage Expansion

**Status:** PASS  
**This-session tape:** `DATASET`  
**Artifact:** `logs/phase27_23_bidask_expansion.json`  
**Collection timestamp UTC:** `2026-09-06T07:29:41Z`

Read-only. No MT5 start/restart, orders, `symbol_select`, `.env`, or production parquet overwrite.

## Environment

Verified REAL / `LiteFinance-MT5-Live`: **True** (`ok`).  
Attach: `REAL` / `LiteFinance-MT5-Live`.  
Terminal build: `6182`.

## Collection

Bounded 7-day UTC window via 6-hour `copy_ticks_range` chunks (split if a chunk hits 100000 ticks). Not an unbounded download.

| Metric | Value |
|---|---|
| ticks | `1116230` |
| invalid ticks | `0` |
| M5 bars | `992` |
| start UTC | `2026-08-31T01:05:00Z` |
| end UTC | `2026-09-03T14:40:00Z` |
| duration hours | `85.583` |
| fingerprint | `366c2202f20438d938d0ed54edb5f76fa3f01aea82b7537e3389f936b710f2de` |
| M5 tape | `logs/phase27_23_xauusd_i_m5_bidask.parquet` |
| raw ticks | `logs/phase27_23_xauusd_i_ticks.parquet` |

## vs Phase 27.18

27.18: `82` bars, `2026-09-04T17:10:00Z` → `2026-09-04T23:55:00Z`, fingerprint `c6aedc9bca3f9cf66d2c2e2971a301e224b2157e1cf91c60933a9a742398d319`.

Materially improved: **True** (992 bars / 85.583 h vs 82 / 6.75 h).

Safety stop: `max_total_ticks_reached` at 1,116,230 ticks. The requested 7-day window (`2026-08-30T07:29:42Z` → `2026-09-06T07:29:42Z`) was not fully retrieved. This tape ends `2026-09-03T14:40:00Z` and does **not** include the later Phase 27.18 window (`2026-09-04T17:10:00Z` → `2026-09-04T23:55:00Z`). The two logs tapes are complementary, not a single contiguous series.

## Coverage vs `data/XAUUSD_i_5m.parquet`

Canonical range: `2026-08-13T20:20:00Z` → `2026-08-28T17:25:00Z` (`3000` bars).  
Overlap: **False**. Exact timestamp matches: `0`.  
Full canonical coverage: **False**.

| Class | Result |
|---|---|
| A. Historical Bid/Ask exists | **PROVEN** |
| B. Bounded validation window | **PROVEN** |
| C. Full canonical research dataset | **BLOCKED** |

Spread may be **DATASET** only for the logs-only bounded window (`True`).  
Production parquet spread remains PROXY (`False`).  
Full cost-aware validation remains **BLOCKED**.

PROXY / OHLC / live tick were not substituted.

## Production

**BLOCKED.** COMPLETE_COSTS_REQUIRED was not weakened. FINAL_GATE remains `BLOCKED`.  
`data/XAUUSD_i_5m.parquet` and `data/XAUUSD_i_4h.parquet` were not overwritten. Phase 27.24+ not started.

## Next

STOP after Phase 27.23.

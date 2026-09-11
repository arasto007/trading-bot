# Phase 27.23 — Historical XAUUSD_i M5 Bid/Ask Coverage Expansion

**Status:** PASS  
**This-session tape:** `DATASET`  
**Artifact:** `logs/phase27_23_bidask_expansion.json`  
**Collection timestamp UTC:** `2026-09-10T07:30:42Z`

Read-only. No MT5 start/restart, orders, `symbol_select`, `.env`, or production parquet overwrite.

## Environment

Verified REAL / `LiteFinance-MT5-Live`: **True** (`ok`).  
Attach: `REAL` / `LiteFinance-MT5-Live`.  
Terminal build: `6182`.

## Collection

Bounded 7-day UTC window via 6-hour `copy_ticks_range` chunks (split if a chunk hits 100000 ticks). Not an unbounded download.

| Metric | Value |
|---|---|
| ticks | `1119725` |
| invalid ticks | `0` |
| M5 bars | `1129` |
| start UTC | `2026-09-03T07:30:00Z` |
| end UTC | `2026-09-09T13:05:00Z` |
| duration hours | `149.583` |
| fingerprint | `b3f652aa46538780a053209dd132dcfdc83ac12d8332f820458b019f44b42c67` |
| M5 tape | `logs/phase27_23_xauusd_i_m5_bidask.parquet` |
| raw ticks | `logs/phase27_23_xauusd_i_ticks.parquet` |

## vs Phase 27.18

27.18: `121` bars, `2026-09-09T20:30:00Z` → `2026-09-10T07:30:00Z`, fingerprint `038febf1c16eba42cafe13b43a66239430f8949b80790f61f012d33c1ea2ff24`.

Materially improved: **True** (1129 bars / 149.583 h vs 121 / 11.0 h).

Safety stop: `max_total_ticks_reached`. Requested window `2026-09-03T07:30:43Z` → `2026-09-10T07:30:43Z`. This tape is not automatically a superset of Phase 27.18.

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

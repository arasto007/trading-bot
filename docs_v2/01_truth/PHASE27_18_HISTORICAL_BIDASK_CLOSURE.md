# Phase 27.18 — Historical M5 Bid/Ask Closure

**Status:** PASS  
**Evidence status:** `DATASET`  
**Artifact:** `logs/phase27_18_historical_bidask.json`

## Policy

Canonical symbol = `XAUUSD_i`. Historical **DATASET** spread requires actual historical Bid + Ask. PROXY spread is never equivalent to historical Bid/Ask.

## Existing repository inventory

| Metric | Value |
|---|---|
| datasets scanned | `43` |
| datasets with bid+ask columns | `2` |
| historical bid/ask in production datasets | `False` |
| canonical XAUUSD_i files | `12` |
| sidecars scanned | `33` |
| prior valid logs tape | `True` |

Production/research parquets under `data/`, `data/backtest/`, and `data/cache/` are not rewritten. A logs-only tape is **not** a production dataset.

## Live tick rejection

Phase 27.17 current/stale Bid/Ask is **not** historical data. Tick UTC `2026-09-10T10:30:40Z` treated as historical M5 tape: **False**.

## Collection

Read-only attach only. MT5 was not started or restarted. `symbol_select` was not called. No orders. `.env` was not read or written.

If a REAL terminal is already connected, a bounded `copy_ticks_range` window (7 days, max 100000 ticks) is aggregated to M5 and written under `logs/` only.

This session collection possible: **True**. Tape status: **DATASET**. Tape path: `logs/phase27_18_xauusd_i_m5_bidask.parquet`.

Bounded window only. A truncated tick cap is not a full-history tape and does not rewrite production datasets.

## Substitutions rejected

- current Bid/Ask tick (including Phase 27.17 live snapshot)
- OHLC-implied spread
- proxy/session spread
- spread column

OHLC frame spread mode: `PROXY`. Spread-column frame spread mode: `PROXY` (not DATASET).

## Cost provenance

| Surface | Classification |
|---|---|
| production datasets | `PROXY` / `BLOCKED_PENDING_DATA` |
| logs tape | `DATASET` |
| DATASET requires historical Bid/Ask | `True` |

`DATASET` is claimed only when genuine historical Bid/Ask exists. Otherwise evidence remains `BLOCKED_PENDING_DATA`. Production datasets stay PROXY unless those files themselves contain historical Bid/Ask.

## Production

**BLOCKED.** FINAL_GATE remains `BLOCKED`. No Strategy, RiskGate, or execution changes. Phase 27.19+ not started.

## Next

STOP after Phase 27.18.

# Phase 27.11 — Historical M5 Bid/Ask Evidence

**Status:** PASS  
**Evidence status:** `COLLECTED_EVIDENCE_ONLY`  
**Artifact:** `logs/phase27_11_historical_bidask.json`

## Canonical target

`XAUUSD_i` M5. A live `symbol_info_tick` Bid/Ask is **not** historical bid/ask.

## Existing repository inventory

| Metric | Value |
|---|---|
| datasets scanned | `43` |
| datasets with bid+ask columns | `2` |
| historical bid/ask available | `False` |
| canonical XAUUSD_i files | `12` |

All production/research parquets under `data/`, `data/backtest/`, and `data/cache/` are OHLC-only. Sidecars already mark spread `PROXY` and `historical_bid_ask_available=false`.

## Collection

Read-only attach only. MT5 was not started. `symbol_select` was not called. No orders.

If a REAL terminal is already connected, a bounded `copy_ticks_range` window (7 days, max 100000 ticks) is aggregated to M5 and written under `logs/` only. Original datasets are never overwritten.

This session: **COLLECTED_EVIDENCE_ONLY**. Tape path: `logs/phase27_11_xauusd_i_m5_bidask.parquet`.

## Substitutions rejected

- current Bid/Ask tick
- OHLC-implied spread
- proxy/session spread

`Cost` provenance now claims `DATASET` spread only when historical bid+ask columns exist.

## Production

**BLOCKED.** No strategy or backtest parameter changes.

## Next

STOP after Phase 27.11.

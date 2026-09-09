# Phase 29 — Long-Horizon XAUUSD_i Research Tape

**Status:** PASS_WITH_DEFERRAL
**Class:** RESEARCH / DATA ENGINEERING ONLY
**Live trading authorized:** NO
**Production changes:** `NONE`
**Parameters optimized:** NO
**FINAL_GATE:** `BLOCKED`

Longest **defensible** historical research tape for broker-observed canonical symbol `XAUUSD_i`.
Logical `XAUUSD` tapes were **not** merged. EV-EQ-01 remains `NOT_PROVEN`.

STOP AFTER PHASE 29. DO NOT START PHASE 30.

---

## Coverage

| Tape | Path | Start | End | Days | Bars | Coverage % (weekday 24h) |
|---|---|---|---|---:|---:|---:|
| M5 entry (Phase 28 frozen) | `data/XAUUSD_i_5m.parquet` | 2026-08-13 20:20:00+00:00 | 2026-08-28 17:25:00+00:00 | 14.878472 | 3000 | 95.7243 |
| H4 context | `data/XAUUSD_i_4h.parquet` | 2026-06-05 11:00:00+00:00 | 2026-08-14 11:00:00+00:00 | 70.0 | 300 | 99.6678 |
| M15 | — | — | — | — | 0 | NOT_OBSERVED |

Target ≥ 180 calendar days. Minimum acceptable ≥ 60. **M5 obtainable days = 14.878472.** Completeness was not fabricated.

---

## Collection

Attach-only M5 collection: NOT_OBSERVED. Error: terminal64.exe not running — attach skipped (MT5 was not started). Terminal was not started by this phase. Longest defensible existing M5 coverage is 14.88 calendar days.

MT5 trading was not started. `symbol_select` was not called. `.env` was not read. Orders were not sent.

---

## Data quality (M5)

| Check | Result |
|---|---|
| Duplicates | 0 |
| Malformed OHLC | 0 |
| Impossible OHLC | 0 |
| Zero volume | 0 |
| Negative volume | 0 |
| Timezone | UTC |
| Gap classes | {'EXPECTED_SESSION_GAP': 0, 'EXPECTED_WEEKEND_GAP': 2, 'BROKER_ROLLOVER_GAP': 9, 'UNKNOWN_GAP': 0} |

Gaps are classified. Weekend / rollover / session gaps are not automatically bad data.

---

## Bid / Ask

Available on a **separate** Phase 27.26 tape (`logs/phase27_26_xauusd_i_m5_bidask.parquet`), not inside the OHLC parquet.

- Status: `OBSERVED`
- Coverage vs Phase 28 M5 bars: `98.4`
- Spread provenance: `OBSERVED`
- Median spread (price / pips heuristic): `0.4099999999998545 / 4.099999999998545`

PROXY OHLC spread was **not** relabeled as OBSERVED.

---

## Provenance

- Symbol: `XAUUSD_i`
- Environment (OHLC sidecar): `DEMO`
- Source: `logs/operator_broker_evidence_demo_raw.json`
- Retrieval of new MT5 bars: `NOT_OBSERVED`
- This dataset proves only what was actually observed. It does not prove broker-wide economics outside the observed terminal/account.

## Fingerprints

- Phase 28 frozen M5 file SHA256: `ab3e25bab0c6d6689d6654317264cc7774e1b49f88df907a3ea1bd1ade313ed5`
- Phase 28 frozen M5 content: `7cddeca8b7dfc9d715f1f7d1c24fa21922002775f36bbe21c93209684ba1f66d`
- Spec: `{'algorithm': 'SHA256', 'input_columns': ['timestamp_utc_ns', 'open', 'high', 'low', 'close', 'volume'], 'row_ordering_rule': 'timestamp ascending, UTC', 'timestamp_normalization_rule': 'tz-aware UTC; int64 nanoseconds since epoch'}`

Phase 28 canonical parquet was **not** overwritten.

## Dataset binding

Empty `dataset_symbol_map`. `XAUUSD_i` is a direct canonical match. Logical `XAUUSD` remains `ONLY_WITH_EXPLICIT_DATASET_MAP`. Silent mapping did not occur.

## Limitations

M5 XAUUSD_i coverage is 14.88 calendar days (target 180, minimum 60). A longer tape was not observed this run because attach-only MT5 collection did not return additional XAUUSD_i bars. Logical XAUUSD 180d/183d files exist but remain BLOCKED (MISSING_EXPLICIT_MAP; EV-EQ-01 NOT_PROVEN) and were not merged. OHLC has no Bid/Ask columns (PROXY/ohlc_only). Phase 27.26 Bid/Ask is OBSERVED only for the ~15-day canonical window and is not a 180-day tape. Sidecar economics are DEMO LiteFinance evidence and do not prove Real-account identity.

## Recommendation

Keep the Phase 28 M5 snapshot frozen. When a terminal is already running, re-run this phase attach-only to persist a longer XAUUSD_i tape under data/XAUUSD_i_*_phase29.parquet. Do not silently promote logical XAUUSD history. Do not start parameter optimization. Phase 30 was not started.

## Safety

No strategy / RiskGate / ML / execution / PA-lock / calibration change. Phase 30 was **not** started.

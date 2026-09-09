# Phase 106 — Non-OHLC Data Inventory

CODE-EVIDENCE from inspecting local files. No MT5. No download. No .env.
**NON_OHLC_DATA_STATUS:** `PARTIAL_LOCAL_FILES_INCOMPLETE_EVENT_COVERAGE`
Event unit n=`419` signals=`2847`

| ID | class | overlap | path |
|---|---|---|---|
| `A_TICK_PHASE38` | `AVAILABLE_BUT_INCOMPLETE` | `0/419` | `data/XAUUSD_i_ticks_phase38.parquet` |
| `A_TICK_P27_26` | `AVAILABLE_BUT_INCOMPLETE` | `3/419` | `logs/phase27_26_xauusd_i_ticks.parquet` |
| `B_BIDASK_PHASE38` | `AVAILABLE_BUT_INCOMPLETE` | `0/419` | `logs/phase38_xauusd_i_bidask.parquet` |
| `C_SPREAD_P27_26_M5` | `AVAILABLE_BUT_INCOMPLETE` | `3/419` | `logs/phase27_26_xauusd_i_m5_bidask.parquet` |
| `D_M1_PHASE38` | `AVAILABLE_BUT_INCOMPLETE` | `8/419` | `data/XAUUSD_i_m1_phase38.parquet` |
| `E_M15_PHASE38` | `AVAILABLE_AND_USABLE` | `229/419` | `data/XAUUSD_i_m15_phase38.parquet` |
| `F_H1_LOGICAL` | `AVAILABLE_BUT_INCOMPLETE` | `40/419` | `data/XAUUSD_1h.parquet` |
| `G_H4_XAUUSD_I` | `AVAILABLE_BUT_INCOMPLETE` | `18/419` | `data/XAUUSD_i_4h.parquet` |
| `G_H4_LOGICAL_ML` | `AVAILABLE_BUT_INCOMPLETE` | `401/419` | `data/ml/raw/candles/h4/XAUUSD_h4.parquet` |
| `E_M15_LOGICAL_ML` | `AVAILABLE_BUT_INCOMPLETE` | `401/419` | `data/ml/raw/candles/m15/XAUUSD_m15.parquet` |
| `H_SESSION_REPLAY` | `AVAILABLE_BUT_INCOMPLETE` | `2/419` | `logs/session_filter_blocked_replay.jsonl` |
| `L_TRADE_JOURNAL` | `AVAILABLE_BUT_INCOMPLETE` | `None/None` | `data/trade_journal.db` |
| `M_ML_V2` | `AVAILABLE_BUT_NONCAUSAL` | `401/419` | `data/ml/datasets/XAUUSD_M5_dataset_v2.parquet` |

## Absent categories
- `I_NEWS` **MISSING** — No historical news json/parquet/csv on disk. news_calendar.py is a generator, not a dataset.
- `J_CALENDAR` **MISSING** — No economic-calendar data file on disk.
- `F_H1_CANONICAL` **MISSING** — No XAUUSD_i H1 parquet.
- `K_MICROSTRUCTURE_FULL` **MISSING** — No full-horizon tick/order-book tape overlapping Phase40 events.

Logical `XAUUSD` files are not treated as canonical (EV-EQ-01 NOT_PROVEN).

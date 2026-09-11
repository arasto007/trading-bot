# Phase 115 — Non-OHLC Data Acquisition & Ingestion

FROZEN-DATA-EVIDENCE (local files) and CODE-EVIDENCE (joins). Not exit-design research.

PHASE115_STATUS = PASS
ACQUISITION_STATUS = LOCAL_SIDECARS_ONLY
INGESTION_STATUS = COMPLETE_FOR_AVAILABLE_SOURCES
DATA_QUALITY_STATUS = PARTIAL
PHASE116_READY = False

TICK_STATUS = TICK_DATA_PARTIAL
SPREAD_STATUS = SPREAD_DATA_PARTIAL
M1_STATUS = M1_DATA_PARTIAL
M15_STATUS = M15_DATA_PARTIAL
H1_STATUS = H1_DATA_MISSING
H4_STATUS = H4_DATA_PARTIAL
NEWS_STATUS = NEWS_DATA_MISSING

TICK_EVENT_COVERAGE = 3
TICK_COMPLETE_LIFECYCLE_EVENTS = 3
TICK_ENTRY_COVERAGE = 3
TICK_EXIT_COVERAGE = 3
TICK_INTRABAR_RESOLUTION_COVERAGE = 3

AMBIGUOUS_394_RESOLVED = 3
AMBIGUOUS_394_REMAINING = 391

OUTLIER_31_84R_TICK_COVERAGE = False
OUTLIER_31_84R_CHRONOLOGY_STATUS = DATA_INSUFFICIENT

C_VS_D_VS_E_VS_F_STATUS = DATA_INSUFFICIENT
SPREAD_INFORMATION_STATUS = DESCRIPTIVE_ONLY_N_LT_MIN_BIN
M1_INCREMENTAL_INFORMATION_STATUS = M1_ADDS_NO_INTRABAR_ORDER
H1_INFORMATION_STATUS = H1_CANONICAL_MISSING
NEWS_INFORMATION_STATUS = NEWS_DATA_MISSING

REMAINING_UNKNOWN = Full-horizon XAUUSD_i tick bid/ask covering 2023-02-26T15:40:00Z–2026-09-07T20:10:00Z; canonical XAUUSD_i H1; M15 gap before 2024-07-25; H4 full horizon; historical scheduled news/calendar. Local ticks cover only a late-2026 sidecar window.

TESTS_PHASE115 = {'passed': 13, 'skipped': 0, 'failed': 0}
REGRESSION_40_43_57_63_68_115 = {'passed': 143, 'skipped': 4, 'failed': 0}

FROZEN_PHASE40_TIMESTAMP = 2026-09-07T21:09:46Z
FROZEN_PHASE40_FINGERPRINT = 222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5
FROZEN_PHASE40_SHA256 = 6f4ff0b6dae0d86974414f129f3c1e6009c21bcb285ad0c449d5033bda4ee17f

## Safety

No MT5, no .env, no orders, no production changes, no exit-rule tests.
Ticks were not synthesized. Missing bid/ask was not replaced with OHLC.
Logical XAUUSD was not substituted for XAUUSD_i. EV-EQ-01 remains NOT_PROVEN.

## Sources

[
  {
    "source_name": "A_TICK_PHASE38",
    "path": "data/XAUUSD_i_ticks_phase38.parquet",
    "XAUUSD_i_verified": true,
    "acquisition_status": "AVAILABLE_LOCAL",
    "n_rows": 300000,
    "coverage_start": "2026-08-31T20:00:00.030000Z",
    "coverage_end": "2026-09-01T17:52:29.184000Z"
  },
  {
    "source_name": "A_TICK_P27_26",
    "path": "logs/phase27_26_xauusd_i_ticks.parquet",
    "XAUUSD_i_verified": true,
    "acquisition_status": "AVAILABLE_LOCAL",
    "n_rows": 3125805,
    "coverage_start": "2026-08-13T20:20:00Z",
    "coverage_end": "2026-08-28T17:29:59Z"
  },
  {
    "source_name": "B_BIDASK_PHASE38",
    "path": "logs/phase38_xauusd_i_bidask.parquet",
    "XAUUSD_i_verified": true,
    "acquisition_status": "AVAILABLE_LOCAL",
    "n_rows": 68183,
    "coverage_start": "2026-08-31T20:00:00Z",
    "coverage_end": "2026-09-01T17:52:29Z"
  },
  {
    "source_name": "C_SPREAD_P27_26_M5",
    "path": "logs/phase27_26_xauusd_i_m5_bidask.parquet",
    "XAUUSD_i_verified": true,
    "acquisition_status": "AVAILABLE_LOCAL",
    "n_rows": 2952,
    "coverage_start": "2026-08-13T20:20:00Z",
    "coverage_end": "2026-08-28T17:25:00Z"
  },
  {
    "source_name": "D_M1_PHASE38",
    "path": "data/XAUUSD_i_m1_phase38.parquet",
    "XAUUSD_i_verified": true,
    "acquisition_status": "AVAILABLE_LOCAL",
    "n_rows": 30000,
    "coverage_start": "2026-08-07T01:50:00Z",
    "coverage_end": "2026-09-07T20:01:00Z"
  },
  {
    "source_name": "E_M15_PHASE38",
    "path": "data/XAUUSD_i_m15_phase38.parquet",
    "XAUUSD_i_verified": true,
    "acquisition_status": "AVAILABLE_LOCAL",
    "n_rows": 50000,
    "coverage_start": "2024-07-25T12:15:00Z",
    "coverage_end": "2026-09-07T20:00:00Z"
  },
  {
    "source_name": "F_H1_LOGICAL",
    "path": "data/XAUUSD_1h.parquet",
    "XAUUSD_i_verified": false,
    "acquisition_status": "REJECTED_SYMBOL",
    "n_rows": 3000,
    "coverage_start": "2026-02-02T11:00:00Z",
    "coverage_end": "2026-08-05T08:00:00Z"
  },
  {
    "source_name": "G_H4_XAUUSD_I",
    "path": "data/XAUUSD_i_4h.parquet",
    "XAUUSD_i_verified": true,
    "acquisition_status": "AVAILABLE_LOCAL",
    "n_rows": 300,
    "coverage_start": "2026-06-05T11:00:00Z",
    "coverage_end": "2026-08-14T11:00:00Z"
  },
  {
    "source_name": "G_H4_LOGICAL_ML",
    "path": "data/ml/raw/candles/h4/XAUUSD_h4.parquet",
    "XAUUSD_i_verified": false,
    "acquisition_status": "REJECTED_SYMBOL",
    "n_rows": 33768,
    "coverage_start": "2004-06-11T04:00:00Z",
    "coverage_end": "2026-06-29T12:00:00Z"
  },
  {
    "source_name": "E_M15_LOGICAL_ML",
    "path": "data/ml/raw/candles/m15/XAUUSD_m15.parquet",
    "XAUUSD_i_verified": false,
    "acquisition_status": "REJECTED_SYMBOL",
    "n_rows": 506461,
    "coverage_start": "2004-06-11T07:15:00Z",
    "coverage_end": "2026-06-29T13:45:00Z"
  },
  {
    "source_name": "H_SESSION_REPLAY",
    "path": "logs/session_filter_blocked_replay.jsonl",
    "XAUUSD_i_verified": false,
    "acquisition_status": "EMPTY",
    "n_rows": 0,
    "coverage_start": null,
    "coverage_end": null
  },
  {
    "source_name": "L_TRADE_JOURNAL",
    "path": "data/trade_journal.db",
    "XAUUSD_i_verified": false,
    "acquisition_status": "EMPTY",
    "n_rows": 0,
    "coverage_start": null,
    "coverage_end": null
  },
  {
    "source_name": "M_ML_V2",
    "path": "data/ml/datasets/XAUUSD_M5_dataset_v2.parquet",
    "XAUUSD_i_verified": false,
    "acquisition_status": "REJECTED_SYMBOL",
    "n_rows": 5724,
    "coverage_start": null,
    "coverage_end": null
  },
  {
    "source_name": "A_TICK_PHASE37",
    "path": "data/XAUUSD_i_ticks_phase37.parquet",
    "XAUUSD_i_verified": true,
    "acquisition_status": "MISSING",
    "n_rows": 0,
    "coverage_start": null,
    "coverage_end": null
  },
  {
    "source_name": "D_M1_PHASE37",
    "path": "data/XAUUSD_i_m1_phase37.parquet",
    "XAUUSD_i_verified": true,
    "acquisition_status": "MISSING",
    "n_rows": 0,
    "coverage_start": null,
    "coverage_end": null
  },
  {
    "source_name": "F_H1_CANONICAL_ABSENT",
    "path": "data/XAUUSD_i_1h.parquet",
    "XAUUSD_i_verified": true,
    "acquisition_status": "MISSING",
    "n_rows": 0,
    "coverage_start": null,
    "coverage_end": null
  },
  {
    "source_name": "I_NEWS_RESEARCH",
    "path": "data/research/non_ohlc/news/historical_calendar.parquet",
    "XAUUSD_i_verified": false,
    "acquisition_status": "MISSING",
    "n_rows": 0,
    "coverage_start": null,
    "coverage_end": null
  }
]

## Tick window

- rows: `3493969`
- first: `2026-08-13T20:20:00Z`
- last: `2026-09-01T17:52:29.184000Z`
- calendar days: `14`
- active trading days: `14`

Full acquisition window was not covered by local ticks.

## Execution semantics (research reconstruction only)

- long favorable: ask > entry; long adverse: bid < entry
- short favorable: bid < entry; short adverse: ask > entry
- same-timestamp fav+adv → SIMULTANEOUS_UNRESOLVED
- production execution unchanged

Phase 116 was not started.


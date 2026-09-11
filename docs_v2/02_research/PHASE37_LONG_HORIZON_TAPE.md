# Phase 37 — Long-Horizon XAUUSD_i Historical Tape Acquisition

**STATUS:** `PASS`
**Class:** RESEARCH / DATA ACQUISITION ONLY
**Live trading authorized:** NO
**Production changes:** `NONE`
**Parameters optimized:** NO
**Strategy evaluated:** NO
**FINAL_GATE:** `BLOCKED`

STOP AFTER PHASE 37. DO NOT START PHASE 38.
DO NOT OPTIMIZE. DO NOT ALTER PRODUCTION.

This phase exists to resolve the Phase 36 evidence bottleneck (tape ~14.88 days / 6 events).
The frozen Phase 28/30 snapshot `data/XAUUSD_i_5m.parquet` was **not** overwritten.

---

## TERMINAL

**ATTACHED**

- Broker/server: `LiteFinance Global LLC` / `LiteFinance-MT5-Live`
- Environment: `REAL`
- Path: `C:\Program Files\MetaTrader 5`
- Build: `6182`
- Connected: `True`
- Multiple terminals: `False`
- Attach-only: `True`
- MT5 started by this phase: `False`
- Retrieval: `2026-09-10T07:34:55Z`
- Error: `None`
- Note: none

## SYMBOL

- `XAUUSD_i` = `YES`
- `XAUUSD` = `ABSENT_ON_OBSERVED_TERMINAL`

`XAUUSD` absence is **ABSENT_ON_OBSERVED_TERMINAL** at most. Broker-wide absence was not concluded.
`dataset_symbol_map` is empty. Silent mapping did not occur. `symbol_select` was not called.

Symbol evidence (XAUUSD_i): `{'symbol': 'XAUUSD_i', 'existence': 'YES', 'visibility': 'YES', 'digits': 2, 'point': 0.01, 'contract_size': 100.0, 'tick_size': 0.01, 'tick_value': 1.0, 'tick_value_profit': 1.0, 'tick_value_loss': 1.0, 'volume_min': 0.01, 'volume_max': 100.0, 'volume_step': 0.01, 'stops_level': 0, 'freeze_level': 0, 'filling_mode': 1, 'execution_mode': 2, 'calc_mode': 2, 'swap_long': -89.136, 'swap_short': 3.45, 'rollover3days': 3, 'bid': 4404.49, 'ask': 4404.9, 'quote_utc': '2026-09-10T10:34:58Z', 'broker_wide_absence_concluded': False, 'selectable': 'YES', 'trade_mode': 4, 'trade_mode_label': 'FULL', 'symbol_select_called': False, 'presence': 'YES'}`

## M5

| Field | Value |
|---|---|
| Path | `data/XAUUSD_i_5m_phase37.parquet` |
| Start | 2023-02-28 21:00:00+00:00 |
| End | 2026-09-10 10:30:00+00:00 |
| Days | 1289.5625 |
| Rows | 250000 |
| Coverage 24x7 % | 67.3138 |
| Coverage weekday 24h % | 94.1935 |
| Status | OBSERVED |
| Partial | False |

## TARGET

- 60-day minimum: `True`
- 180-day preferred: `True`

Completeness was not fabricated.

## GAPS

`{'EXPECTED_SESSION_GAP': 0, 'EXPECTED_WEEKEND_GAP': 180, 'BROKER_ROLLOVER_GAP': 702, 'UNKNOWN_GAP': 53}`

UNKNOWN_GAP is **not** automatically acceptable.

## BID/ASK

Status: `OBSERVED`  
Grade: `OBSERVED` (OBSERVED remains separate from PROXY and MODELED)  
Coverage: `OBSERVED ticks n=71326 over bounded lookback`  
Stats: `{'available': True, 'status': 'OBSERVED', 'grade': 'OBSERVED', 'not_proxy': True, 'not_modeled': True, 'n': 71326, 'median': 0.4099999999998545, 'p75': 0.42000000000007276, 'p90': 0.42000000000007276, 'p95': 0.5500000000001819, 'p99': 0.5799999999999272, 'max': 0.8599999999996726, 'median_pips': 4.099999999998545, 'p75_pips': 4.200000000000728, 'p90_pips': 4.200000000000728, 'p95_pips': 5.500000000001819, 'p99_pips': 5.799999999999272, 'max_pips': 8.599999999996726, 'by_hour_utc_median_pips': {'1': 5.69999999999709, '2': 5.599999999994907, '3': 4.200000000000728, '4': 4.200000000000728, '5': 4.200000000000728, '6': 4.200000000000728, '7': 4.200000000000728, '8': 4.200000000000728, '9': 3.999999999996362, '10': 3.8000000000010914, '11': 3.900000000003274, '12': 3.900000000003274, '13': 3.900000000003274, '14': 3.8999999999941792, '15': 3.900000000003274, '16': 3.8999999999941792, '17': 3.900000000003274, '18': 3.8999999999941792, '19': 3.900000000003274, '20': 3.6999999999989086, '21': 4.000000000005457, '22': 3.999999999996362, '23': 3.599999999996726}, 'ny_15_16_utc': {'n': 3574, 'median': 3.900000000003274, 'p75': 4.099999999998545, 'p90': 4.200000000000728, 'p95': 4.200000000000728, 'p99': 4.200000000000728, 'max': 4.200000000000728, 'status': 'OBSERVED'}, 'rollover_21_00_utc': {'n': 9154, 'median': 3.8000000000010914, 'p75': 4.200000000000728, 'p90': 4.200000000000728, 'p95': 4.200000000000728, 'p99': 4.200000000000728, 'max': 4.200000000000728, 'status': 'OBSERVED'}, 'weekend': {'n': 0, 'status': 'NOT_OBSERVED'}, 'pip_size_heuristic': 0.1, 'first_timestamp': '2026-09-03 10:30:00+00:00', 'last_timestamp': '2026-09-04 09:41:38+00:00'}`

Missing Bid/Ask was **not** replaced with proxy values.

## M15

`{'path': 'data/XAUUSD_i_15m_phase37.parquet', 'status': 'OBSERVED', 'ok': True, 'start': '2024-07-29 22:15:00+00:00', 'end': '2026-09-10 10:30:00+00:00', 'days': 772.5104166666666, 'rows': 50000, 'partial': False, 'error': None, 'below_minimum_60d': False, 'below_preferred_180d': False}`

## M1

`{'path': 'data/XAUUSD_i_m1_phase37.parquet', 'status': 'OBSERVED', 'ok': True, 'start': '2026-08-11 11:58:00+00:00', 'end': '2026-09-10 10:35:00+00:00', 'days': 29.94236111111111, 'rows': 30000, 'partial': False, 'error': None, 'below_minimum_60d': True, 'below_preferred_180d': True}`

## TICKS

`{'path': 'data/XAUUSD_i_ticks_phase37.parquet', 'status': 'PARTIAL', 'rows': 300000, 'partial': True, 'resource_bound': True, 'error': None}`

## FINGERPRINT

- Frozen Phase 28/30 file: `ab3e25bab0c6d6689d6654317264cc7774e1b49f88df907a3ea1bd1ade313ed5`
- Frozen unchanged: `True`
- Phase 37 M5 file: `990edd803237c9b950f60607aa4832306b7a0c3957bcca3f8097a2f9cad9b87e`
- Phase 37 M5 content: `3a87e18ccb67bb27fae0cf4194df7eb2ba69ab826b1817ec10f2744b697e8f3f`

Phase 28 fingerprint is reused only if content is identical.

## CONTENT HASH

`3a87e18ccb67bb27fae0cf4194df7eb2ba69ab826b1817ec10f2744b697e8f3f`

## DATASET_BINDING

Empty map. Canonical symbol `XAUUSD_i` only. Logical `XAUUSD` was not merged, renamed, or silently bound.

`{'canonical_symbol': 'XAUUSD_i', 'dataset_symbol_map': {}, 'empty_map': True, 'xauusd_merged': False, 'xauusd_renamed': False, 'silent_xauusd_mapping': False, 'm5': {'logical_symbol': 'XAUUSD_i', 'configured_symbol': 'XAUUSD_i', 'mapped_broker_symbol': 'XAUUSD_i', 'mapping_source': 'match', 'mapping_status': 'MATCH', 'blocked': False, 'reason': 'ok', 'map_entry_used': None, 'ev_eq_01': 'NOT_PROVEN'}, 'logical_xauusd_used': False}`

## PROVENANCE

`{'symbol': 'XAUUSD_i', 'timeframe': 'M5', 'source': 'mt5.copy_rates_from_pos attach-only', 'broker': 'LiteFinance Global LLC', 'server': 'LiteFinance-MT5-Live', 'environment': 'REAL', 'retrieval_timestamp_utc': '2026-09-10T07:34:55Z', 'terminal_path': 'C:\\Program Files\\MetaTrader 5', 'terminal_build': 6182, 'row_count': 250000, 'coverage': {'path': 'data/XAUUSD_i_5m_phase37.parquet', 'symbol': 'XAUUSD_i', 'timeframe': 'M5', 'row_count': 250000, 'first_timestamp': '2023-02-28 21:00:00+00:00', 'last_timestamp': '2026-09-10 10:30:00+00:00', 'duration_days': 1289.5625, 'expected_bars_24x7': 371395, 'expected_bars_weekday_24h': 265411, 'observed_bars': 250000, 'coverage_pct_24x7': 67.3138, 'coverage_pct_weekday_24h': 94.1935, 'duplicate_timestamps': 0, 'missing_timestamps_24x7': 121395, 'malformed_timestamps': 0, 'malformed_ohlc': 0, 'impossible_ohlc': 0, 'high_lt_low': 0, 'close_outside_high_low': 0, 'negative_prices': 0, 'zero_volume': 5, 'negative_volume': 0, 'abnormal_timestamp_ordering': False, 'timezone': 'UTC', 'timezone_consistent_utc': True, 'gap_count': 935, 'gap_classification': {'EXPECTED_SESSION_GAP': 0, 'EXPECTED_WEEKEND_GAP': 180, 'BROKER_ROLLOVER_GAP': 702, 'UNKNOWN_GAP': 53}, 'gap_examples': [{'from': '2023-02-28 23:55:00+00:00', 'to': '2023-03-01 01:00:00+00:00', 'delta_minutes': 65.0, 'classification': 'BROKER_ROLLOVER_GAP'}, {'from': '2023-03-01 23:55:00+00:00', 'to': '2023-03-02 01:00:00+00:00', 'delta_minutes': 65.0, 'classification': 'BROKER_ROLLOVER_GAP'}, {'from': '2023-03-02 23:55:00+00:00', 'to': '2023-03-03 01:00:00+00:00', 'delta_minutes': 65.0, 'classification': 'BROKER_ROLLOVER_GAP'}, {'from': '2023-03-03 23:55:00+00:00', 'to': '2023-03-06 01:00:00+00:00', 'delta_minutes': 2945.0, 'classification': 'EXPECTED_WEEKEND_GAP'}, {'from': '2023-03-06 23:55:00+00:00', 'to': '2023-03-07 01:00:00+00:00', 'delta_minutes': 65.0, 'classification': 'BROKER_ROLLOVER_GAP'}, {'from': '2023-03-07 23:55:00+00:00', 'to': '2023-03-08 01:00:00+00:00', 'delta_minutes': 65.0, 'classification': 'BROKER_ROLLOVER_GAP'}, {'from': '2023-03-08 23:55:00+00:00', 'to': '2023-03-09 01:00:00+00:00', 'delta_minutes': 65.0, 'classification': 'BROKER_ROLLOVER_GAP'}, {'from': '2023-03-09 23:55:00+00:00', 'to': '2023-03-10 01:00:00+00:00', 'delta_minutes': 65.0, 'classification': 'BROKER_ROLLOVER_GAP'}, {'from': '2023-03-10 23:55:00+00:00', 'to': '2023-03-13 00:00:00+00:00', 'delta_minutes': 2885.0, 'classification': 'EXPECTED_WEEKEND_GAP'}, {'from': '2023-03-13 22:55:00+00:00', 'to': '2023-03-14 00:00:00+00:00', 'delta_minutes': 65.0, 'classification': 'BROKER_ROLLOVER_GAP'}, {'from': '2023-03-14 22:55:00+00:00', 'to': '2023-03-15 00:00:00+00:00', 'delta_minutes': 65.0, 'classification': 'BROKER_ROLLOVER_GAP'}, {'from': '2023-03-15 22:55:00+00:00', 'to': '2023-03-16 00:00:00+00:00', 'delta_minutes': 65.0, 'classification': 'BROKER_ROLLOVER_GAP'}, {'from': '2023-03-16 22:55:00+00:00', 'to': '2023-03-17 00:00:00+00:00', 'delta_minutes': 65.0, 'classification': 'BROKER_ROLLOVER_GAP'}, {'from': '2023-03-17 22:55:00+00:00', 'to': '2023-03-20 00:00:00+00:00', 'delta_minutes': 2945.0, 'classification': 'EXPECTED_WEEKEND_GAP'}, {'from': '2023-03-20 22:55:00+00:00', 'to': '2023-03-21 00:00:00+00:00', 'delta_minutes': 65.0, 'classification': 'BROKER_ROLLOVER_GAP'}, {'from': '2023-03-21 22:55:00+00:00', 'to': '2023-03-22 00:00:00+00:00', 'delta_minutes': 65.0, 'classification': 'BROKER_ROLLOVER_GAP'}], 'columns': ['open', 'high', 'low', 'close', 'volume'], 'bid_present': False, 'ask_present': False, 'spread_column_present': False, 'note': 'Gaps are classified, not auto-treated as bad data. Weekend/rollover/session gaps are expected on gold.'}, 'gap_classification': {'EXPECTED_SESSION_GAP': 0, 'EXPECTED_WEEKEND_GAP': 180, 'BROKER_ROLLOVER_GAP': 702, 'UNKNOWN_GAP': 53}, 'fingerprint': '990edd803237c9b950f60607aa4832306b7a0c3957bcca3f8097a2f9cad9b87e', 'content_hash': '3a87e18ccb67bb27fae0cf4194df7eb2ba69ab826b1817ec10f2744b697e8f3f', 'columns': ['open', 'high', 'low', 'close', 'volume'], 'timezone': 'UTC', 'limitations': 'Terminal status ATTACHED. M5 collected days=1289.5625 (minimum 60, preferred 180). Completeness was not fabricated. Logical XAUUSD was not merged. Frozen data/XAUUSD_i_5m.parquet fingerprint ab3e25bab0c6d6689d6654317264cc7774e1b49f88df907a3ea1bd1ade313ed5 unchanged. OHLC Phase 37 tape has no Bid/Ask columns (PROXY/ohlc_only). Tick Bid/Ask, if present, is OBSERVED only for the bounded tick window. This phase does not evaluate gold_ny_sweep and does not authorize live trading.'}`

## LIMITATIONS

Terminal status ATTACHED. M5 collected days=1289.5625 (minimum 60, preferred 180). Completeness was not fabricated. Logical XAUUSD was not merged. Frozen data/XAUUSD_i_5m.parquet fingerprint ab3e25bab0c6d6689d6654317264cc7774e1b49f88df907a3ea1bd1ade313ed5 unchanged. OHLC Phase 37 tape has no Bid/Ask columns (PROXY/ohlc_only). Tick Bid/Ask, if present, is OBSERVED only for the bounded tick window. This phase does not evaluate gold_ny_sweep and does not authorize live trading.

## PRODUCTION_CHANGES

MUST BE NONE — recorded `NONE`.

## NEXT STEP

Do not start Phase 38 from this file. Do not run strategy evaluation. Do not optimize.

## Safety

No live orders, no `.env`, no frozen parquet rewrite, no strategy/RiskGate/ML change.
Phase 38 was **not** started.

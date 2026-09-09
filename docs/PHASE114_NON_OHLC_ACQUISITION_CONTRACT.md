# Phase 114 — Non-OHLC Acquisition Contract

INFERENCE over FROZEN-DATA-EVIDENCE (event timestamps) and CODE-EVIDENCE (lookback constants). Data not acquired.
**ACQUISITION_READY:** `True`
**DATA_ACQUIRED:** `false`
**CONTRACT_COMPLETE:** `true`

## 114A Horizon
- earliest event: `2023-02-27T15:40:00+00:00`
- latest event: `2026-09-04T15:00:00+00:00`
- latest exit: `2026-09-04T15:30:00+00:00`
- acquisition window: `2023-02-26T15:40:00+00:00` → `2026-09-07T20:10:00+00:00`
- symbol: `XAUUSD_i` (not `XAUUSD`)
- timezone: `UTC`
- tick precision: millisecond; bars: bar-open seconds
- before entry: H4 lookback 1440 min; news 30 min scheduled-only
- after entry: through measured exit; max hold `7320.0` minutes; do not cap +31.84R

## 114B Tick schema
REQUIRED: `timestamp_utc`, `bid`, `ask`. OPTIONAL: last, volume, flags, source.
COMPLETE = 419/419 event lifecycles. Current local status: `TICK_DATA_MISSING`.

## 114C Spread
Prefer bid+ask; derive spread. Do not infer broker economics. Current: `SPREAD_DATA_MISSING`.

## 114D Timeframes
M1 / M15 / H1 / H4 OHLCV, `XAUUSD_i`, UTC, bar-open closed-bar semantics. No indicators as acquisition fields.

## 114E News
REQUIRED: event_timestamp_utc, event_name, source_provider. Actual values are not causal predictors at/after entry. Window: 30 min before entry. Do not use the in-repo generator.

## 114F Alignment
Event unit. As-of ticks `timestamp <= state_ts`. HTF last closed bar. News scheduled time `< entry`. Research not run in this phase.

## 114G Quality gate
11-point checklist. COMPLETE requires 419/419 coverage. Thresholds not searched.

## 114H Sources
Repo files / broker export / authorized provider / public datasets. No download. No XAUUSD substitute.

## 114I Priority
1. Tick+bid/ask  2. M1  3. Spread-from-quotes  4. H1  5. M15 gap  6. H4  7. News
Rationale: same-bar path ordering is the unresolved C/D vs E/F question; M15 already failed as a discriminator.

## 114J Stop
Data not acquired. Phase 115 not started. Operator must authorize a proven `XAUUSD_i` source before ingest.
**NEXT_RESEARCH_TARGET:** `OPERATOR_AUTHORIZED_XAUUSD_I_INGEST`

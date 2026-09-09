# Data Flow

**Status:** VERIFIED  
**Last verified:** 2026-09-01  

## Live (default)

```text
MT5 rates
  → Mt5MarketDataAdapter
  → DataStage
  → IndicatorStage (ATR and PA enrich)
  → SignalStage: exclude_forming_bar (drop last row) → registry.generate_signal
  → SignalFilterStage (WPSQF default OFF)
  → RiskStage / RiskGate
  → ExecutionStage / Mt5ExecutionAdapter
  → MT5 order_send (if live execute)
```

Evidence: `tradingbot/pipeline/`, `tradingbot/domain/ohlcv.py::exclude_forming_bar`, `bootstrap.build_kernel_live`.

## Research (not live)

```text
parquet candles (typically XAUUSD)
  → isolated replay / feature builders
  → models / metrics JSON
```

No automatic promotion onto the daemon.

## Look-ahead

Live decisions use **closed** bars (`iloc[:-1]`). Research that includes the last row is **not** comparable without documenting that difference.

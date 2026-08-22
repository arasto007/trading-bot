# Data Pipeline

## Status

- **Status:** VERIFIED
- **Last Verified:** 2026-08-22
- **Verification Method:** Read MT5 adapter, cache, data stage, runtime_truth normalization
- **Verified against commit:** `57bf778c23cefffe508bb49079688b177796f67e`

## Scope

Market data acquisition, storage, and delivery to the trading pipeline on the **live path**.

## Live Data Flow

```text
MetaTrader 5 terminal
  ↓
Mt5MarketDataAdapter.ensure_connected()     [attach-only, IPC lock held]
  ↓
Mt5MarketDataAdapter.update_all(symbols, timeframes)
  ↓
mt5.copy_rates_from_pos(broker_symbol, tf, 0, count)
  ↓
normalize_ohlcv()                             [domain/ohlcv]
  ↓
normalize_mt5_bar_index()                     [runtime_truth — broker TZ skew]
  ↓
ParquetCache.write/read                       [data/*.parquet, gitignored]
  ↓
DataStage.get_ohlcv() → ctx.raw_ohlcv
  ↓
IndicatorStage → ctx.enriched_ohlcv
```

**Evidence:** `tradingbot/adapters/mt5_market_data.py`; `tradingbot/pipeline/data_stage.py`

## Primary Adapter

| Field | Value |
|-------|-------|
| **Class** | `Mt5MarketDataAdapter` |
| **Port** | `IMarketDataProvider` |
| **Connection** | Attach-only; holds IPC lock for process lifetime |
| **Default fetch** | `FETCH_BARS` / `fetch_bars` ~3000 max; DataStage uses PA `FETCH_BARS` (300) |

## Symbol Resolution

Canonical config symbol: `XAUUSD_i`  
Broker symbol resolved via `resolve_broker_symbol()` in adapters.

**Evidence:** `live.py::PRIMARY_SYMBOL`; `adapters/symbols.py`

## Timeframes

### Supported in adapter mapping

`1m`, `5m`, `15m`, `30m`, `1h`, `4h`, `1d` → MT5 constants

**Evidence:** `mt5_market_data.py::_LEGACY_TF_NAMES`

### Actually used on default live kernel loop

| Timeframe | Role | Status |
|-----------|------|--------|
| **M5** | Signal + pipeline OHLCV | **ACTIVE** |
| **H4** | HTF bias map only | **ACTIVE** (context, not signal TF) |
| M15 | Presets exist; not in kernel loop | **AVAILABLE, not cycled** |
| M1 | Adapter support only | **NOT USED** live default |
| Tick | `symbol_info_tick` at execution/spread | **ACTIVE** for quotes/spread, not OHLCV series |

**Evidence:** `get_live_config()` forces `["5m"]`; `trading_kernel.py::_build_htf_bias_map`

## Caching

| Component | Location | Behavior |
|-----------|----------|----------|
| `ParquetCache` | `data/` (gitignored) | Persists OHLCV per symbol/TF |
| In-memory | Adapter instance | Latest fetched frames |

**Evidence:** `tradingbot/adapters/market_cache.py`

## Data Quality / Staleness

| Mechanism | Purpose |
|-----------|---------|
| `runtime_truth.update_market_data_state` | Bar age tracking |
| `_ReliabilityKernel` | Blocks entries if M5 bar stale |
| `check_mt5_health` | Tick age vs `HEALTH_MAX_TICK_AGE_SEC` (120s default) |

**Evidence:** `runtime_truth.py`; `live_runner.py`; `trading_kernel.py`

## Tick Data

- **Not** used as primary signal input series
- Used for: live spread in RiskGate, execution pricing, health checks
- Research module `ml/research/phase30f` has tick backfill — **NOT on live path**

## Historical / Backtest Data

| Source | Use |
|--------|-----|
| `BacktestMarketData` | Historical bars for backtest engine |
| MT5 fetch in backtest setup | May seed from terminal |
| `data/backtest/*.parquet` | Referenced in legacy docs — **UNKNOWN** current contents |

**Evidence:** `tradingbot/backtest/data_source.py`

## Feature Store

- `tradingbot/ml/features/unified_feature_store.py` — meta-labeler features
- `tradingbot/ml/feature_store.py` — research/offline
- **Not** on default live signal path (PA uses domain PA enrichment)

## Database

Trade journal SQLite separate from OHLCV — see OBSERVABILITY.md.

## Active Components

`Mt5MarketDataAdapter`, parquet cache, OHLCV normalization, M5 live fetch, H4 bias fetch.

## Disabled / Unused on Default Live

- M1/M15/H4 as signal cycle timeframes
- Tick streaming pipeline
- ML PipelineCache dataset warm (ML kernel off)

## Unknowns

- Parquet files on operator disk
- Broker-specific bar timestamp skew magnitude (calibrated at startup)

## Change Impact

`tradingbot/adapters/mt5_market_data.py`, `market_cache.py`, `domain/ohlcv.py`, `services/runtime_truth.py`, `config/live.py`

## Verification

Read `Mt5MarketDataAdapter.update_all`, `get_ohlcv`, `DataStage.run`.

# Phase 8.0 — Historical ML Data Collection

Production-grade historical candle collection for the offline ML pipeline. This phase is **data only** — no live trading, no order execution, no ML model integration.

## Safety limitations

- MT5 usage is **read-only**: `copy_rates_range`, `copy_rates_from_pos`, `copy_ticks_range`, `symbol_info_tick`
- Does **not** import or modify: `TradingKernel`, `RiskGate`, `ExecutionStage`, `mt5_execution`
- Does **not** send orders or enable live trading
- Extends the existing Phase 1 `MLDataPipeline` — no parallel pipeline

## Folder structure

```
data/ml/
├── raw/
│   └── candles/
│       ├── m5/XAUUSD_m5.parquet
│       ├── m15/XAUUSD_m15.parquet
│       └── h4/XAUUSD_h4.parquet
├── metadata/
│   ├── XAUUSD_M5_metadata.json
│   ├── XAUUSD_M15_metadata.json
│   ├── XAUUSD_H4_metadata.json
│   └── collection_runs/
│       └── {run_id}.json
├── processed/          (Phase 2+)
├── datasets/           (Phase 3+)
└── reports/
```

## How to collect history

### Prerequisites

Set MT5 credentials (read-only terminal access):

```powershell
$env:MT5_LOGIN = "your_login"
$env:MT5_PASSWORD = "your_password"
$env:MT5_SERVER = "your_server"
```

### Full historical backfill (365 days)

```powershell
python scripts/collect_ml_data.py `
  --symbol XAUUSD `
  --historical `
  --days 365 `
  --timeframes M5,M15,H4
```

### Date-range collection

```powershell
python scripts/collect_ml_data.py `
  --symbol XAUUSD `
  --historical `
  --start-date 2024-01-01 `
  --end-date 2025-01-01 `
  --timeframes M5,M15,H4
```

### Incremental update

Resumes from `last_update_utc` in metadata:

```powershell
python scripts/collect_ml_data.py `
  --symbol XAUUSD `
  --incremental `
  --timeframes M5,M15,H4
```

### Validate stored data only

```powershell
python scripts/collect_ml_data.py `
  --symbol XAUUSD `
  --validate-only `
  --timeframes M5,M15,H4
```

## Collection flow

```
MT5 (read-only)
      │
HistoricalCandleFetcher
      │
normalize_ohlcv()
      │
validation gate
      │
CandleStore.merge_store()
      │
MetadataStore.update_candles()
      │
CollectionRunManifest + SHA256 fingerprint
```

## Manifest explanation

Each collection run writes `data/ml/metadata/collection_runs/{run_id}.json`:

| Field | Description |
|-------|-------------|
| `run_id` | Unique collection run identifier |
| `timestamp` | UTC ISO time of run completion |
| `git_commit` | Repository commit hash (if available) |
| `symbol` | e.g. `XAUUSD` |
| `timeframes` | TFs collected in this run |
| `source` | Always `mt5_read_only` |
| `date_start` / `date_end` | Requested collection window |
| `bars_fetched` | Bars downloaded per TF in this run |
| `validation_status` | `pass`, `partial`, or `fail` |
| `raw_files` | Paths to stored parquet files |
| `fingerprint` | SHA256 hash per raw parquet file |
| `rejected` | TFs that failed validation (not stored) |
| `incremental` | Whether this was an incremental run |

## Validation rules

Before persisting raw candles, the storage gate requires:

- No duplicate timestamps
- No NaN in OHLC columns
- `high >= max(open, close)`
- `low <= min(open, close)`
- Chronological index order
- Minimum bar counts:

| Timeframe | Minimum bars |
|-----------|--------------|
| M5 | 50,000 |
| M15 | 20,000 |
| H4 | 5,000 |

If validation fails, data is **not** written to disk for that timeframe.

## Incremental updates

1. Read `data/ml/metadata/XAUUSD_{TF}_metadata.json`
2. Use `last_update_utc` as the start of the next fetch window
3. Fetch through current UTC time
4. Merge into existing parquet via `CandleStore.merge_store()`
5. Update metadata and append a new collection manifest

If no metadata exists, incremental mode falls back to `--days` (default 365).

## Architecture timeframes

| TF | Role |
|----|------|
| H4 | Market bias |
| M15 | Context validation |
| M5 | Entry execution reference |
| M1 | Data collection only (Phase 1 legacy collector — **historical**; not current `BacktestConfig` default) |

Phase 8.0 historical collection defaults to **M5, M15, H4**.

## Related commands (not Phase 8.0)

```powershell
# Phase 1 snapshot collector (bar-count limited)
python scripts/collect_ml_data.py --symbol XAUUSD

# Status report
python scripts/collect_ml_data.py --report --symbol XAUUSD

# Phase 2+ (do not run until raw data validated)
python scripts/collect_ml_data.py --features --symbol XAUUSD
python scripts/collect_ml_data.py --dataset --symbol XAUUSD
```

## Modules added in Phase 8.0

| Module | Purpose |
|--------|---------|
| `historical_fetcher.py` | `HistoricalCandleFetcher` — range/chunk/incremental fetch |
| `collection_manifest.py` | Run manifests in `metadata/collection_runs/` |
| `collection_validation.py` | Pre-storage validation gate |
| `raw_fingerprint.py` | SHA256 fingerprints for raw parquet |

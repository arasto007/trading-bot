# Phase 8.1 — Production Dataset Build

Build the first production labeled ML dataset from Phase 8.0 raw candles using existing Phase 2–3 components. **No MT5, no training, no execution.**

## Prerequisites

1. Phase 8.0 historical collection completed and validated:

```powershell
python scripts/collect_ml_data.py --symbol XAUUSD --validate-only --timeframes M5,M15,H4
```

2. Minimum raw bar counts:

| Timeframe | Minimum |
|-----------|---------|
| M5 | 50,000 |
| M15 | 20,000 |
| H4 | 5,000 |

## Commands

### Preflight only

```powershell
python scripts/build_ml_dataset.py --symbol XAUUSD --timeframe M5 --preflight-only
```

Checks:
- Raw candles exist for M5, M15, H4
- Minimum bar counts met
- At least 30 days of overlapping history across timeframes

### Full production build

```powershell
python scripts/build_ml_dataset.py --symbol XAUUSD --timeframe M5 --build
```

Flow:

```
preflight
  → extract events (M5, M15)
  → build features (M5 anchor + H4/M15 context)
  → build labeled dataset
  → hardening (statistics, label quality, leakage audit)
  → validation gate
  → fingerprint + manifest
```

### Validate existing dataset

```powershell
python scripts/build_ml_dataset.py --symbol XAUUSD --timeframe M5 --validate-only
```

## Output artifacts

| Artifact | Path |
|----------|------|
| Labeled dataset | `data/ml/datasets/XAUUSD_M5_dataset.parquet` |
| Build manifest | `data/ml/metadata/XAUUSD_M5_dataset_build.json` |
| Quality report | `data/ml/reports/XAUUSD_M5_dataset_quality.json` |
| Leakage audit | `data/ml/reports/XAUUSD_M5_dataset_leakage_audit.json` |
| Statistics | `data/ml/reports/XAUUSD_M5_dataset_statistics.json` |
| Features | `data/ml/processed/features/m5/XAUUSD_m5_features.parquet` |
| Events | `data/ml/raw/events/{M5,M15}/XAUUSD_{TF}_events.jsonl` |

## Expected dataset schema

~66 columns:
- 21 meta columns (`timestamp`, `label`, `split`, `event_type`, TP/SL fields, …)
- 45 feature columns from the registry
- `dataset_schema_version = 1.0`

Split values: `train` | `validation` | `test` | `purge` (purge excluded from training)

## Labeling defaults

| Parameter | Value |
|-----------|-------|
| Risk unit | ATR(14) at entry |
| SL | 1R |
| TP | 2R |
| Future window | 72 M5 bars (6 hours) |
| Purge gap | 72 bars between splits |

## Safety

- Does not import or modify TradingKernel, RiskGate, or execution layer
- Does not connect to MT5
- Does not train models
- Reuses existing `FeatureBuilder`, `DatasetBuilder`, and hardening modules

## Modules added in Phase 8.1

| Module | Purpose |
|--------|---------|
| `tradingbot/ml/dataset/preflight.py` | Raw data readiness checks |
| `tradingbot/ml/dataset/production_builder.py` | Full build orchestration |
| `scripts/build_ml_dataset.py` | CLI entry point |

## Legacy command (still available)

```powershell
python scripts/collect_ml_data.py --dataset --symbol XAUUSD
```

Phase 8.1 `build_ml_dataset.py --build` adds preflight gating and structured production output.

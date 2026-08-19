# Phase 8.2 — Dataset Quality & Research Audit

Analyze the production dataset built by Phase 8.1 **before any model training**. This phase is offline research and validation only.

## Purpose

- Validate schema and label balance
- Measure feature quality (missing rate, variance, correlation, mutual information)
- Break down performance by session and market regime
- Research alternative label parameters (simulation only)
- Freeze validated datasets as immutable releases with SHA256 fingerprints

**No MT5, no training, no live trading paths.**

## Prerequisites

Phase 8.1 dataset on disk:

```powershell
python scripts/build_ml_dataset.py --symbol XAUUSD --timeframe M5 --build
```

## Workflow

```
Load dataset (DatasetStore)
    → schema validation
    → label distribution analysis
    → feature quality analysis
    → session analysis
    → regime analysis
    → label parameter research (simulation)
    → fingerprint
    → research audit report
    → optional release freeze
```

## CLI Usage

### Full research audit

```powershell
python scripts/audit_ml_dataset.py --symbol XAUUSD --timeframe M5 --audit
```

### Feature quality only

```powershell
python scripts/audit_ml_dataset.py --symbol XAUUSD --timeframe M5 --features
```

### Freeze release

Runs audit first; fails if audit status is `fail`.

```powershell
python scripts/audit_ml_dataset.py --symbol XAUUSD --timeframe M5 --release --version 1
```

## Report Locations

All reports under `data/ml/reports/`:

| Report | Path pattern |
|--------|----------------|
| Research audit | `XAUUSD_M5_research_audit.json` |
| Label quality | `XAUUSD_M5_label_quality.json` |
| Feature quality | `XAUUSD_M5_m5_feature_quality.json` |
| Session | `XAUUSD_M5_session_report.json` |
| Regime | `XAUUSD_M5_regime_report.json` |
| Label research | `XAUUSD_M5_label_research_report.json` |

## Release Layout

Frozen releases under `data/ml/releases/`:

```
XAUUSD_M5_v1/
    dataset.parquet
    fingerprint.json      # SHA256 + dataset/feature hashes
    feature_schema.json   # 45 registered features
    label_config.json     # ATR window, R multiples, purge bars
    research_report.json  # full audit snapshot
```

Release folders are immutable — creating the same version twice raises `FileExistsError`.

## Label Balance Status

| Status | TP win rate (resolved labels) |
|--------|-------------------------------|
| healthy | 45%–55% |
| acceptable | 35%–65% |
| warning | outside range |

## Label Research

Simulates (does **not** modify stored labels):

- Future windows: 36, 72, 120 bars
- ATR periods: 14, 20, 50

Requires raw M5 candles in `data/ml/raw/candles/` for simulation.

## Acceptance Criteria

- Dataset audit engine (`DatasetResearchAudit`) exists
- Feature, label, session, and regime reports generated
- Release system with SHA256 fingerprint
- No ML training performed
- No MT5 / kernel / risk / execution dependencies
- Phase 8.0, 8.1, and full test suite remain green

## Modules

| Module | Role |
|--------|------|
| `research_audit.py` | Orchestration |
| `label_analysis.py` | Class distribution and balance |
| `feature_analysis.py` | Per-feature quality metrics |
| `session_analysis.py` | Asia / London / NY breakdown |
| `regime_analysis.py` | Volatility, trend, H4 bias buckets |
| `label_research.py` | Alternative label config simulation |
| `release_manager.py` | Immutable release packaging |

"""Phase 22L — Step 1: dataset_v2 generation pipeline audit."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.data.paths import dataset_v2_path, normalize_ml_base_dir
from tradingbot.ml.dataset.store import DatasetStore


def audit_dataset_generation_pipeline(*, base_dir: str | None = None) -> dict[str, Any]:
    """Repository-driven audit — no production writes."""
    from tradingbot.adapters.legacy_loader import load_legacy_config, project_root
    from tradingbot.ml.data.stores.candle_store import CandleStore
    from tradingbot.ml.data.historical_quality_validator import production_date_range

    legacy = load_legacy_config()
    base_dir = normalize_ml_base_dir(base_dir or legacy.get("BASE_DIR"))
    symbol, tf = "XAUUSD", "M5"

    old = DatasetStore(base_dir).load_v2(symbol, tf)
    manifest_path = Path(project_root()) / "data" / "ml" / "metadata" / f"{symbol}_{tf}_V2_dataset_build.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}

    m5 = CandleStore(base_dir).load(symbol, tf)
    m5_max = None
    if m5 is not None and not m5.empty:
        idx = pd.to_datetime(m5.index, utc=True)
        m5_max = str(idx.max())

    ds_max = None
    if old is not None and not old.empty and "timestamp" in old.columns:
        ds_max = str(pd.to_datetime(old["timestamp"], utc=True).max())

    start, end = production_date_range()

    return {
        "phase": "22L",
        "step": 1,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "entry_script": "scripts/build_ml_dataset.py",
        "primary_commands": {
            "full_production_build": "python scripts/build_ml_dataset.py --phase9-1",
            "v2_only": "python scripts/build_ml_dataset.py --build-v2",
            "v2_rebuild_source": "python scripts/build_ml_dataset.py --build-v2 --rebuild-source",
            "finalize_patch_spread": "python scripts/build_ml_dataset.py --phase9-finalize",
        },
        "pipeline_chain": [
            {
                "stage": "preflight",
                "module": "tradingbot.ml.dataset.phase9_production_build.Phase91ProductionBuilder.run_preflight_checks",
                "inputs": ["CandleStore M5/M15/H4", "HistoricalQualityValidator"],
            },
            {
                "stage": "sparse_v1_build",
                "module": "tradingbot.ml.dataset.sparse_event_builder.SparseEventDatasetBuilder.build",
                "inputs": [
                    "CandleStore M5/M15/H4 (production_date_range 5Y window)",
                    "extract_market_events + session transitions",
                    "FeatureBuilder.compute_at per event bar",
                    "label_from_future_candles",
                ],
                "output": "data/ml/datasets/XAUUSD_M5_dataset.parquet (v1 labeled sparse events)",
            },
            {
                "stage": "v2_hardening",
                "module": "tradingbot.ml.dataset.production_dataset_v2.ProductionDatasetV2Builder.build_v2",
                "inputs": ["v1 dataset or DatasetBuilder fallback"],
                "operations": ["DatasetSanityGate.filter", "assign_purged_split_column", "validate", "train_readiness"],
                "output": "data/ml/datasets/XAUUSD_M5_dataset_v2.parquet",
            },
        ],
        "feature_engineering": {
            "builder": "tradingbot.ml.features.builder.FeatureBuilder",
            "mode": "event_sparse — features computed only at sampling events, not every M5 bar",
            "phase99_columns": ["ema50_slope", "candle_direction", "structure_distance"],
            "inference_merge": "build_unified_frame left-joins dataset_v2 on exact timestamp → fillna(0.0)",
        },
        "data_sources": {
            "candles": "data/ml/raw/candles/{M5,M15,H4}/ or legacy data/ml/candles/",
            "events": "extracted from candles via market_event_extractor (not live MT5 at inference)",
            "spread": "bar-range proxy when spread store unavailable",
            "production_window": {"start_utc": start.isoformat(), "end_utc": end.isoformat(), "days": 1825},
        },
        "current_artifacts": {
            "dataset_v2_path": str(dataset_v2_path(symbol, tf, base_dir)),
            "row_count": int(len(old)) if old is not None else 0,
            "max_timestamp": ds_max,
            "build_manifest": str(manifest_path) if manifest_path.is_file() else None,
            "last_build_utc": manifest.get("build_timestamp_utc"),
            "m5_candle_max_timestamp": m5_max,
        },
        "live_update_mechanism": {
            "automatic_on_live_loop": False,
            "evidence": "No DatasetStore.store_v2 call in TradingKernel, PipelineCache, or live runner paths",
            "manual_trigger": "scripts/build_ml_dataset.py --phase9-1 (operator-initiated batch build)",
            "inference_reads": "PipelineCache.get_unified_frame → DatasetStore.load_v2 (read-only at runtime)",
        },
        "why_stopped_at_2026_06_29": {
            "primary_reason": "Last manual Phase 9.1 build timestamp 2026-06-29T16:46:56 UTC — no subsequent rebuild",
            "secondary_reason": "M5 CandleStore max 2026-06-29T13:50 UTC — sparse dataset cannot extend beyond candle history",
            "not_a_pipeline_crash": True,
            "live_expected_to_refresh": False,
        },
        "architectural_note": "dataset_v2 is event-sparse (~5724 rows); unified frame merges on exact timestamp so non-event M5 bars always get fillna(0) for phase99_*",
    }

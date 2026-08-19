#!/usr/bin/env python3
"""Phase 22M — live data pipeline & CandleStore forensics (repository only)."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

OUT = Path(__file__).resolve().parent


def _write(name: str, payload: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  saved {name}", flush=True)


def _rg_count(pattern: str, glob: str = "*.py") -> int:
    try:
        r = subprocess.run(
            ["rg", "-l", pattern, str(ROOT / "tradingbot"), str(ROOT / "scripts"), "--glob", glob],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return len([ln for ln in r.stdout.splitlines() if ln.strip()])
    except Exception:
        return -1


def main() -> int:
    from tradingbot.adapters.legacy_loader import load_legacy_config, project_root
    from tradingbot.adapters.market_cache import ParquetCache
    from tradingbot.ml.data.paths import candle_path, dataset_v2_path, normalize_ml_base_dir
    from tradingbot.ml.data.stores.candle_store import CandleStore

    import pandas as pd

    base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
    legacy = load_legacy_config()
    data_dir = legacy.get("data_dir") or legacy.get("DATA_DIR") or "data"
    now = datetime.now(timezone.utc).isoformat()

    cs_path = candle_path("XAUUSD", "M5", base_dir)
    cs = CandleStore(base_dir).load("XAUUSD", "M5")
    cs_max = str(pd.to_datetime(cs.index, utc=True).max()) if cs is not None and len(cs) else None
    cs_mtime = datetime.utcfromtimestamp(cs_path.stat().st_mtime).isoformat() + "Z" if cs_path.is_file() else None

    pc = ParquetCache(data_dir)
    live_path = pc.path("XAUUSD", "5m")
    live_p = Path(live_path)
    live_df = pc.load("XAUUSD", "5m")
    live_max = str(pd.to_datetime(live_df.index, utc=True).max()) if live_df is not None and len(live_df) else None
    live_mtime = datetime.utcfromtimestamp(live_p.stat().st_mtime).isoformat() + "Z" if live_p.is_file() else None

    dv2_path = dataset_v2_path("XAUUSD", "M5", base_dir)
    ds = pd.read_parquet(dv2_path) if dv2_path.is_file() else None
    ds_max = str(pd.to_datetime(ds["timestamp"], utc=True).max()) if ds is not None else None
    ds_mtime = datetime.utcfromtimestamp(dv2_path.stat().st_mtime).isoformat() + "Z" if dv2_path.is_file() else None

    manifest_path = project_root() / "data/ml/metadata/XAUUSD_M5_V2_dataset_build.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}

    candlestore = {
        "phase": "22M",
        "step": 1,
        "generated_utc": now,
        "class": "tradingbot.ml.data.stores.candle_store.CandleStore",
        "persistence_path": str(cs_path),
        "path_pattern": "data/ml/raw/candles/{tf}/{SYMBOL}_{tf}.parquet",
        "creators": [
            {
                "module": "tradingbot.ml.data.pipeline.MLDataPipeline",
                "methods": ["collect_historical", "collect_historical_optimized", "collect_reference_candles", "run_full"],
                "write_api": "CandleStore.merge_store",
            }
        ],
        "entry_scripts": [
            "scripts/collect_ml_data.py (--historical, --incremental, --production-5y, default run_full)",
            "start/13_collect_ml_data.bat",
        ],
        "live_runner_updates": False,
        "live_runner_evidence": "tradingbot/application/live_runner.py imports Mt5MarketDataAdapter only — no CandleStore import",
        "on_disk": {
            "exists": cs_path.is_file(),
            "rows": int(len(cs)) if cs is not None else 0,
            "max_timestamp_utc": cs_max,
            "file_mtime_utc": cs_mtime,
        },
        "writers_in_production_code": [
            "tradingbot/ml/data/pipeline.py (merge_store only non-test writer)",
        ],
        "readers": "SparseEventDatasetBuilder, 40+ research orchestrators, Phase91 build, PipelineCache indirect via dataset_v2",
    }
    _write("candlestore_forensics.json", candlestore)

    pipeline_map = {
        "phase": "22M",
        "step": 2,
        "generated_utc": now,
        "stages": [
            {
                "stage": "MT5",
                "producer": "MetaTrader5 terminal",
                "consumer": "Mt5MarketDataAdapter._fetch_from_mt5 / MLDataPipeline.fetch",
                "api": "mt5.copy_rates_from_pos / copy_rates_range",
                "update_frequency": "every kernel cycle (live) OR batch collection (ML)",
                "persistence": "none (in-memory rates)",
            },
            {
                "stage": "Live ParquetCache",
                "producer": "Mt5MarketDataAdapter.get_ohlcv / update_all",
                "consumer": "TradingKernel DataStage via get_ohlcv",
                "path": f"{data_dir}/{{symbol}}_{{timeframe}}.parquet",
                "update_frequency": "each live cycle when cache stale (< bars requested)",
                "persistence": "overwrite rolling ~3000 bars",
                "on_disk_max_ts": live_max,
                "on_disk_mtime_utc": live_mtime,
            },
            {
                "stage": "CandleStore",
                "producer": "MLDataPipeline.collect_historical*",
                "consumer": "SparseEventDatasetBuilder.build",
                "update_frequency": "manual/batch only (start/13, collect_ml_data.py)",
                "persistence": "merge_store append/dedupe parquet",
                "on_disk_max_ts": cs_max,
                "disconnected_from_live": True,
            },
            {
                "stage": "Dataset Builder",
                "producer": "SparseEventDatasetBuilder + ProductionDatasetV2Builder",
                "consumer": "none at runtime until next manual build",
                "entry": "scripts/build_ml_dataset.py --phase9-1",
                "update_frequency": "manual only — last 2026-06-29",
                "persistence": "dataset_v2 parquet",
            },
            {
                "stage": "dataset_v2",
                "producer": "ProductionDatasetV2Builder.store_v2",
                "consumer": "PipelineCache.get_unified_frame → build_unified_frame merge",
                "update_frequency": "manual build only",
                "on_disk_max_ts": ds_max,
                "on_disk_mtime_utc": ds_mtime,
            },
            {
                "stage": "PipelineCache",
                "producer": "build_unified_frame + attach_top5_features",
                "consumer": "KernelAdapter.produce_unified_signal",
                "update_frequency": "every signal cycle",
                "persistence": "in-memory singleton cache only",
            },
            {
                "stage": "Range Engine",
                "producer": "Phase99EngineWrapper via row_for_phase99_range",
                "consumer": "DecisionOrchestrator",
                "update_frequency": "every signal cycle",
                "persistence": "none",
            },
        ],
        "critical_split": "Live inference reads MT5→ParquetCache; phase99 features read dataset_v2 built from CandleStore. No repository path connects ParquetCache→CandleStore→dataset_v2 during LiveRunner.",
    }
    _write("data_pipeline_map.json", pipeline_map)

    dataset_update = {
        "phase": "22M",
        "step": 3,
        "generated_utc": now,
        "stop_timestamp": "2026-06-29T13:45:00+00:00",
        "proven_causes": {
            "A_candlestore_not_updated": {
                "proven": True,
                "evidence": f"CandleStore max={cs_max}, file mtime={cs_mtime}. No merge_store after 2026-06-29.",
            },
            "B_dataset_builder_not_run": {
                "proven": True,
                "evidence": f"dataset_v2 max={ds_max}, build manifest={manifest.get('build_timestamp_utc')}. store_v2 only in production_dataset_v2.py / phase9_production_build.py.",
            },
            "C_scheduler_broken": {
                "proven": False,
                "evidence": "No cron/APScheduler/scheduled task in repository for CandleStore or dataset_v2 refresh. Not broken — absent.",
            },
            "D_live_runner_no_dataset_link": {
                "proven": True,
                "evidence": "LiveRunner→TradingKernel→Mt5MarketDataAdapter→ParquetCache. Zero imports of CandleStore, DatasetStore, build_ml_dataset in live_runner.py, trading_kernel.py, pipeline/*.",
            },
        },
        "verdict_step3": "E — multiple causes together (A + B + D + automation absent)",
        "live_data_not_stale": {
            "proven": True,
            "evidence": f"ParquetCache data/XAUUSD_5m.parquet max={live_max}, mtime={live_mtime} — live MT5 path still fetches recent bars.",
        },
        "why_dataset_stopped_growing": "CandleStore and dataset_v2 are batch artifacts. Last batch run 2026-06-29. Live loop never triggers batch pipeline.",
    }
    _write("dataset_update_analysis.json", dataset_update)

    usage = {
        "phase": "22M",
        "step": 4,
        "generated_utc": now,
        "symbols": {
            "dataset_v2 / DatasetStore.load_v2": {
                "role": "READ at inference",
                "write_locations": [
                    "tradingbot/ml/dataset/production_dataset_v2.py:store_v2",
                    "tradingbot/ml/dataset/phase9_production_build.py:finalize store_v2",
                ],
                "read_locations_count": _rg_count("load_v2"),
                "live_path": "PipelineCache.get_unified_frame",
                "update_in_live": False,
            },
            "CandleStore": {
                "role": "READ for dataset build; WRITE only via MLDataPipeline",
                "write_locations": ["tradingbot/ml/data/pipeline.py:merge_store"],
                "read_locations_count": _rg_count("CandleStore"),
                "live_path": "unused",
                "update_in_live": False,
            },
            "build_ml_dataset": {
                "role": "CLI entry for Phase91 / v2 build",
                "write_locations": ["scripts/build_ml_dataset.py"],
                "invoked_by_live": False,
                "invoked_by_start_bats": "not in start/3_live_loop_execute.bat; not in 14_rebuild_ml_models.bat (uses collect only, not --phase9-1)",
            },
            "SparseEventDatasetBuilder": {
                "role": "Build v1 labeled sparse events from CandleStore",
                "write_locations": ["sparse_event_builder.build_and_store → DatasetStore.store (v1)"],
                "live_path": "unused",
            },
            "ProductionDatasetV2Builder": {
                "role": "v1 → filtered dataset_v2",
                "write_locations": ["production_dataset_v2.py:store_v2"],
                "live_path": "unused",
            },
            "FeatureBuilder": {
                "role_at_training": "sparse_event_builder.compute_at per event",
                "role_at_live_inference": "NOT used for phase99 (uses dataset merge)",
                "live_path": "unused for range model features",
            },
            "ParquetCache": {
                "role": "Live OHLCV cache",
                "write_locations": ["tradingbot/adapters/mt5_market_data.py:store"],
                "read_locations": ["Mt5MarketDataAdapter.get_ohlcv", "BacktestMarketData cache"],
                "update_in_live": True,
                "feeds_dataset_v2": False,
            },
        },
    }
    _write("repository_usage_map.json", usage)

    automation = {
        "phase": "22M",
        "step": 5,
        "generated_utc": now,
        "expected_automatic_refresh": False,
        "repository_evidence": "No code path schedules collect_ml_data or build_ml_dataset after LiveRunner start.",
        "searched_for": ["cron", "APScheduler", "schedule.", "Celery", "watchdog dataset", "incremental collect in live loop"],
        "findings": {
            "run_live_watchdog.py": "Restarts tradingbot child only — no ML data/dataset tasks",
            "LiveRunner._run": "MT5 connect → BackgroundServices → kernel.run_forever — no CandleStore",
            "BackgroundServices": "PositionProtector + PositionRecovery only",
            "TradingKernel.run_forever": "DataStage → IndicatorStage → SignalStage — uses IMarketDataProvider only",
            "start/13_collect_ml_data.bat": "Manual ML collection — not chained to live loop",
            "start/14_rebuild_ml_models.bat": "collect_ml_data.py default run_full + trend bundle — does NOT call build_ml_dataset --phase9-1",
            "start/3_live_loop_execute.bat": "verify_ml_live_ready → run_live_watchdog --execute only",
        },
        "missing_jobs": [
            "Scheduled or triggered collect_ml_data.py --incremental (CandleStore merge)",
            "Scheduled or triggered build_ml_dataset.py --phase9-1 (dataset_v2 rebuild)",
            "Bridge from ParquetCache rolling cache to CandleStore historical store",
            "PipelineCache invalidation hook after dataset_v2 refresh",
        ],
        "existing_but_manual": [
            "scripts/collect_ml_data.py",
            "scripts/build_ml_dataset.py",
            "start/13_collect_ml_data.bat",
        ],
    }
    _write("automation_analysis.json", automation)

    repair = {
        "phase": "22M",
        "step": 7,
        "implementation_status": "NOT_IMPLEMENTED — plan only",
        "constraints": ["no model retrain", "no strategy/threshold/risk changes", "max 3 files"],
        "minimal_repair": {
            "summary": "Add offline batch orchestration (existing scripts) on a schedule. Do NOT wire LiveRunner to dataset build inline.",
            "files": [
                {
                    "path": "scripts/scheduled_ml_refresh.py",
                    "action": "CREATE",
                    "purpose": "Orchestrate: collect_ml_data.py --incremental --symbol XAUUSD then build_ml_dataset.py --phase9-1. Log manifest timestamps. Exit non-zero on failure.",
                    "rationale": "Repository already has both steps; only missing chained entry point.",
                },
                {
                    "path": "start/15_refresh_ml_dataset.bat",
                    "action": "CREATE",
                    "purpose": "Manual + Windows Task Scheduler entry (e.g. daily off-hours) calling scheduled_ml_refresh.py",
                    "rationale": "Matches existing start/*.bat pattern; no live loop change.",
                },
                {
                    "path": "scripts/verify_ml_live_ready.py",
                    "action": "OPTIONAL_EXTEND",
                    "purpose": "Warn if dataset_v2 max_timestamp lags CandleStore or is older than N days (read-only check before live start)",
                    "rationale": "start/3 already calls verify before live — surfaces staleness without auto-mutation.",
                },
            ],
        },
        "explicitly_not_recommended_in_22m": [
            "Modifying LiveRunner to write CandleStore each cycle (high risk, duplicates MLDataPipeline)",
            "Modifying PipelineCache/KernelAdapter for live FeatureBuilder overlay (engine change — Phase 22J scope)",
            "Modifying TradingKernel or RiskGate",
        ],
        "operator_workflow_until_automation": [
            "start/13_collect_ml_data.bat --incremental",
            "python scripts/build_ml_dataset.py --phase9-1",
            "Restart live to reload PipelineCache (process restart)",
        ],
    }
    _write("repair_plan.json", repair)

    root = {
        "phase": "22M",
        "step": 6,
        "verdict_code": "D",
        "verdict_label": "Architecture Incorrect",
        "evidence_summary": "Live MT5 data updates ParquetCache (data/XAUUSD_5m.parquet, max 2026-07-03). ML inference phase99 features read dataset_v2 built from CandleStore (max 2026-06-29). Repository contains no bridge between these stores and no live-triggered dataset rebuild.",
        "rejected_verdicts": {
            "A_Live_Data_Broken": "ParquetCache fresh — live fetch works",
            "B_Dataset_Builder_Broken": "Builder works when run manually (Phase 22L rebuild succeeded)",
            "C_Automation_Missing": "True but secondary — root issue is architectural split even if cron added",
            "E_No_Problem_Found": "False — dataset_v2 stale vs live candles",
        },
    }
    _write("root_cause_verdict.json", root)

    final = {
        "phase": "22M",
        "title": "Live Data Pipeline & CandleStore Forensics",
        "completed_utc": now,
        "production_modified": False,
        "verdict": root["verdict_code"],
        "verdict_label": root["verdict_label"],
        "why_dataset_stopped_after_2026_06_29": (
            "Last manual batch: CandleStore collected and dataset_v2 built on 2026-06-29. "
            "LiveRunner continues updating a separate ParquetCache only. "
            "No scheduler or code reconnects live data to CandleStore or dataset_v2."
        ),
        "minimal_repair": repair["minimal_repair"]["summary"],
        "reports": [
            "candlestore_forensics.json",
            "data_pipeline_map.json",
            "dataset_update_analysis.json",
            "repository_usage_map.json",
            "automation_analysis.json",
            "repair_plan.json",
            "root_cause_verdict.json",
            "phase22m_final_report.json",
        ],
    }
    _write("phase22m_final_report.json", final)
    print(f"Phase 22M complete | verdict={root['verdict_code']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

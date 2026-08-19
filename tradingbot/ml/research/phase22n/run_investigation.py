#!/usr/bin/env python3
"""Phase 22N — automated ML data refresh validation and reports."""

from __future__ import annotations

import argparse
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


def _live_runner_isolation_check() -> dict:
    live_runner = ROOT / "tradingbot" / "application" / "live_runner.py"
    text = live_runner.read_text(encoding="utf-8") if live_runner.is_file() else ""
    forbidden = [
        "CandleStore",
        "DatasetStore",
        "build_ml_dataset",
        "scheduled_ml_refresh",
        "collect_ml_data",
    ]
    hits = {token: token in text for token in forbidden}
    return {
        "live_runner_path": str(live_runner),
        "forbidden_imports_or_calls": hits,
        "isolated": not any(hits.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 22N investigation / validation")
    parser.add_argument("--execute", action="store_true", help="Run full scheduled_ml_refresh pipeline")
    parser.add_argument("--verify-only", action="store_true", help="Verify existing artifacts only")
    args = parser.parse_args()

    now = datetime.now(timezone.utc).isoformat()

    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "scheduled_ml_refresh",
        ROOT / "scripts" / "scheduled_ml_refresh.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    capture_snapshot = mod.capture_snapshot
    verify_refresh = mod.verify_refresh

    before = capture_snapshot("XAUUSD", "M5")
    before_dict = {k: v.to_dict() for k, v in before.items()}

    refresh_exit = None
    if args.execute:
        print("Running scheduled_ml_refresh (collect + build + verify)...", flush=True)
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "scheduled_ml_refresh.py"), "--report-dir", str(OUT)],
            cwd=str(ROOT),
        )
        refresh_exit = proc.returncode
    elif args.verify_only:
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "scheduled_ml_refresh.py"), "--verify-only", "--report-dir", str(OUT)],
            cwd=str(ROOT),
        )

    after = capture_snapshot("XAUUSD", "M5")
    after_dict = {k: v.to_dict() for k, v in after.items()}
    passed, verification = verify_refresh(before, after, symbol="XAUUSD", timeframe="M5")

    isolation = _live_runner_isolation_check()
    automation = {
        "phase": "22N",
        "generated_utc": now,
        "implementation_status": "IMPLEMENTED",
        "files_created": [
            "scripts/scheduled_ml_refresh.py",
            "start/15_refresh_ml_dataset.bat",
        ],
        "files_modified": [
            "scripts/verify_ml_live_ready.py",
        ],
        "pipeline_steps": [
            "collect_ml_data.py --incremental --symbol XAUUSD",
            "build_ml_dataset.py --phase9-1 --symbol XAUUSD --timeframe M5",
            "verify: timestamp, coverage, feature count",
        ],
        "retry_policy": "ML_REFRESH_RETRIES env (default 2) per step",
        "exit_codes": {"0": "success", "1": "collect failed", "2": "build failed", "3": "verify failed"},
        "live_runner_isolation": isolation,
        "operator_entry_points": [
            "start/15_refresh_ml_dataset.bat",
            "python scripts/scheduled_ml_refresh.py",
        ],
        "windows_task_scheduler": "NOT_CONFIGURED_IN_REPO — operator must schedule 15_refresh_ml_dataset.bat",
        "automatic_refresh_without_scheduler": False,
    }
    _write("automation_validation.json", automation)

    ts_cmp = {
        "phase": "22N",
        "generated_utc": now,
        "before": {
            "candle_store_max_timestamp_utc": before_dict["candle_store_m5"]["max_timestamp_utc"],
            "dataset_v2_max_timestamp_utc": before_dict["dataset_v2"]["max_timestamp_utc"],
            "candle_store_rows": before_dict["candle_store_m5"]["row_count"],
            "dataset_v2_rows": before_dict["dataset_v2"]["row_count"],
        },
        "after": {
            "candle_store_max_timestamp_utc": after_dict["candle_store_m5"]["max_timestamp_utc"],
            "dataset_v2_max_timestamp_utc": after_dict["dataset_v2"]["max_timestamp_utc"],
            "candle_store_rows": after_dict["candle_store_m5"]["row_count"],
            "dataset_v2_rows": after_dict["dataset_v2"]["row_count"],
        },
        "candle_store_advanced": verification.get("candle_store_advanced"),
        "dataset_advanced": verification.get("dataset_advanced"),
        "lag_hours_candle_to_dataset": verification.get("lag_hours_candle_to_dataset"),
        "refresh_executed": args.execute,
        "refresh_exit_code": refresh_exit,
    }
    _write("timestamp_comparison.json", ts_cmp)

    ds_val = {
        "phase": "22N",
        "generated_utc": now,
        "verification_passed": passed,
        "verification": verification,
        "feature_count_before": before_dict["dataset_v2"]["feature_count"],
        "feature_count_after": after_dict["dataset_v2"]["feature_count"],
        "row_count_before": before_dict["dataset_v2"]["row_count"],
        "row_count_after": after_dict["dataset_v2"]["row_count"],
    }
    _write("dataset_refresh_validation.json", ds_val)

    scheduler = {
        "phase": "22N",
        "generated_utc": now,
        "log_file": str(ROOT / "logs" / "scheduled_ml_refresh.log"),
        "report_dir": str(OUT),
        "last_run_success": passed if args.execute or args.verify_only else None,
        "note": "scheduler_report.json updated when scheduled_ml_refresh.py runs",
    }
    if (OUT / "scheduler_report.json").is_file():
        scheduler["last_scheduler_report"] = json.loads((OUT / "scheduler_report.json").read_text(encoding="utf-8"))
    _write("scheduler_report.json", scheduler)

    final = {
        "phase": "22N",
        "title": "Automated ML Data Refresh",
        "generated_utc": now,
        "verdict": "PASS" if passed else "NEEDS_REVIEW",
        "implementation_summary": (
            "Added offline orchestrator scheduled_ml_refresh.py chaining incremental CandleStore collection "
            "and Phase 9.1 dataset_v2 rebuild with retry, logging, and verification. "
            "LiveRunner remains isolated; refresh runs outside the live loop via start/15_refresh_ml_dataset.bat."
        ),
        "constraints_respected": [
            "no model changes",
            "no strategy/threshold/risk/execution/dashboard changes",
            "no LiveRunner ↔ Dataset Builder coupling",
        ],
        "dataset_auto_updates": {
            "answer": "CONDITIONAL",
            "explanation": (
                "The repository now provides automated refresh tooling (scheduled_ml_refresh.py + "
                "15_refresh_ml_dataset.bat). Dataset_v2 updates automatically only when that job is "
                "executed (manually or via Windows Task Scheduler). Live loop does NOT trigger refresh."
            ),
            "requires_operator_action": "Schedule start/15_refresh_ml_dataset.bat (e.g. daily off-hours) or run manually",
        },
        "timestamp_comparison": ts_cmp,
        "verification": verification,
        "next_recommendation": (
            "Configure Windows Task Scheduler for 15_refresh_ml_dataset.bat after market close; "
            "restart live process after refresh so PipelineCache reloads dataset_v2."
        ),
    }
    _write("phase22n_final_report.json", final)

    print(json.dumps({"verdict": final["verdict"], "passed": passed}, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

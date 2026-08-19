#!/usr/bin/env python3
"""Phase 22O — pre-live dataset maintenance orchestrator (outside trading loop)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

LOG_DIR = ROOT / "logs"
ORCHESTRATOR_LOG = LOG_DIR / "dataset_orchestrator.log"
DEFAULT_SYMBOL = "XAUUSD"
DEFAULT_TIMEFRAME = "M5"


def _log(msg: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now(timezone.utc).isoformat()} | {msg}"
    print(line, flush=True)
    with ORCHESTRATOR_LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def refresh_threshold_hours() -> float:
    raw = os.environ.get(
        "ML_DATASET_REFRESH_THRESHOLD_HOURS",
        os.environ.get("ML_DATASET_MAX_LAG_HOURS", "48"),
    )
    return float(raw)


def is_auto_refresh_enabled() -> bool:
    return os.environ.get("ML_AUTO_DATASET_REFRESH", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def measure_dataset_lag(
    symbol: str = DEFAULT_SYMBOL,
    timeframe: str = DEFAULT_TIMEFRAME,
) -> dict[str, Any]:
    """Compare dataset_v2 max timestamp vs live ParquetCache (read-only)."""
    import pandas as pd

    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.adapters.market_cache import ParquetCache
    from tradingbot.ml.data.paths import dataset_v2_path, normalize_ml_base_dir

    legacy = load_legacy_config()
    base_dir = normalize_ml_base_dir(legacy.get("BASE_DIR"))
    data_dir = legacy.get("data_dir") or legacy.get("DATA_DIR") or "data"

    result: dict[str, Any] = {
        "symbol": symbol.upper(),
        "timeframe": timeframe.upper(),
        "dataset_path": None,
        "dataset_max_utc": None,
        "live_cache_path": None,
        "live_max_utc": None,
        "lag_hours": None,
        "dataset_exists": False,
        "live_cache_exists": False,
    }

    dv2 = dataset_v2_path(symbol, timeframe, base_dir)
    result["dataset_path"] = str(dv2)
    if not dv2.is_file():
        return result

    result["dataset_exists"] = True
    ds_df = pd.read_parquet(dv2, columns=["timestamp"])
    ds_max = pd.to_datetime(ds_df["timestamp"], utc=True).max()
    result["dataset_max_utc"] = ds_max.isoformat()

    cache = ParquetCache(data_dir)
    live_path = cache.path(symbol, "5m")
    result["live_cache_path"] = live_path
    live_df = cache.load(symbol, "5m")
    if live_df is None or live_df.empty:
        return result

    result["live_cache_exists"] = True
    live_max = pd.to_datetime(live_df.index, utc=True).max()
    result["live_max_utc"] = live_max.isoformat()
    lag_hours = float((live_max - ds_max).total_seconds()) / 3600.0
    result["lag_hours"] = round(lag_hours, 2)
    return result


def needs_refresh(lag_info: dict[str, Any], *, threshold_hours: float | None = None) -> bool:
    threshold = threshold_hours if threshold_hours is not None else refresh_threshold_hours()
    lag = lag_info.get("lag_hours")
    if lag is None:
        return not lag_info.get("dataset_exists", False)
    return float(lag) > threshold


def run_scheduled_refresh(
    *,
    symbol: str = DEFAULT_SYMBOL,
    timeframe: str = DEFAULT_TIMEFRAME,
    report_dir: Path | None = None,
) -> dict[str, Any]:
    """Invoke Phase 22N refresh job (subprocess — isolated from live loop)."""
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "scheduled_ml_refresh.py"),
        "--symbol",
        symbol.upper(),
        "--timeframe",
        timeframe.upper(),
    ]
    if report_dir is not None:
        cmd.extend(["--report-dir", str(report_dir)])

    _log(f"Starting scheduled_ml_refresh: {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=str(ROOT))
    success = proc.returncode == 0
    _log(f"scheduled_ml_refresh finished exit={proc.returncode} success={success}")
    return {
        "exit_code": proc.returncode,
        "success": success,
        "command": cmd,
    }


def run_pre_live_maintenance(
    *,
    symbol: str = DEFAULT_SYMBOL,
    timeframe: str = DEFAULT_TIMEFRAME,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Check dataset lag vs ParquetCache; refresh when above threshold.

    Called once before the first live child process — never inside the trading loop.
    """
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.adapters.mt5_utils import is_mt5_lock_held_by_other, is_refresh_recent
    from tradingbot.ml.integration.config import is_ml_kernel_enabled

    legacy = load_legacy_config()
    started = datetime.now(timezone.utc).isoformat()
    threshold = refresh_threshold_hours()
    report: dict[str, Any] = {
        "phase": "22O",
        "started_utc": started,
        "symbol": symbol.upper(),
        "timeframe": timeframe.upper(),
        "threshold_hours": threshold,
        "auto_refresh_enabled": is_auto_refresh_enabled(),
        "ml_kernel_enabled": is_ml_kernel_enabled(),
        "action": "none",
        "refresh_attempted": False,
        "refresh_success": None,
        "warning": None,
    }

    if not is_ml_kernel_enabled():
        report["action"] = "skipped"
        report["reason"] = "ml_kernel_off"
        _log("Pre-live maintenance skipped — USE_ML_KERNEL=false")
        return report

    if not is_auto_refresh_enabled() and not force:
        report["action"] = "skipped"
        report["reason"] = "ML_AUTO_DATASET_REFRESH disabled"
        _log("Pre-live maintenance skipped — ML_AUTO_DATASET_REFRESH=false")
        return report

    if not force and is_refresh_recent(legacy):
        report["action"] = "skipped"
        report["reason"] = "recent_refresh"
        _log("Pre-live maintenance skipped — candles refreshed recently (cooldown)")
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        return report

    if not force and is_mt5_lock_held_by_other(legacy):
        report["action"] = "skipped"
        report["reason"] = "mt5_lock_held"
        _log("Pre-live maintenance skipped — another process holds MT5 IPC lock")
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        return report

    before = measure_dataset_lag(symbol, timeframe)
    report["before"] = before
    report["needs_refresh"] = needs_refresh(before, threshold_hours=threshold)

    if not report["needs_refresh"] and not force:
        report["action"] = "none"
        _log(
            f"Dataset fresh — lag={before.get('lag_hours')}h threshold={threshold}h — no refresh",
        )
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        return report

    if dry_run:
        report["action"] = "would_refresh"
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        _log(f"Dry-run — would refresh (lag={before.get('lag_hours')}h)")
        return report

    report["action"] = "refresh"
    report["refresh_attempted"] = True
    refresh = run_scheduled_refresh(symbol=symbol, timeframe=timeframe)
    report["refresh"] = refresh
    report["refresh_success"] = refresh["success"]

    after = measure_dataset_lag(symbol, timeframe)
    report["after"] = after

    if refresh["success"]:
        report["action"] = "refreshed"
        _log(
            f"Refresh OK — dataset {before.get('dataset_max_utc')} -> {after.get('dataset_max_utc')}",
        )
    else:
        report["action"] = "refresh_failed_continue"
        report["warning"] = (
            f"scheduled_ml_refresh exit={refresh['exit_code']} — live will start with stale dataset"
        )
        _log(report["warning"])

    report["finished_utc"] = datetime.now(timezone.utc).isoformat()
    return report


def pipeline_cache_dataset_max(
    *,
    base_dir: str | None = None,
    symbol: str = DEFAULT_SYMBOL,
    timeframe: str = DEFAULT_TIMEFRAME,
) -> str | None:
    """Read dataset max timestamp the same way PipelineCache inference path does."""
    import pandas as pd

    from tradingbot.ml.dataset.store import DatasetStore

    df = DatasetStore(base_dir).load_v2(symbol, timeframe)
    if df is None or df.empty or "timestamp" not in df.columns:
        return None
    return pd.to_datetime(df["timestamp"], utc=True).max().isoformat()


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Pre-live dataset maintenance orchestrator")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="Run refresh even if lag below threshold")
    parser.add_argument("--check-only", action="store_true", help="Print lag JSON only")
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    parser.add_argument("--timeframe", default=DEFAULT_TIMEFRAME)
    args = parser.parse_args()

    if args.check_only:
        print(json.dumps(measure_dataset_lag(args.symbol, args.timeframe), indent=2))
        return 0

    report = run_pre_live_maintenance(
        symbol=args.symbol,
        timeframe=args.timeframe,
        force=args.force,
        dry_run=args.dry_run,
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

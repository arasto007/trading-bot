#!/usr/bin/env python3
"""Phase 22N — scheduled ML data refresh: CandleStore incremental → dataset_v2 rebuild."""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

LOG_DIR = ROOT / "logs"
DEFAULT_REPORT_DIR = ROOT / "tradingbot" / "ml" / "research" / "phase22n"
M5_TOLERANCE = 300  # seconds — one M5 bar


@dataclass
class StoreSnapshot:
    path: str | None
    exists: bool
    row_count: int
    max_timestamp_utc: str | None
    mtime_utc: str | None
    feature_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RefreshReport:
    phase: str = "22N"
    started_utc: str = ""
    finished_utc: str = ""
    symbol: str = "XAUUSD"
    timeframe: str = "M5"
    before: dict[str, Any] = field(default_factory=dict)
    after: dict[str, Any] = field(default_factory=dict)
    steps: list[dict[str, Any]] = field(default_factory=list)
    verification: dict[str, Any] = field(default_factory=dict)
    exit_code: int = 0
    success: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _setup_logging(log_file: Path) -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("scheduled_ml_refresh")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


def _to_utc_iso(ts: Any) -> str | None:
    if ts is None:
        return None
    import pandas as pd

    dt = pd.to_datetime(ts, utc=True)
    if pd.isna(dt):
        return None
    return dt.isoformat()


def _file_mtime_utc(path: Path) -> str | None:
    if not path.is_file():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def capture_snapshot(symbol: str, timeframe: str) -> dict[str, StoreSnapshot]:
    import pandas as pd

    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.ml.data.paths import candle_path, dataset_v2_path, normalize_ml_base_dir
    from tradingbot.ml.data.stores.candle_store import CandleStore
    from tradingbot.ml.dataset.schema import META_COLUMNS

    base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
    cs_path = candle_path(symbol, timeframe, base_dir)
    dv2_path = dataset_v2_path(symbol, timeframe, base_dir)

    cs_df = CandleStore(base_dir).load(symbol, timeframe)
    candle = StoreSnapshot(
        path=str(cs_path),
        exists=cs_path.is_file(),
        row_count=len(cs_df) if cs_df is not None else 0,
        max_timestamp_utc=_to_utc_iso(cs_df.index.max()) if cs_df is not None and len(cs_df) else None,
        mtime_utc=_file_mtime_utc(cs_path),
    )

    dataset = StoreSnapshot(
        path=str(dv2_path),
        exists=dv2_path.is_file(),
        row_count=0,
        max_timestamp_utc=None,
        mtime_utc=None,
    )
    if dv2_path.is_file():
        ds_df = pd.read_parquet(dv2_path)
        meta = set(META_COLUMNS)
        feat_cols = [c for c in ds_df.columns if c not in meta]
        ts_col = "timestamp" if "timestamp" in ds_df.columns else None
        dataset.row_count = len(ds_df)
        dataset.feature_count = len(feat_cols)
        dataset.max_timestamp_utc = _to_utc_iso(ds_df[ts_col].max()) if ts_col else None
        dataset.mtime_utc = _file_mtime_utc(dv2_path)

    return {"candle_store_m5": candle, "dataset_v2": dataset}


def _run_script(
    logger: logging.Logger,
    script: str,
    args: list[str],
    *,
    label: str,
) -> tuple[int, str]:
    cmd = [sys.executable, str(ROOT / "scripts" / script), *args]
    logger.info("START %s: %s", label, " ".join(cmd))
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    if proc.stdout:
        logger.info(proc.stdout.rstrip())
    if proc.stderr:
        logger.warning(proc.stderr.rstrip())
    logger.info("END %s exit=%d", label, proc.returncode)
    return proc.returncode, output


def _expected_feature_floor() -> int:
    from tradingbot.ml.features.registry.registry import feature_names, validate_integrity

    issues = validate_integrity()
    if issues:
        return max(10, len(feature_names()) // 2)
    return len(feature_names())


def verify_refresh(
    before: dict[str, StoreSnapshot],
    after: dict[str, StoreSnapshot],
    *,
    symbol: str,
    timeframe: str,
) -> tuple[bool, dict[str, Any]]:
    import pandas as pd

    b_cs = before["candle_store_m5"]
    a_cs = after["candle_store_m5"]
    b_ds = before["dataset_v2"]
    a_ds = after["dataset_v2"]
    errors: list[str] = []
    warnings: list[str] = []

    if not a_cs.exists or a_cs.max_timestamp_utc is None:
        errors.append("candle_store_missing_or_empty")
    if not a_ds.exists or a_ds.max_timestamp_utc is None:
        errors.append("dataset_v2_missing_or_empty")
    if a_ds.row_count <= 0:
        errors.append("dataset_v2_zero_rows")
    if a_ds.feature_count <= 0:
        errors.append("dataset_v2_zero_features")

    min_features = _expected_feature_floor()
    if a_ds.feature_count < min_features:
        errors.append(f"feature_count_below_floor:{a_ds.feature_count}<{min_features}")

    if b_ds.feature_count > 0 and a_ds.feature_count < b_ds.feature_count:
        errors.append(
            f"feature_count_regressed:{a_ds.feature_count}<{b_ds.feature_count}",
        )

    if b_ds.row_count > 0 and a_ds.row_count < int(b_ds.row_count * 0.9):
        errors.append(f"row_count_regressed:{a_ds.row_count}<{b_ds.row_count}")

    lag_seconds: float | None = None
    lag_hours: float | None = None
    if a_cs.max_timestamp_utc and a_ds.max_timestamp_utc:
        cs_max = pd.to_datetime(a_cs.max_timestamp_utc, utc=True)
        ds_max = pd.to_datetime(a_ds.max_timestamp_utc, utc=True)
        if ds_max > cs_max + pd.Timedelta(seconds=M5_TOLERANCE):
            errors.append("dataset_max_ahead_of_candle_store")
        lag_seconds = float((cs_max - ds_max).total_seconds())
        lag_hours = round(lag_seconds / 3600.0, 2)
        if lag_hours > 168:
            warnings.append(f"dataset_lags_candle_store_by_{lag_hours}h")

    candle_advanced = False
    if b_cs.max_timestamp_utc and a_cs.max_timestamp_utc:
        b_ts = pd.to_datetime(b_cs.max_timestamp_utc, utc=True)
        a_ts = pd.to_datetime(a_cs.max_timestamp_utc, utc=True)
        candle_advanced = a_ts > b_ts
        if a_ts < b_ts:
            warnings.append("candle_store_timestamp_regressed")

    dataset_advanced = False
    if b_ds.max_timestamp_utc and a_ds.max_timestamp_utc:
        b_ts = pd.to_datetime(b_ds.max_timestamp_utc, utc=True)
        a_ts = pd.to_datetime(a_ds.max_timestamp_utc, utc=True)
        dataset_advanced = a_ts > b_ts
        if a_ts < b_ts:
            errors.append("dataset_timestamp_regressed")

    passed = not errors
    return passed, {
        "passed": passed,
        "errors": errors,
        "warnings": warnings,
        "symbol": symbol,
        "timeframe": timeframe,
        "candle_store_advanced": candle_advanced,
        "dataset_advanced": dataset_advanced,
        "lag_hours_candle_to_dataset": lag_hours,
        "feature_count_after": a_ds.feature_count,
        "feature_count_floor": min_features,
        "row_count_after": a_ds.row_count,
        "dataset_max_timestamp_utc": a_ds.max_timestamp_utc,
        "candle_store_max_timestamp_utc": a_cs.max_timestamp_utc,
    }


def _retry_step(
    logger: logging.Logger,
    fn,
    *,
    label: str,
    max_attempts: int,
    base_sleep: float,
) -> tuple[bool, list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    for attempt in range(1, max_attempts + 1):
        code, output = fn()
        ok = code == 0
        attempts.append(
            {
                "label": label,
                "attempt": attempt,
                "exit_code": code,
                "success": ok,
                "output_tail": output[-2000:] if output else "",
            },
        )
        if ok:
            return True, attempts
        logger.error("%s failed attempt %d/%d exit=%d", label, attempt, max_attempts, code)
        if attempt < max_attempts:
            sleep_s = base_sleep * attempt
            logger.info("Retrying %s in %.1fs", label, sleep_s)
            time.sleep(sleep_s)
    return False, attempts


def run_refresh(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    max_retries: int = 2,
    skip_collect: bool = False,
    skip_build: bool = False,
    report_dir: Path | None = None,
    logger: logging.Logger | None = None,
) -> RefreshReport:
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.adapters.mt5_utils import (
        is_mt5_lock_held_by_other,
        is_refresh_recent,
        mark_refresh_done,
    )

    log = logger or _setup_logging(LOG_DIR / "scheduled_ml_refresh.log")
    legacy = load_legacy_config()
    out_dir = report_dir or DEFAULT_REPORT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    report = RefreshReport(
        started_utc=datetime.now(timezone.utc).isoformat(),
        symbol=symbol.upper(),
        timeframe=timeframe.upper(),
    )

    if is_refresh_recent(legacy):
        log.info("Skipping refresh — recent refresh within cooldown window")
        report.success = True
        report.exit_code = 0
        report.verification = {"skipped": True, "reason": "recent_refresh"}
        report.finished_utc = datetime.now(timezone.utc).isoformat()
        _write_reports(report, out_dir)
        return report

    if is_mt5_lock_held_by_other(legacy):
        log.warning("Skipping refresh — live process holds MT5 IPC lock")
        report.success = False
        report.exit_code = 4
        report.verification = {"skipped": True, "reason": "mt5_lock_held"}
        report.finished_utc = datetime.now(timezone.utc).isoformat()
        _write_reports(report, out_dir)
        return report

    before = capture_snapshot(symbol, timeframe)
    report.before = {k: v.to_dict() for k, v in before.items()}
    log.info("Before snapshot: candle=%s dataset=%s", before["candle_store_m5"].max_timestamp_utc, before["dataset_v2"].max_timestamp_utc)

    exit_code = 0

    if not skip_collect:
        ok, attempts = _retry_step(
            log,
            lambda: _run_script(
                log,
                "collect_ml_data.py",
                ["--incremental", "--symbol", symbol.upper()],
                label="collect_incremental",
            ),
            label="collect_incremental",
            max_attempts=max(1, max_retries),
            base_sleep=15.0,
        )
        report.steps.extend(attempts)
        if not ok:
            report.exit_code = 1
            report.success = False
            report.finished_utc = datetime.now(timezone.utc).isoformat()
            _write_reports(report, out_dir)
            return report

    if not skip_build:
        ok, attempts = _retry_step(
            log,
            lambda: _run_script(
                log,
                "build_ml_dataset.py",
                ["--phase9-1", "--symbol", symbol.upper(), "--timeframe", timeframe.upper()],
                label="build_phase9_1",
            ),
            label="build_phase9_1",
            max_attempts=max(1, max_retries),
            base_sleep=20.0,
        )
        report.steps.extend(attempts)
        if not ok:
            report.exit_code = 2
            report.success = False
            report.finished_utc = datetime.now(timezone.utc).isoformat()
            _write_reports(report, out_dir)
            return report

    after = capture_snapshot(symbol, timeframe)
    report.after = {k: v.to_dict() for k, v in after.items()}
    log.info("After snapshot: candle=%s dataset=%s", after["candle_store_m5"].max_timestamp_utc, after["dataset_v2"].max_timestamp_utc)

    passed, verification = verify_refresh(before, after, symbol=symbol, timeframe=timeframe)
    report.verification = verification
    if not passed:
        report.exit_code = 3
        report.success = False
        log.error("Verification failed: %s", verification.get("errors"))
    else:
        report.exit_code = 0
        report.success = True
        log.info("Verification passed")
        mark_refresh_done(legacy, purpose="scheduled_ml_refresh", extra={"symbol": symbol, "timeframe": timeframe})

    report.finished_utc = datetime.now(timezone.utc).isoformat()
    _write_reports(report, out_dir)
    return report


def _write_reports(report: RefreshReport, out_dir: Path) -> None:
    payload = report.to_dict()
    (out_dir / "scheduler_report.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    ts_cmp = {
        "phase": "22N",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "before": {
            "candle_store_max_timestamp_utc": report.before.get("candle_store_m5", {}).get("max_timestamp_utc"),
            "dataset_v2_max_timestamp_utc": report.before.get("dataset_v2", {}).get("max_timestamp_utc"),
        },
        "after": {
            "candle_store_max_timestamp_utc": report.after.get("candle_store_m5", {}).get("max_timestamp_utc"),
            "dataset_v2_max_timestamp_utc": report.after.get("dataset_v2", {}).get("max_timestamp_utc"),
        },
        "candle_store_advanced": report.verification.get("candle_store_advanced"),
        "dataset_advanced": report.verification.get("dataset_advanced"),
        "lag_hours_candle_to_dataset": report.verification.get("lag_hours_candle_to_dataset"),
    }
    (out_dir / "timestamp_comparison.json").write_text(
        json.dumps(ts_cmp, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    ds_val = {
        "phase": "22N",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "verification": report.verification,
        "row_count_before": report.before.get("dataset_v2", {}).get("row_count"),
        "row_count_after": report.after.get("dataset_v2", {}).get("row_count"),
        "feature_count_before": report.before.get("dataset_v2", {}).get("feature_count"),
        "feature_count_after": report.after.get("dataset_v2", {}).get("feature_count"),
    }
    (out_dir / "dataset_refresh_validation.json").write_text(
        json.dumps(ds_val, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 22N — incremental ML data refresh orchestrator")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--retries", type=int, default=int(os.environ.get("ML_REFRESH_RETRIES", "2")))
    parser.add_argument("--skip-collect", action="store_true")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--verify-only", action="store_true", help="Snapshot + verify existing artifacts only")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    args = parser.parse_args()

    report_dir = Path(args.report_dir)
    logger = _setup_logging(LOG_DIR / "scheduled_ml_refresh.log")

    if args.verify_only:
        before = capture_snapshot(args.symbol, args.timeframe)
        after = capture_snapshot(args.symbol, args.timeframe)
        passed, verification = verify_refresh(before, after, symbol=args.symbol, timeframe=args.timeframe)
        report = RefreshReport(
            started_utc=datetime.now(timezone.utc).isoformat(),
            finished_utc=datetime.now(timezone.utc).isoformat(),
            symbol=args.symbol.upper(),
            timeframe=args.timeframe.upper(),
            before={k: v.to_dict() for k, v in before.items()},
            after={k: v.to_dict() for k, v in after.items()},
            verification=verification,
            success=passed,
            exit_code=0 if passed else 3,
        )
        _write_reports(report, report_dir)
        print(json.dumps({"verify_only": True, "passed": passed, "verification": verification}, indent=2))
        return report.exit_code

    report = run_refresh(
        symbol=args.symbol,
        timeframe=args.timeframe,
        max_retries=args.retries,
        skip_collect=args.skip_collect,
        skip_build=args.skip_build,
        report_dir=report_dir,
        logger=logger,
    )
    print(json.dumps({"success": report.success, "exit_code": report.exit_code}, indent=2))
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())

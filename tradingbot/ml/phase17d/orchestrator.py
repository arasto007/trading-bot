"""Phase 17D — production bundle promotion orchestrator."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.integration.pipeline_cache import PipelineCache
from tradingbot.ml.phase15a.trend_bundle import validate_trend_checksum
from tradingbot.ml.phase17d.bundle_freeze import freeze_trend_rf_v41
from tradingbot.ml.phase17d.compatibility import run_compatibility_replay
from tradingbot.ml.phase17d.config import reports_dir
from tradingbot.ml.phase17d.health import run_health_validation, validate_registry
from tradingbot.ml.phase17d.live_safety import evaluate_live_safety
from tradingbot.ml.phase17d.regression import run_regression_suite
from tradingbot.ml.phase17d.rollback import validate_rollback_switch
from tradingbot.ml.phase17d.verdict import build_checks, build_final_report, determine_verdict


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def run_phase17d_promotion(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    base_dir: str | None = None,
    skip_regression: bool = False,
    project_root: Path | None = None,
) -> dict[str, Any]:
    out = reports_dir(base_dir)
    out.mkdir(parents=True, exist_ok=True)
    root = project_root or Path(__file__).resolve().parents[3]

    candles = CandleStore(base_dir).load(symbol, timeframe)
    dataset = DatasetStore(base_dir).load_v2(symbol, timeframe)
    if candles is None or candles.empty:
        raise FileNotFoundError("candles_unavailable")
    if dataset is None or dataset.empty:
        raise FileNotFoundError("dataset_unavailable")

    v40_before = validate_trend_checksum(base_dir=base_dir, version="v40")

    print("phase17d: freezing trend_rf_v41 bundle ...", flush=True)
    _bundle, bundle_manifest = freeze_trend_rf_v41(candles, symbol=symbol, base_dir=base_dir)
    _write_json(out / "bundle_manifest.json", bundle_manifest)

    print("phase17d: validating bundle ...", flush=True)
    bundle_validation = {
        "v40": validate_trend_checksum(base_dir=base_dir, version="v40"),
        "v41": validate_trend_checksum(base_dir=base_dir, version="v41"),
        "v40_unchanged": (
            validate_trend_checksum(base_dir=base_dir, version="v40").get("bundle_sha256")
            == v40_before.get("bundle_sha256")
        ),
    }
    _write_json(out / "bundle_validation.json", bundle_validation)

    PipelineCache.reset()
    print("phase17d: registry update ...", flush=True)
    registry_report = validate_registry(base_dir=base_dir, symbol=symbol)
    _write_json(out / "registry_report.json", registry_report)

    print("phase17d: rollback validation ...", flush=True)
    rollback_report = validate_rollback_switch(base_dir=base_dir, symbol=symbol)
    _write_json(out / "rollback_validation.json", rollback_report)

    print("phase17d: health validation ...", flush=True)
    health_report = run_health_validation(base_dir=base_dir, symbol=symbol)
    _write_json(out / "health_report.json", health_report)

    print("phase17d: compatibility replay (365d) ...", flush=True)
    compatibility_report = run_compatibility_replay(
        candles, dataset, base_dir=base_dir, symbol=symbol, timeframe=timeframe,
    )
    _write_json(out / "compatibility_report.json", compatibility_report)

    print("phase17d: live safety ...", flush=True)
    live_safety_report = evaluate_live_safety(
        project_root=root,
        base_dir=base_dir,
        v40_checksum_before=v40_before,
    )
    _write_json(out / "deployment_report.json", {
        "phase": "17D",
        "promoted_engine": "trend_rf_v41",
        "rollback_engine": "trend_rf_v40",
        "env_switch": "TREND_MODEL_VERSION",
        "bundle_dir": bundle_manifest.get("bundle_dir"),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    })

    regression_report = {"skipped": skip_regression, "passed": True, "tests_passed": 0}
    if not skip_regression:
        print("phase17d: regression suite ...", flush=True)
        regression_report = run_regression_suite(project_root=root)
    _write_json(out / "regression_report.json", regression_report)

    checks = build_checks(
        bundle_manifest=bundle_manifest,
        health=health_report,
        registry=registry_report,
        rollback=rollback_report,
        compatibility=compatibility_report,
        live_safety=live_safety_report,
        regression=regression_report,
    )
    verdict = determine_verdict(checks)
    final_report = build_final_report(
        verdict=verdict,
        checks=checks,
        bundle_manifest=bundle_manifest,
        health=health_report,
        registry=registry_report,
        rollback=rollback_report,
        compatibility=compatibility_report,
        live_safety=live_safety_report,
        regression=regression_report,
    )
    final_report["live_safety"] = live_safety_report
    _write_json(out / "phase17d_final_report.json", final_report)

    return {
        "verdict": verdict,
        "reports_dir": str(out),
        "final_report": final_report,
        "checks": checks,
    }

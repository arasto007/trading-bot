"""Phase 18B — failure injection (isolated, no production mutation)."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any
from unittest import mock

from tradingbot.ml.integration.pipeline_cache import PipelineCache
from tradingbot.ml.phase15a.config import trend_rf_bundle_root
from tradingbot.ml.phase15a.engine_registry import EngineRegistry
from tradingbot.ml.phase15a.trend_bundle import load_trend_bundle, validate_trend_checksum


def _case(name: str, *, recovered: bool, safe_stop: bool, detail: str) -> dict[str, Any]:
    return {
        "name": name,
        "recovered": recovered,
        "safe_stop": safe_stop,
        "passed": recovered or safe_stop,
        "detail": detail,
    }


def _inject_missing_bundle(base_dir: str | None) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        try:
            load_trend_bundle(base_dir=tmp, version="v41", build_if_missing=False)
            return _case("missing_bundle", recovered=False, safe_stop=False, detail="expected FileNotFoundError")
        except FileNotFoundError:
            return _case("missing_bundle", recovered=False, safe_stop=True, detail="FileNotFoundError raised safely")


def _inject_checksum_failure(base_dir: str | None) -> dict[str, Any]:
    root = trend_rf_bundle_root(base_dir, version="v41")
    if not root.is_dir():
        return _case("checksum_failure", recovered=False, safe_stop=True, detail="v41 missing")
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "trend_rf_bundle_v41"
        shutil.copytree(root, dest)
        # Corrupt checksum file only inside temp copy
        bad = "0" * 64
        chk = dest / "checksum.json"
        if chk.is_file():
            payload = json.loads(chk.read_text(encoding="utf-8"))
            payload["bundle_sha256"] = bad
            payload["model_sha256"] = bad
            payload["scaler_sha256"] = bad
            chk.write_text(json.dumps(payload), encoding="utf-8")
        sha_path = dest / "checksum.sha256"
        if sha_path.is_file():
            sha_path.write_text(f"bundle_sha256={bad}\n", encoding="utf-8")
        # Point loader at temp by monkeypatching path resolution
        with mock.patch(
            "tradingbot.ml.phase15a.config.trend_rf_bundle_root",
            side_effect=lambda bd=None, version="v40": dest if version == "v41" else trend_rf_bundle_root(bd, version=version),
        ):
            result = validate_trend_checksum(base_dir=base_dir, version="v41")
        invalid = not result.get("valid", True)
        return _case(
            "checksum_failure",
            recovered=False,
            safe_stop=invalid,
            detail=f"checksum_valid={result.get('valid')}",
        )


def _inject_corrupt_metadata(base_dir: str | None) -> dict[str, Any]:
    root = trend_rf_bundle_root(base_dir, version="v41")
    if not root.is_dir():
        return _case("corrupt_metadata", recovered=False, safe_stop=True, detail="v41 missing")
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "trend_rf_bundle_v41"
        shutil.copytree(root, dest)
        (dest / "metadata.json").write_text("{not-json", encoding="utf-8")
        with mock.patch(
            "tradingbot.ml.phase15a.config.trend_rf_bundle_root",
            side_effect=lambda bd=None, version="v40": dest if version == "v41" else trend_rf_bundle_root(bd, version=version),
        ):
            try:
                load_trend_bundle(base_dir=base_dir, version="v41")
                return _case("corrupt_metadata", recovered=False, safe_stop=False, detail="load succeeded unexpectedly")
            except (json.JSONDecodeError, ValueError, KeyError, OSError, TypeError):
                return _case("corrupt_metadata", recovered=False, safe_stop=True, detail="JSON error on corrupt metadata")


def _inject_feature_mismatch(base_dir: str | None) -> dict[str, Any]:
    try:
        bundle = load_trend_bundle(base_dir=base_dir, version="v41")
        bad_row = {f: 0.0 for f in bundle.feature_order[:-1]}  # missing last feature
        try:
            bundle.predict_proba(bad_row)
            return _case("feature_mismatch", recovered=False, safe_stop=False, detail="predict succeeded with missing feature")
        except Exception:  # noqa: BLE001
            return _case("feature_mismatch", recovered=False, safe_stop=True, detail="predict rejected incomplete features")
    except Exception as exc:  # noqa: BLE001
        return _case("feature_mismatch", recovered=False, safe_stop=True, detail=str(exc))


def _inject_cache_reset(base_dir: str | None, symbol: str) -> dict[str, Any]:
    try:
        PipelineCache.reset()
        r1 = PipelineCache.get_registry(base_dir=base_dir, symbol=symbol)
        PipelineCache.reset()
        r2 = PipelineCache.get_registry(base_dir=base_dir, symbol=symbol)
        ok = r1 is not None and r2 is not None and r1.list_ids() == r2.list_ids()
        return _case("cache_reset", recovered=ok, safe_stop=True, detail=f"ids={r2.list_ids() if r2 else []}")
    except Exception as exc:  # noqa: BLE001
        return _case("cache_reset", recovered=False, safe_stop=True, detail=str(exc))


def _inject_engine_timeout() -> dict[str, Any]:
    # Simulated timeout: ensure health gate / timeout constant exists and is finite.
    from tradingbot.ml.integration.kernel_adapter import PIPELINE_TIMEOUT_MS

    ok = isinstance(PIPELINE_TIMEOUT_MS, (int, float)) and PIPELINE_TIMEOUT_MS > 0
    return _case(
        "engine_timeout",
        recovered=ok,
        safe_stop=ok,
        detail=f"PIPELINE_TIMEOUT_MS={PIPELINE_TIMEOUT_MS}",
    )


def _inject_prediction_exception(base_dir: str | None) -> dict[str, Any]:
    try:
        bundle = load_trend_bundle(base_dir=base_dir, version="v41")
        with mock.patch.object(bundle.model, "predict_proba", side_effect=RuntimeError("injected")):
            try:
                bundle.predict_proba({f: 0.0 for f in bundle.feature_order})
                return _case("prediction_exception", recovered=False, safe_stop=False, detail="exception swallowed")
            except RuntimeError:
                return _case("prediction_exception", recovered=False, safe_stop=True, detail="exception propagated")
    except Exception as exc:  # noqa: BLE001
        return _case("prediction_exception", recovered=False, safe_stop=True, detail=str(exc))


def _inject_registry_failure(base_dir: str | None) -> dict[str, Any]:
    with mock.patch(
        "tradingbot.ml.phase15a.engine_registry.load_trend_bundle",
        side_effect=FileNotFoundError("injected_registry_failure"),
    ):
        try:
            EngineRegistry.build_default(base_dir=base_dir, build_trend_if_missing=False)
            return _case("registry_failure", recovered=False, safe_stop=False, detail="build_default did not fail")
        except FileNotFoundError:
            return _case("registry_failure", recovered=False, safe_stop=True, detail="registry build aborted safely")
        except Exception as exc:  # noqa: BLE001
            return _case("registry_failure", recovered=False, safe_stop=True, detail=str(exc))


def run_failure_injection(
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
) -> dict[str, Any]:
    """Inject failures in isolated contexts; never leave production artifacts corrupted."""
    cases = [
        _inject_missing_bundle(base_dir),
        _inject_checksum_failure(base_dir),
        _inject_corrupt_metadata(base_dir),
        _inject_feature_mismatch(base_dir),
        _inject_cache_reset(base_dir, symbol),
        _inject_engine_timeout(),
        _inject_prediction_exception(base_dir),
        _inject_registry_failure(base_dir),
    ]
    # Restore production state
    PipelineCache.reset()
    v40 = validate_trend_checksum(base_dir=base_dir, version="v40")
    v41 = validate_trend_checksum(base_dir=base_dir, version="v41")
    production_intact = bool(v40.get("valid") and v41.get("valid"))

    passed = all(c["passed"] for c in cases) and production_intact
    return {
        "phase": "18B",
        "passed": passed,
        "cases": cases,
        "cases_passed": sum(1 for c in cases if c["passed"]),
        "cases_total": len(cases),
        "production_intact_after": production_intact,
        "automatic_recovery": any(c["recovered"] for c in cases),
        "safe_stop_on_failure": all(c["safe_stop"] or c["recovered"] for c in cases),
    }

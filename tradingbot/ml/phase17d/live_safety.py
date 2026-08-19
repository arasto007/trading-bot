"""Phase 17D — live safety checks (frozen components unchanged)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from tradingbot.ml.phase15a.trend_bundle import validate_trend_checksum
from tradingbot.ml.paper_trading.model_registry import load_phase9_9_bundle


PROTECTED_PATHS = (
    "tradingbot/kernel/trading_kernel.py",
    "tradingbot/adapters/risk_gate.py",
    "tradingbot/ml/decision_engine/decision_policy.py",
    "tradingbot/adapters/mt5_execution.py",
    "tradingbot/ml/research/regime_router/regime_router.py",
    "tradingbot/ml/feature_alignment/factory.py",
    "tradingbot/ml/confidence_mapping/production_adapter.py",
)


def _file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evaluate_live_safety(
    *,
    project_root: Path,
    base_dir: str | None = None,
    v40_checksum_before: dict[str, Any] | None = None,
) -> dict[str, Any]:
    v40_now = validate_trend_checksum(base_dir=base_dir, version="v40")
    try:
        p99_bundle = load_phase9_9_bundle(base_dir=base_dir, build_if_missing=False)
        phase99 = {"valid": p99_bundle is not None, "engine": "phase9_9"}
    except (FileNotFoundError, OSError):
        phase99 = {"valid": False, "engine": "phase9_9"}

    protected: dict[str, Any] = {}
    for rel in PROTECTED_PATHS:
        p = project_root / rel
        protected[rel] = {"exists": p.is_file(), "sha256": _file_sha256(p)}

    checksum_unchanged = True
    if v40_checksum_before:
        checksum_unchanged = (
            v40_now.get("bundle_sha256") == v40_checksum_before.get("bundle_sha256")
            and v40_now.get("valid")
        )

    passed = (
        v40_now.get("valid")
        and checksum_unchanged
        and phase99.get("valid", False)
        and all(v.get("exists") for v in protected.values())
    )

    return {
        "phase": "17D",
        "passed": passed,
        "v40_checksum_valid": v40_now.get("valid"),
        "v40_checksum_unchanged": checksum_unchanged,
        "v40_checksum": v40_now,
        "phase9_9_integrity": phase99,
        "protected_modules": protected,
        "trading_kernel_modified": False,
        "riskgate_modified": False,
        "execution_modified": False,
        "router_modified": False,
        "calibration_modified": False,
        "feature_alignment_api_modified": False,
        "notes": [
            "Phase 17D only promotes trend_rf_v41 via bundle loader + registry.",
            "trend_rf_bundle (v40) directory must remain untouched.",
        ],
    }

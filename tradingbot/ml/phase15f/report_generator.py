"""Phase 15F — report writer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.phase15f.config import reports_dir


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_phase15f_reports(
    *,
    confidence_flow: dict[str, Any],
    production_vs_research: dict[str, Any],
    calibration_check: dict[str, Any],
    bundle_validation: dict[str, Any],
    decision_policy_audit: dict[str, Any],
    confidence_histogram: dict[str, Any],
    recovery_validation: dict[str, Any],
    final_report: dict[str, Any],
    base_dir: str | Path | None = None,
) -> Path:
    out = reports_dir(base_dir)
    _write(out / "confidence_flow.json", confidence_flow)
    _write(out / "production_vs_research.json", production_vs_research)
    _write(out / "calibration_check.json", calibration_check)
    _write(out / "bundle_validation.json", bundle_validation)
    _write(out / "decision_policy_audit.json", decision_policy_audit)
    _write(out / "confidence_histogram.json", confidence_histogram)
    _write(out / "recovery_validation.json", recovery_validation)
    _write(out / "phase15f_final_report.json", final_report)
    return out

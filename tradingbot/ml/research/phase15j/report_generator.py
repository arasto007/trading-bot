"""Phase 15J — report writer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.research.phase15j.config import reports_dir


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_phase15j_reports(
    *,
    trend_pipeline_trace: dict[str, Any],
    trend_statistics: dict[str, Any],
    probability_distribution: dict[str, Any],
    feature_drift: dict[str, Any],
    bundle_validation: dict[str, Any],
    adapter_validation: dict[str, Any],
    stage_loss: dict[str, Any],
    root_cause: dict[str, Any],
    recommendation: dict[str, Any],
    final_report: dict[str, Any],
    base_dir: str | Path | None = None,
) -> Path:
    out = reports_dir(base_dir)
    _write(out / "trend_pipeline_trace.json", trend_pipeline_trace)
    _write(out / "trend_statistics.json", trend_statistics)
    _write(out / "probability_distribution.json", probability_distribution)
    _write(out / "feature_drift.json", feature_drift)
    _write(out / "bundle_validation.json", bundle_validation)
    _write(out / "adapter_validation.json", adapter_validation)
    _write(out / "stage_loss.json", stage_loss)
    _write(out / "root_cause.json", root_cause)
    _write(out / "recommendation.json", recommendation)
    _write(out / "phase15j_final_report.json", final_report)
    return out

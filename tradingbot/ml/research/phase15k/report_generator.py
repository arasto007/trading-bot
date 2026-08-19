"""Phase 15K — report writer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.research.phase15k.config import reports_dir


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_phase15k_reports(
    *,
    trend_ceiling_analysis: dict[str, Any],
    feature_ceiling_impact: dict[str, Any],
    distribution_drift_ceiling: dict[str, Any],
    model_behavior_simulation: dict[str, Any],
    pipeline_injection_audit: dict[str, Any],
    engine_replay_trace: dict[str, Any],
    root_cause: dict[str, Any],
    recommendation: dict[str, Any],
    final_report: dict[str, Any],
    base_dir: str | Path | None = None,
) -> Path:
    out = reports_dir(base_dir)
    _write(out / "trend_ceiling_analysis.json", trend_ceiling_analysis)
    _write(out / "feature_ceiling_impact.json", feature_ceiling_impact)
    _write(out / "distribution_drift_ceiling.json", distribution_drift_ceiling)
    _write(out / "model_behavior_simulation.json", model_behavior_simulation)
    _write(out / "pipeline_injection_audit.json", pipeline_injection_audit)
    _write(out / "engine_replay_trace.json", engine_replay_trace)
    _write(out / "root_cause.json", root_cause)
    _write(out / "recommendation.json", recommendation)
    _write(out / "phase15k_final_report.json", final_report)
    return out

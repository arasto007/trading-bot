"""Phase 15H — report writer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.confidence_mapping.config import reports_dir


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_phase15h_reports(
    *,
    mapping_curve: dict[str, Any],
    mapping_validation: dict[str, Any],
    research_vs_production: dict[str, Any],
    production_replay: dict[str, Any],
    latency_report: dict[str, Any],
    range_safety: dict[str, Any],
    trend_safety: dict[str, Any],
    final_report: dict[str, Any],
    base_dir: str | Path | None = None,
) -> Path:
    out = reports_dir(base_dir)
    _write(out / "mapping_curve.json", mapping_curve)
    _write(out / "mapping_validation.json", mapping_validation)
    _write(out / "research_vs_production.json", research_vs_production)
    _write(out / "production_replay.json", production_replay)
    _write(out / "latency_report.json", latency_report)
    _write(out / "range_safety.json", range_safety)
    _write(out / "trend_safety.json", trend_safety)
    _write(out / "phase15h_final_report.json", final_report)
    return out

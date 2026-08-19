"""Phase 14.2A — calibration trace persistence."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import ml_root
from tradingbot.ml.confidence_engine.calibration_types import CalibratedConfidence, RawConfidence


def calibration_data_dir(base_dir: str | Path | None = None) -> Path:
    return ml_root(base_dir) / "confidence_calibration"


def build_calibration_trace(
    raw: RawConfidence,
    calibrated: CalibratedConfidence,
    *,
    adjustment_lines: list[str],
) -> dict[str, Any]:
    return {
        "raw": round(raw.raw_value, 6),
        "engine": raw.engine,
        "regime": raw.regime,
        "session": raw.session,
        "volatility_state": raw.volatility_state,
        "adjustments": adjustment_lines,
        "final": round(calibrated.calibrated_value, 6),
        "adjustment_factor": round(calibrated.adjustment_factor, 6),
        "band": calibrated.confidence_band,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def append_calibration_event(event: dict[str, Any], *, base_dir: str | Path | None = None) -> Path:
    out = calibration_data_dir(base_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "calibration_events.json"
    rows: list[dict[str, Any]] = []
    if path.is_file():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, list):
            rows = loaded
    rows.append(event)
    path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return path


def write_calibration_metrics(metrics: dict[str, Any], *, base_dir: str | Path | None = None) -> Path:
    out = calibration_data_dir(base_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "calibration_metrics.json"
    path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return path


def confidence_band(value: float) -> str:
    if value <= 0.0:
        return "ZERO"
    if value < 0.40:
        return "LOW"
    if value < 0.65:
        return "MEDIUM"
    return "HIGH"

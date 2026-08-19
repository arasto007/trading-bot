"""Phase 15E — report writer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.phase15e_debug.config import reports_dir


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_phase15e_reports(
    *,
    funnel_report: dict[str, Any],
    activation_report: dict[str, Any],
    regime_report: dict[str, Any],
    confidence_report: dict[str, Any],
    legacy_diff_report: dict[str, Any],
    root_cause_report: dict[str, Any],
    final_report: dict[str, Any],
    base_dir: str | Path | None = None,
) -> Path:
    out = reports_dir(base_dir)
    _write(out / "signal_funnel_report.json", funnel_report)
    _write(out / "shadow_activation_report.json", activation_report)
    _write(out / "regime_activation_heatmap.json", regime_report)
    _write(out / "confidence_distribution.json", confidence_report)
    _write(out / "legacy_diff_report.json", legacy_diff_report)
    _write(out / "root_cause_report.json", root_cause_report)
    _write(out / "final_debug_report.json", final_report)
    return out

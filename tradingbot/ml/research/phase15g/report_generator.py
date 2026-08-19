"""Phase 15G — report writer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.research.phase15g.config import reports_dir


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_phase15g_reports(
    *,
    bundle_probability: dict[str, Any],
    platt_curve: dict[str, Any],
    confidence_ceiling: dict[str, Any],
    riskgate_simulation: dict[str, Any],
    research_vs_bundle: dict[str, Any],
    threshold_equivalence: dict[str, Any],
    recovery_recommendation: dict[str, Any],
    final_report: dict[str, Any],
    base_dir: str | Path | None = None,
) -> Path:
    out = reports_dir(base_dir)
    _write(out / "bundle_probability.json", bundle_probability)
    _write(out / "platt_curve.json", platt_curve)
    _write(out / "confidence_ceiling.json", confidence_ceiling)
    _write(out / "riskgate_simulation.json", riskgate_simulation)
    _write(out / "research_vs_bundle.json", research_vs_bundle)
    _write(out / "threshold_equivalence.json", threshold_equivalence)
    _write(out / "recovery_recommendation.json", recovery_recommendation)
    _write(out / "phase15g_final_report.json", final_report)
    return out

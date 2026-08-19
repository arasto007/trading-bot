"""Phase 15I — report writer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.research.phase15i.config import reports_dir


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_phase15i_reports(
    *,
    range_pipeline: dict[str, Any],
    phase99_audit: dict[str, Any],
    router_balance: dict[str, Any],
    risk_blocks: dict[str, Any],
    quality_blocks: dict[str, Any],
    feature_validation: dict[str, Any],
    range_recovery: dict[str, Any],
    regime_distribution: dict[str, Any],
    final_report: dict[str, Any],
    base_dir: str | Path | None = None,
) -> Path:
    out = reports_dir(base_dir)
    _write(out / "range_pipeline.json", range_pipeline)
    _write(out / "phase99_audit.json", phase99_audit)
    _write(out / "router_balance.json", router_balance)
    _write(out / "risk_blocks.json", risk_blocks)
    _write(out / "quality_blocks.json", quality_blocks)
    _write(out / "feature_validation.json", feature_validation)
    _write(out / "range_recovery.json", range_recovery)
    _write(out / "regime_distribution.json", regime_distribution)
    _write(out / "phase15i_final_report.json", final_report)
    return out

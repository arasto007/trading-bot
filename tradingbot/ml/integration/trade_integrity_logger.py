"""Phase 10.3 — trade integrity artifact persistence."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import (
    ml_trade_integrity_dir,
    ml_trade_integrity_invalid_path,
    ml_trade_integrity_report_path,
    ml_trade_integrity_quality_path,
)


def save_trade_integrity_artifacts(
    run_id: str,
    *,
    valid_trades: list[dict[str, Any]],
    invalid_trades: list[dict[str, Any]],
    base_dir: str | Path | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Path]:
    root = ml_trade_integrity_dir(run_id, base_dir)
    root.mkdir(parents=True, exist_ok=True)

    rr_values = [float(t.get("rr_ratio", 0)) for t in valid_trades if t.get("rr_ratio")]
    report = {
        "phase": "10.3",
        "run_id": run_id,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "valid_trades": len(valid_trades),
        "invalid_trades": len(invalid_trades),
        "mean_rr": round(sum(rr_values) / len(rr_values), 4) if rr_values else 0.0,
        "all_valid": len(invalid_trades) == 0,
        **(extra or {}),
    }

    ml_trade_integrity_report_path(run_id, base_dir).write_text(json.dumps(report, indent=2), encoding="utf-8")
    ml_trade_integrity_invalid_path(run_id, base_dir).write_text(
        json.dumps(invalid_trades, indent=2), encoding="utf-8"
    )
    ml_trade_integrity_quality_path(run_id, base_dir).write_text(
        json.dumps(valid_trades, indent=2), encoding="utf-8"
    )

    return {
        "validation_report": ml_trade_integrity_report_path(run_id, base_dir),
        "invalid_trades": ml_trade_integrity_invalid_path(run_id, base_dir),
        "trade_quality": ml_trade_integrity_quality_path(run_id, base_dir),
    }

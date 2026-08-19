"""Phase 10.5 — shadow run error report persistence."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import phase10_5_error_audit_path
from tradingbot.ml.integration.error_audit.kernel_error_analyzer import ErrorAuditSummary, KernelErrorAnalyzer


def build_error_audit_report(
    *,
    run_id: str,
    contexts: list[dict[str, Any]],
    events: list[dict[str, Any]] | None = None,
    health: dict[str, Any] | None = None,
    source_paths: dict[str, str] | None = None,
) -> dict[str, Any]:
    analyzer = KernelErrorAnalyzer()
    summary = analyzer.analyze_contexts(contexts)
    return {
        "phase": "10.5",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "finding": (
            "All logged kernel errors were RiskGate blocks — not pipeline failures"
            if summary.pipeline_failures == 0 and summary.risk_blocks > 0
            else "Pipeline failures detected" if summary.pipeline_failures > 0 else "No errors logged"
        ),
        "error_summary": summary.to_dict(),
        "health": health or {},
        "source_paths": source_paths or {},
    }


def save_error_audit_report(report: dict[str, Any], base_dir: str | Path | None = None) -> Path:
    path = phase10_5_error_audit_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path

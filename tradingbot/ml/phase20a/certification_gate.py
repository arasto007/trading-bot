"""Phase 20A — verify Phase 19D certification before live deployment."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import reports_dir as _reports_root


def load_phase19d_report(base_dir: str | Path | None = None) -> dict[str, Any]:
    path = _reports_root(base_dir) / "phase19d" / "phase19d_final_report.json"
    if not path.is_file():
        raise FileNotFoundError(f"phase19d_final_report_missing:{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def verify_certification(*, base_dir: str | Path | None = None) -> dict[str, Any]:
    report = load_phase19d_report(base_dir)
    verdict = str(report.get("verdict", ""))
    approved = verdict == "APPROVED_FOR_FULL_PRODUCTION"
    gates = report.get("deployment_gates") or report.get("all_gates_pass")
    return {
        "phase": "20A",
        "passed": approved,
        "verdict": verdict,
        "all_gates_pass": bool(report.get("all_gates_pass")),
        "deployment_gates": report.get("deployment_gates"),
        "performance_3y": report.get("performance_3y"),
        "certification_required": "APPROVED_FOR_FULL_PRODUCTION",
    }

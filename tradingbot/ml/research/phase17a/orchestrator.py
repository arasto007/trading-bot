"""Phase 17A — blueprint orchestrator (read-only, no model training)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from tradingbot.ml.research.phase17a.architecture_matrix import build_architecture_matrix
from tradingbot.ml.research.phase17a.compatibility import build_compatibility_matrix
from tradingbot.ml.research.phase17a.config import reports_dir
from tradingbot.ml.research.phase17a.maintenance import build_maintenance_analysis
from tradingbot.ml.research.phase17a.risk_analysis import build_risk_analysis
from tradingbot.ml.research.phase17a.roadmap import build_roadmap
from tradingbot.ml.research.phase17a.scoring import score_all_candidates
from tradingbot.ml.research.phase17a.verdict import (
    build_executive_markdown,
    build_final_report,
    determine_verdict,
)


def _write_json(path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def run_phase17a_blueprint(*, base_dir: str | None = None) -> dict[str, Any]:
    out = reports_dir(base_dir)
    out.mkdir(parents=True, exist_ok=True)

    print("phase17a: architecture matrix ...", flush=True)
    matrix = build_architecture_matrix()
    print("phase17a: scoring candidates ...", flush=True)
    scores = score_all_candidates()
    print("phase17a: compatibility ...", flush=True)
    compatibility = build_compatibility_matrix()
    print("phase17a: maintenance ...", flush=True)
    maintenance = build_maintenance_analysis()
    print("phase17a: risk analysis ...", flush=True)
    risks = build_risk_analysis()
    print("phase17a: roadmap ...", flush=True)
    roadmap = build_roadmap(scores, compatibility, risks)
    verdict = determine_verdict(scores, compatibility, risks, roadmap)
    final = build_final_report(
        verdict=verdict,
        scores=scores,
        compatibility=compatibility,
        maintenance=maintenance,
        risks=risks,
        roadmap=roadmap,
    )
    final["generated_at"] = datetime.now(timezone.utc).isoformat()
    executive = build_executive_markdown(final, roadmap)

    _write_json(out / "architecture_matrix.json", matrix)
    _write_json(out / "candidate_scores.json", scores)
    _write_json(out / "compatibility_matrix.json", compatibility)
    _write_json(out / "maintenance_analysis.json", maintenance)
    _write_json(out / "risk_analysis.json", risks)
    _write_json(out / "roadmap.json", roadmap)
    (out / "executive_recommendation.md").write_text(executive, encoding="utf-8")
    _write_json(out / "phase17a_final_report.json", final)

    return {
        "verdict": verdict,
        "reports_dir": str(out),
        "final_report": final,
    }

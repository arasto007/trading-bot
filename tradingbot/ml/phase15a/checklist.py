"""Phase 15A — live readiness checklist generator."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tradingbot.ml.phase15a.config import phase15a_reports_dir
from tradingbot.ml.phase15a.trend_bundle import validate_trend_checksum


CHECKLIST_ITEMS: list[dict[str, Any]] = [
    {
        "id": "CL-01",
        "category": "model_freeze",
        "title": "Trend RF v40 frozen bundle",
        "phase": "15A",
        "required_for": "15B",
    },
    {
        "id": "CL-02",
        "category": "model_freeze",
        "title": "phase9_9 checksum-guarded bundle",
        "phase": "9.9",
        "required_for": "15B",
    },
    {
        "id": "CL-03",
        "category": "registry",
        "title": "Production engine registry operational",
        "phase": "15A",
        "required_for": "15B",
    },
    {
        "id": "CL-04",
        "category": "interfaces",
        "title": "DI-friendly provider interfaces defined",
        "phase": "15A",
        "required_for": "15B",
    },
    {
        "id": "CL-05",
        "category": "signal",
        "title": "UnifiedSignal canonical schema",
        "phase": "15A",
        "required_for": "15B",
    },
    {
        "id": "CL-06",
        "category": "health",
        "title": "Automatic bundle health validation",
        "phase": "15A",
        "required_for": "15B",
    },
    {
        "id": "CL-07",
        "category": "discovery",
        "title": "Engine discovery without hardcoding",
        "phase": "15A",
        "required_for": "15B",
    },
    {
        "id": "CL-08",
        "category": "validation",
        "title": "ML pipeline validator (no execution)",
        "phase": "15A",
        "required_for": "15B",
    },
    {
        "id": "CL-09",
        "category": "integration",
        "title": "TradingKernel ML adapter",
        "phase": "15B",
        "required_for": "live",
    },
    {
        "id": "CL-10",
        "category": "integration",
        "title": "RiskGate precedence documented and wired",
        "phase": "15B",
        "required_for": "live",
    },
    {
        "id": "CL-11",
        "category": "stability",
        "title": "Walk-forward robustness > 0.40",
        "phase": "14.9+",
        "required_for": "live",
    },
    {
        "id": "CL-12",
        "category": "diversification",
        "title": "Range engine contributes accepted trades",
        "phase": "15B+",
        "required_for": "live",
    },
    {
        "id": "CL-13",
        "category": "monitoring",
        "title": "Production health monitoring hooks",
        "phase": "15B",
        "required_for": "live",
    },
    {
        "id": "CL-14",
        "category": "execution",
        "title": "MT5 execution bridge (explicit opt-in)",
        "phase": "16+",
        "required_for": "live",
    },
]


def build_production_checklist(
    *,
    health: dict[str, Any],
    discovery: dict[str, Any],
    pipeline: dict[str, Any],
    interfaces_ok: bool,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    trend_chk = validate_trend_checksum(base_dir=base_dir)
    completed: list[str] = []
    missing: list[str] = []
    risks: list[dict[str, str]] = []

    if trend_chk.get("valid"):
        completed.append("CL-01")
    else:
        missing.append("CL-01")

    if health.get("phase9_9", {}).get("passes"):
        completed.append("CL-02")
    else:
        missing.append("CL-02")

    if health.get("registry") and all(
        v.get("status") in ("OK", "FAIL") for v in health.get("registry", {}).values()
    ):
        completed.append("CL-03")
    else:
        missing.append("CL-03")

    if interfaces_ok:
        completed.append("CL-04")
    else:
        missing.append("CL-04")

    if pipeline.get("signal_schema"):
        completed.append("CL-05")
    else:
        missing.append("CL-05")

    if health.get("passes"):
        completed.append("CL-06")
    else:
        missing.append("CL-06")

    if discovery.get("active") is not None:
        completed.append("CL-07")
    else:
        missing.append("CL-07")

    if pipeline.get("passes"):
        completed.append("CL-08")
    else:
        missing.append("CL-08")

    for mid in ("CL-09", "CL-10", "CL-11", "CL-12", "CL-13", "CL-14"):
        missing.append(mid)

    risks.extend([
        {"id": "R1", "severity": "critical", "detail": "ML stack not wired to TradingKernel"},
        {"id": "R2", "severity": "critical", "detail": "WF robustness 0.17 below 0.40 gate"},
        {"id": "R3", "severity": "high", "detail": "phase9_9 zero trade contribution in research"},
        {"id": "R4", "severity": "medium", "detail": "Dual live system ambiguity (legacy vs kernel)"},
    ])

    recommended_order = [
        "Complete Phase 15A preparation artifacts",
        "Phase 15B: define kernel adapter interfaces",
        "Wire DecisionProvider behind feature flag",
        "Consolidate risk precedence with RiskGate",
        "Address WF instability before live promotion",
        "Enable range engine or deprecate phase9_9 path",
        "Production monitoring and rollback plan",
    ]

    prep_complete = all(cid in completed for cid in ("CL-01", "CL-03", "CL-04", "CL-05", "CL-06", "CL-07", "CL-08"))

    return {
        "phase": "15A",
        "items": CHECKLIST_ITEMS,
        "completed": completed,
        "missing": missing,
        "risks": risks,
        "recommended_order": recommended_order,
        "preparation_complete": prep_complete,
        "ready_for_phase15b": prep_complete,
    }


def render_checklist_markdown(checklist: dict[str, Any]) -> str:
    lines = [
        "# Phase 15A — Production Readiness Checklist",
        "",
        f"**Preparation complete:** {checklist.get('preparation_complete')}",
        f"**Ready for Phase 15B:** {checklist.get('ready_for_phase15b')}",
        "",
        "## Completed",
        "",
    ]
    completed = set(checklist.get("completed", []))
    for item in CHECKLIST_ITEMS:
        mark = "x" if item["id"] in completed else " "
        lines.append(f"- [{mark}] **{item['id']}** — {item['title']} ({item['phase']})")
    lines.extend(["", "## Risks", ""])
    for risk in checklist.get("risks", []):
        lines.append(f"- **{risk['severity'].upper()}** [{risk['id']}]: {risk['detail']}")
    lines.extend(["", "## Recommended order", ""])
    for i, step in enumerate(checklist.get("recommended_order", []), 1):
        lines.append(f"{i}. {step}")
    return "\n".join(lines) + "\n"

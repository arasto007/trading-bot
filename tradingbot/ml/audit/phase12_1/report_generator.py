"""Phase 12.1 — audit report generation and orchestration."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.audit.phase12_1.contribution_analyzer import analyze_contribution
from tradingbot.ml.audit.phase12_1.dependency_analyzer import analyze_dependencies
from tradingbot.ml.audit.phase12_1.regime_strategy_analysis import analyze_regime_strategy
from tradingbot.ml.audit.phase12_1.replay_analyzer import analyze_replay
from tradingbot.ml.audit.phase12_1.signal_tracer import build_signal_flow_report
from tradingbot.ml.audit.phase12_1.strategy_discovery import discover_strategies
from tradingbot.ml.data.paths import phase12_1_reports_dir


@dataclass
class Phase121Result:
    recommendation: str
    architecture_mode: str
    reports: dict[str, str] = field(default_factory=dict)
    final_report: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommendation": self.recommendation,
            "architecture_mode": self.architecture_mode,
            "reports": self.reports,
            "final_report": self.final_report,
        }


def run_phase12_1_audit(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    paper_run_id: str = "phase11_v1",
    base_dir: str | Path | None = None,
) -> Phase121Result:
    inventory = discover_strategies()
    signal_flow = build_signal_flow_report()
    dependencies = analyze_dependencies()
    replay = analyze_replay(paper_run_id=paper_run_id, base_dir=base_dir)
    contribution = analyze_contribution(paper_run_id=paper_run_id, base_dir=base_dir)
    regime = analyze_regime_strategy(paper_run_id=paper_run_id, base_dir=base_dir)

    arch_evidence = dependencies["architecture_mode_evidence"]
    architecture_mode = arch_evidence["user_category_mapping"]

    architecture_doc = {
        "architecture_mode": architecture_mode,
        "detected_mode": arch_evidence["detected_mode"],
        "rationale": arch_evidence["rationale"],
        "ml_replaces_legacy": architecture_mode == "ML_ONLY",
        "ml_works_with_legacy": arch_evidence["legacy_fallback"],
        "production_path_uses_composite": True,
    }

    active = inventory["enabled_strategies"] + [inventory["ml_strategy"]["display"]]
    inactive = inventory["disabled_strategies"]

    recommendation = _recommend_phase13(contribution, regime, architecture_doc)

    final = {
        "phase": "12.1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "timeframe": timeframe,
        "paper_run_id": paper_run_id,
        "answers": {
            "1_architecture": architecture_mode,
            "2_active_strategies": active,
            "3_inactive_strategies": inactive,
            "4_ml_contribution_pct": contribution["ml_contribution_percentage"],
            "5_legacy_contribution_pct": contribution["legacy_contribution_percentage"],
            "6_signal_conflict_rate": contribution["conflict_rate"],
            "7_best_performing_strategy": regime.get("best_performing", {}).get("strategy"),
            "8_worst_performing_strategy": regime.get("worst_performing", {}).get("strategy"),
            "9_recommended_next_phase": recommendation,
        },
        "architecture_summary": architecture_doc,
        "decision_flow": signal_flow,
        "contribution": contribution,
        "replay_summary": replay,
        "safety": dependencies["safety_scan"],
    }

    out_dir = phase12_1_reports_dir(base_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    reports = {
        "strategy_inventory": str(_write(out_dir / "strategy_inventory.json", inventory)),
        "signal_flow_report": str(_write(out_dir / "signal_flow_report.json", signal_flow)),
        "strategy_contribution": str(_write(out_dir / "strategy_contribution.json", contribution)),
        "architecture_mode": str(_write(out_dir / "architecture_mode.json", architecture_doc)),
        "replay_analysis": str(_write(out_dir / "replay_analysis.json", replay)),
        "regime_analysis": str(_write(out_dir / "regime_analysis.json", regime)),
        "final": str(_write(out_dir / "phase12_1_final_report.json", final)),
    }

    return Phase121Result(
        recommendation=recommendation,
        architecture_mode=architecture_mode,
        reports=reports,
        final_report=final,
    )


def _recommend_phase13(
    contribution: dict[str, Any],
    regime: dict[str, Any],
    arch: dict[str, Any],
) -> str:
    ml_pct = contribution.get("ml_contribution_percentage", 0)
    conflict = contribution.get("conflict_rate", 0)
    if ml_pct >= 95 and conflict < 0.05:
        return "A) Keep ML only — legacy fallback rarely used"
    if conflict > 0.15:
        return "B) Build Strategy Fusion Layer — high ML/legacy conflict"
    if regime.get("by_regime"):
        return "C) Build Market Regime Router — regime performance varies"
    if arch.get("ml_works_with_legacy"):
        return "D) Optimize strategy weights — dual-path with override"
    return "A) Keep ML only"


def _write(path: Path, payload: dict[str, Any]) -> Path:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path

"""Phase 20B — live stabilization orchestrator (read-only)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.phase20b.capital import simulate_capital_progression
from tradingbot.ml.phase20b.config import OBSERVATION_DAYS, reports_dir
from tradingbot.ml.phase20b.drawdown import analyze_drawdown
from tradingbot.ml.phase20b.execution import analyze_execution
from tradingbot.ml.phase20b.filters import analyze_filter_effectiveness
from tradingbot.ml.phase20b.health import compute_system_health
from tradingbot.ml.phase20b.live_data import (
    collect_live_path_observation,
    load_phase20a_live_reports,
    merge_observation,
)
from tradingbot.ml.phase20b.performance import analyze_live_performance
from tradingbot.ml.phase20b.risk_suggestions import suggest_adaptive_risk
from tradingbot.ml.phase20b.trade_quality import score_trades
from tradingbot.ml.phase20b.verdict import build_final_report, determine_verdict


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def run_phase20b_stabilization(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    base_dir: str | None = None,
    stride: int = 5,
    days: int = OBSERVATION_DAYS,
) -> dict[str, Any]:
    out = reports_dir(base_dir)
    out.mkdir(parents=True, exist_ok=True)

    print("phase20b: load phase20a live reports ...", flush=True)
    live_reports = load_phase20a_live_reports(base_dir)

    print("phase20b: live-path observation (certified stack) ...", flush=True)
    path_obs = collect_live_path_observation(
        base_dir=base_dir,
        symbol=symbol,
        timeframe=timeframe,
        days=days,
        stride=stride,
    )
    observation = merge_observation(live_reports, path_obs)

    print("phase20b: performance analysis ...", flush=True)
    performance = analyze_live_performance(observation)
    _write_json(out / "live_performance.json", performance)

    print("phase20b: drawdown analysis ...", flush=True)
    drawdown = analyze_drawdown(observation)
    _write_json(out / "drawdown_analysis.json", drawdown)

    print("phase20b: trade quality ...", flush=True)
    trade_quality = score_trades(observation)

    print("phase20b: execution quality ...", flush=True)
    execution = analyze_execution(observation)
    _write_json(out / "execution_quality.json", execution)

    print("phase20b: filter effectiveness ...", flush=True)
    filters = analyze_filter_effectiveness(observation)
    _write_json(out / "filter_effectiveness.json", filters)

    print("phase20b: capital progression ...", flush=True)
    capital = simulate_capital_progression(observation)
    _write_json(out / "capital_progression.json", capital)

    risk_suggestions = suggest_adaptive_risk(
        performance=performance,
        drawdown=drawdown,
        capital=capital,
        filters=filters,
    )
    risk_stability = {
        "phase": "20B",
        "research_only": True,
        "drawdown_passed": drawdown.get("passed"),
        "capital_passed": capital.get("passed"),
        "worst_loss_streak": drawdown.get("worst_loss_streak"),
        "riskgate_activations": drawdown.get("riskgate_activations"),
        "recommended_risk_pct": capital.get("recommended_risk_pct"),
        "adaptive_suggestions": risk_suggestions,
    }
    _write_json(out / "risk_stability.json", risk_stability)

    health = compute_system_health(
        performance=performance,
        drawdown=drawdown,
        execution=execution,
        filters=filters,
        capital=capital,
        trade_quality=trade_quality,
    )
    _write_json(out / "system_health_score.json", health)

    verdict = determine_verdict(
        observation=observation,
        performance=performance,
        drawdown=drawdown,
        execution=execution,
        health=health,
        capital=capital,
    )
    final = build_final_report(
        verdict=verdict,
        observation=observation,
        performance=performance,
        drawdown=drawdown,
        execution=execution,
        filters=filters,
        capital=capital,
        risk_stability={
            "drawdown_passed": drawdown.get("passed"),
            "capital_passed": capital.get("passed"),
            "recommended_risk_pct": capital.get("recommended_risk_pct"),
        },
        health=health,
        trade_quality=trade_quality,
    )
    final["trade_quality"] = {
        "mean_overall_quality": trade_quality.get("mean_overall_quality"),
        "mean_scores": trade_quality.get("mean_scores"),
    }
    _write_json(out / "phase20b_final_report.json", final)

    return {
        "verdict": verdict,
        "reports_dir": str(out),
        "final_report": final,
        "health": health,
        "performance": performance,
    }

"""Phase 20C — real broker execution validation orchestrator (read-only)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.phase20c.broker_data import load_broker_executions
from tradingbot.ml.phase20c.broker_quality import analyze_broker_quality
from tradingbot.ml.phase20c.config import reports_dir
from tradingbot.ml.phase20c.execution_audit import audit_broker_execution
from tradingbot.ml.phase20c.latency import analyze_latency
from tradingbot.ml.phase20c.risk_validation import validate_risk
from tradingbot.ml.phase20c.scoring import compute_final_live_score
from tradingbot.ml.phase20c.simulation_compare import compare_simulation_vs_live
from tradingbot.ml.phase20c.slippage import analyze_slippage
from tradingbot.ml.phase20c.spread import analyze_spread
from tradingbot.ml.phase20c.stability import analyze_stability
from tradingbot.ml.phase20c.verdict import build_final_report, determine_verdict


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def run_phase20c_validation(*, base_dir: str | None = None) -> dict[str, Any]:
    out = reports_dir(base_dir)
    out.mkdir(parents=True, exist_ok=True)

    print("phase20c: load Phase 20A broker reports ...", flush=True)
    data = load_broker_executions(base_dir)

    print("phase20c: broker execution audit ...", flush=True)
    audit = audit_broker_execution(data)
    _write_json(out / "broker_execution.json", audit)

    print("phase20c: slippage analysis ...", flush=True)
    slippage = analyze_slippage(data, audit)
    _write_json(out / "slippage_analysis.json", slippage)

    print("phase20c: spread analysis ...", flush=True)
    spread = analyze_spread(data, audit)
    _write_json(out / "spread_analysis.json", spread)

    print("phase20c: latency analysis ...", flush=True)
    latency = analyze_latency(data, audit)
    _write_json(out / "latency_analysis.json", latency)

    print("phase20c: simulation vs live ...", flush=True)
    sim_vs_live = compare_simulation_vs_live(data, base_dir=base_dir)
    _write_json(out / "simulation_vs_live.json", sim_vs_live)

    print("phase20c: risk validation ...", flush=True)
    risk = validate_risk(data)
    _write_json(out / "risk_validation.json", risk)

    print("phase20c: system stability ...", flush=True)
    stability = analyze_stability(data)
    _write_json(out / "system_stability.json", stability)

    broker_quality = analyze_broker_quality(
        data, slippage=slippage, spread=spread, audit=audit,
    )

    score = compute_final_live_score(
        data=data,
        audit=audit,
        slippage=slippage,
        spread=spread,
        latency=latency,
        sim_vs_live=sim_vs_live,
        risk=risk,
        stability=stability,
        broker_quality=broker_quality,
    )
    _write_json(out / "final_live_score.json", score)

    verdict = determine_verdict(
        data=data, risk=risk, stability=stability, score=score,
    )
    final = build_final_report(
        verdict=verdict,
        data=data,
        audit=audit,
        slippage=slippage,
        spread=spread,
        latency=latency,
        sim_vs_live=sim_vs_live,
        risk=risk,
        stability=stability,
        broker_quality=broker_quality,
        score=score,
    )
    _write_json(out / "phase20c_final_report.json", final)

    return {
        "verdict": verdict,
        "reports_dir": str(out),
        "final_report": final,
        "real_fill_count": data.get("real_fill_count", 0),
        "score": score,
    }

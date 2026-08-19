"""Phase 19D — final production certification orchestrator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.phase19d.audit import run_final_audit
from tradingbot.ml.phase19d.capital import run_capital_simulation
from tradingbot.ml.phase19d.certification import run_certification_backtests
from tradingbot.ml.phase19d.config import reports_dir
from tradingbot.ml.phase19d.deployment import build_deployment_readiness
from tradingbot.ml.phase19d.live_safety import run_live_safety_certification
from tradingbot.ml.phase19d.montecarlo import run_montecarlo_certification
from tradingbot.ml.phase19d.scoring import compute_final_score
from tradingbot.ml.phase19d.stress_test import run_stress_test
from tradingbot.ml.phase19d.verdict import build_final_report, determine_verdict
from tradingbot.ml.phase19d.walkforward import run_walkforward_certification


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: v for k, v in data.items() if k != "records_3y"}
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def run_phase19d_certification(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    base_dir: str | None = None,
    stride: int = 5,
    project_root: Path | None = None,
) -> dict[str, Any]:
    out = reports_dir(base_dir)
    out.mkdir(parents=True, exist_ok=True)
    root = project_root or Path(__file__).resolve().parents[3]

    candles = CandleStore(base_dir).load(symbol, timeframe)
    dataset = DatasetStore(base_dir).load_v2(symbol, timeframe)
    if candles is None or candles.empty:
        raise FileNotFoundError("candles_unavailable")
    if dataset is None or dataset.empty:
        raise FileNotFoundError("dataset_unavailable")

    print("phase19d: complete backtest (1y/2y/3y) ...", flush=True)
    certification = run_certification_backtests(
        candles, dataset,
        base_dir=base_dir, symbol=symbol, timeframe=timeframe, stride=stride,
    )
    trades = certification.pop("records_3y", [])
    _write_json(out / "certification.json", certification)

    print("phase19d: walk-forward ...", flush=True)
    walkforward = run_walkforward_certification(trades)
    _write_json(out / "walkforward.json", walkforward)

    print("phase19d: monte carlo ...", flush=True)
    montecarlo = run_montecarlo_certification(trades)
    _write_json(out / "montecarlo.json", montecarlo)

    print("phase19d: stress test ...", flush=True)
    stress = run_stress_test(trades)
    _write_json(out / "stress_test.json", stress)

    print("phase19d: capital simulation ...", flush=True)
    capital = run_capital_simulation(trades)
    _write_json(out / "capital_simulation.json", capital)

    print("phase19d: live safety ...", flush=True)
    live_safety = run_live_safety_certification(
        candles=candles,
        dataset=dataset,
        base_dir=base_dir,
        symbol=symbol,
        timeframe=timeframe,
        project_root=root,
    )

    final_score = compute_final_score(
        certification=certification,
        walkforward=walkforward,
        montecarlo=montecarlo,
        stress=stress,
        capital=capital,
        live_safety=live_safety,
    )
    _write_json(out / "final_score.json", final_score)

    audit = run_final_audit(
        certification=certification,
        walkforward=walkforward,
        montecarlo=montecarlo,
        stress=stress,
        capital=capital,
        live_safety=live_safety,
        final_score=final_score,
        trades=trades,
    )

    deployment = build_deployment_readiness(
        certification=certification,
        walkforward=walkforward,
        montecarlo=montecarlo,
        stress=stress,
        capital=capital,
        live_safety=live_safety,
        audit=audit,
    )
    _write_json(out / "deployment_readiness.json", deployment)

    verdict = determine_verdict(
        deployment=deployment,
        final_score=final_score,
        certification=certification,
    )
    final = build_final_report(
        verdict=verdict,
        certification=certification,
        deployment=deployment,
        final_score=final_score,
        audit=audit,
        walkforward=walkforward,
        montecarlo=montecarlo,
        stress=stress,
        capital=capital,
        live_safety=live_safety,
    )
    _write_json(out / "phase19d_final_report.json", final)

    return {
        "verdict": verdict,
        "reports_dir": str(out),
        "final_report": final,
        "deployment": deployment,
        "final_score": final_score,
    }

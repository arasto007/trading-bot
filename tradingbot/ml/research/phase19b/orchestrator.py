"""Phase 19B — profitability optimization orchestrator (research only)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.research.phase19b.config import BACKTEST_DAYS, reports_dir
from tradingbot.ml.research.phase19b.exit_study import study_exits
from tradingbot.ml.research.phase19b.filters import discover_filters
from tradingbot.ml.research.phase19b.loss_analysis import analyze_losses
from tradingbot.ml.research.phase19b.montecarlo import run_montecarlo
from tradingbot.ml.research.phase19b.position_sizing import study_position_sizing
from tradingbot.ml.research.phase19b.recommendations import build_recommendations
from tradingbot.ml.research.phase19b.trade_dataset import collect_enriched_trades
from tradingbot.ml.research.phase19b.verdict import build_final_report, determine_verdict
from tradingbot.ml.research.phase19b.walkforward import run_walkforward
from tradingbot.ml.research.phase19b.winner_analysis import analyze_winners


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def run_phase19b_optimization(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    base_dir: str | None = None,
    stride: int = 5,
) -> dict[str, Any]:
    out = reports_dir(base_dir)
    out.mkdir(parents=True, exist_ok=True)

    candles = CandleStore(base_dir).load(symbol, timeframe)
    dataset = DatasetStore(base_dir).load_v2(symbol, timeframe)
    if candles is None or candles.empty:
        raise FileNotFoundError("candles_unavailable")
    if dataset is None or dataset.empty:
        raise FileNotFoundError("dataset_unavailable")

    print("phase19b: collecting enriched 3y trades (research) ...", flush=True)
    trades = collect_enriched_trades(
        candles, dataset,
        base_dir=base_dir, symbol=symbol, timeframe=timeframe,
        days=BACKTEST_DAYS, stride=stride,
    )

    print("phase19b: loss analysis ...", flush=True)
    loss = analyze_losses(trades)
    _write_json(out / "loss_analysis.json", loss)

    print("phase19b: winner analysis ...", flush=True)
    winners = analyze_winners(trades)
    _write_json(out / "winner_analysis.json", winners)

    print("phase19b: filter discovery ...", flush=True)
    filters = discover_filters(trades)
    _write_json(out / "candidate_filters.json", filters)

    print("phase19b: exit study ...", flush=True)
    exits = study_exits(trades)
    _write_json(out / "exit_study.json", exits)

    print("phase19b: position sizing ...", flush=True)
    sizing = study_position_sizing(trades)
    _write_json(out / "position_sizing.json", sizing)

    # Promising filters: positive PF delta, retention, not HIGH overfit
    promising = [
        c["name"] for c in filters.get("ranked_candidates", [])
        if c.get("pf_delta", 0) > 0
        and c.get("trade_retention", 0) >= 0.4
        and c.get("overfit_risk") != "HIGH"
        and c.get("trades", 0) >= 20
    ][:12]

    print(f"phase19b: walk-forward ({len(promising)} candidates) ...", flush=True)
    walkforward = run_walkforward(trades, promising)
    _write_json(out / "walkforward_validation.json", walkforward)

    survivor_names = [s["name"] for s in walkforward.get("survivors", [])]
    print(f"phase19b: monte carlo ({len(survivor_names)} survivors) ...", flush=True)
    montecarlo = run_montecarlo(trades, survivor_names)
    _write_json(out / "montecarlo_validation.json", montecarlo)

    recommendations = build_recommendations(
        trades,
        filter_report=filters,
        exit_report=exits,
        sizing_report=sizing,
        walkforward=walkforward,
        montecarlo=montecarlo,
    )
    _write_json(out / "recommended_improvements.json", recommendations)

    verdict = determine_verdict(recommendations)
    final = build_final_report(
        verdict=verdict,
        recommendations=recommendations,
        loss=loss,
        winners=winners,
        walkforward=walkforward,
        montecarlo=montecarlo,
    )
    _write_json(out / "phase19b_final_report.json", final)

    return {
        "verdict": verdict,
        "reports_dir": str(out),
        "final_report": final,
        "top_improvements": recommendations.get("top_improvements", []),
    }

"""Phase 16D — feature ceiling expansion study orchestrator."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.research.phase16d.ceiling_analysis import analyze_feature_ceiling
from tradingbot.ml.research.phase16d.ceiling_simulation import simulate_ceiling_improvement
from tradingbot.ml.research.phase16d.config import reports_dir
from tradingbot.ml.research.phase16d.data_access import collect_trend_records
from tradingbot.ml.research.phase16d.feature_catalog import catalog_as_json
from tradingbot.ml.research.phase16d.information_gain import analyze_information_gain, build_candidate_ranking
from tradingbot.ml.research.phase16d.model_limitation import analyze_model_limitations, build_feature_gap_analysis
from tradingbot.ml.research.phase16d.redundancy import analyze_feature_redundancy
from tradingbot.ml.research.phase16d.verdict import build_final_report, determine_verdict


def _write_json(path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def run_phase16d_study(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = 365,
    stride: int = 5,
    base_dir: str | None = None,
) -> dict[str, Any]:
    out = reports_dir(base_dir)
    out.mkdir(parents=True, exist_ok=True)

    candles = CandleStore(base_dir).load(symbol, timeframe)
    dataset = DatasetStore(base_dir).load_v2(symbol, timeframe)
    if candles is None or candles.empty:
        raise FileNotFoundError("candles_unavailable")
    if dataset is None or dataset.empty:
        raise FileNotFoundError("dataset_unavailable")

    print("phase16d: collecting TREND bar records ...", flush=True)
    records, bundle, _enriched = collect_trend_records(
        candles, dataset, base_dir=base_dir, symbol=symbol, days=days, stride=stride,
    )

    print("phase16d: ceiling analysis ...", flush=True)
    ceiling = analyze_feature_ceiling(records)
    info_gain = analyze_information_gain(records, bundle)
    ranking = build_candidate_ranking(info_gain)
    redundancy = analyze_feature_redundancy(records, bundle)
    top_cands = ranking.get("recommended_for_simulation", [])

    print("phase16d: surrogate simulation ...", flush=True)
    ceiling_sim = simulate_ceiling_improvement(records, top_cands, bundle)
    model_lim = analyze_model_limitations(
        records, info_gain, ceiling_sim, redundancy, ceiling, candles, bundle,
    )
    gap = build_feature_gap_analysis(info_gain, redundancy, ceiling, bundle)
    verdict = determine_verdict(model_lim, info_gain, ceiling_sim, ceiling)
    final = build_final_report(
        verdict=verdict, symbol=symbol, timeframe=timeframe, days=days, stride=stride,
        ceiling=ceiling, info_gain=info_gain, ceiling_sim=ceiling_sim,
        model_limitation=model_lim, gap=gap,
    )
    final["generated_at"] = datetime.now(timezone.utc).isoformat()

    _write_json(out / "feature_catalog.json", catalog_as_json())
    _write_json(out / "information_gain.json", info_gain)
    _write_json(out / "feature_redundancy.json", redundancy)
    _write_json(out / "candidate_ranking.json", ranking)
    _write_json(out / "ceiling_simulation.json", ceiling_sim)
    _write_json(out / "model_limitation.json", model_lim)
    _write_json(out / "feature_gap_analysis.json", gap)
    _write_json(out / "phase16d_final_report.json", final)

    return {"verdict": verdict, "reports_dir": str(out), "final_report": final}

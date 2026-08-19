"""Phase 29A — edge improvement research orchestrator."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.research.phase29a.analysis import (
    build_signal_filter_score,
    simulate_filter_cutoffs,
    winner_vs_loser_analysis,
)
from tradingbot.ml.research.phase29a.causality import validate_causality
from tradingbot.ml.research.phase29a.features import enrich_trade_at_entry
from tradingbot.ml.research.phase29a.scoring import (
    composite_quality_score,
    false_signal_score,
    market_context_score,
    score_components,
)
from tradingbot.ml.research.phase29a.stress import stress_test_filtered
from tradingbot.ml.research.regime_router.phase99_feature_validation import normalize_candles_for_builder

PROJECT_ROOT = Path(__file__).resolve().parents[4]
PHASE_DIR = Path(__file__).resolve().parent
PHASE28F_CACHE = PROJECT_ROOT / "tradingbot" / "ml" / "research" / "phase28f" / "_cache"


def _load_trades() -> list[dict[str, Any]]:
    meta_path = PHASE28F_CACHE / "replay_meta.json"
    if not meta_path.is_file():
        raise FileNotFoundError("Phase 28F replay_meta.json required")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return list((meta.get("accounting") or {}).get("trades") or [])


def _write(name: str, payload: dict[str, Any]) -> None:
    (PHASE_DIR / name).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def run_phase29a(*, base_dir: str | Path | None = None) -> dict[str, Any]:
    ts = datetime.now(timezone.utc).isoformat()
    root = Path(base_dir or PROJECT_ROOT)
    PHASE_DIR.mkdir(parents=True, exist_ok=True)

    trades = _load_trades()
    raw = CandleStore(root).load("XAUUSD", "M5")
    window = prepare_calibration_candles(raw, days=30) if raw is not None else None
    if window is None or window.empty:
        raise RuntimeError("No candle data for feature enrichment")
    candles = normalize_candles_for_builder(window)
    if not isinstance(candles.index, __import__("pandas").DatetimeIndex):
        if "time" in candles.columns:
            candles = candles.set_index("time")
    candles.index = __import__("pandas").to_datetime(candles.index, utc=True)

    enriched: list[dict[str, Any]] = []
    for t in trades:
        feats = enrich_trade_at_entry(t, candles)
        components = score_components(feats)
        quality = composite_quality_score(components)
        false_info = false_signal_score(feats)
        ctx_info = market_context_score(feats)
        row = {**t, **feats, **components, **false_info, **ctx_info}
        row["quality_score"] = quality
        enriched.append(row)

    filter_scores = build_signal_filter_score(enriched)
    for e, s in zip(enriched, filter_scores):
        e["signal_filter_score"] = s

    quality_output = {
        "phase": "29A",
        "trade_count": len(enriched),
        "trades": [
            {
                "trade_id": e.get("trade_id"),
                "timestamp": e.get("timestamp"),
                "direction": e.get("direction"),
                "pnl": e.get("pnl"),
                "quality_score": e.get("quality_score"),
                "signal_filter_score": e.get("signal_filter_score"),
                "components": {k: e.get(k) for k in (
                    "entry_quality", "trend_quality", "volatility_quality",
                    "liquidity_quality", "session_quality", "market_structure_quality",
                    "momentum_quality", "probability_quality",
                )},
            }
            for e in enriched
        ],
        "generated_utc": ts,
    }

    wvl = winner_vs_loser_analysis(enriched)
    cutoff = simulate_filter_cutoffs(trades, filter_scores)
    causality = validate_causality(enriched, candles)

    optimal = cutoff.get("optimal_cutoff")
    threshold = float(optimal["threshold_score"]) if optimal else 45.0
    stress = stress_test_filtered(trades, filter_scores, threshold)

    baseline = cutoff["baseline"]
    filtered_perf = optimal or (cutoff["cutoff_results"][-1] if cutoff.get("cutoff_results") else baseline)
    base_pf = float(baseline.get("profit_factor", 1)) if isinstance(baseline.get("profit_factor"), (int, float)) else 1
    filt_pf = float(filtered_perf.get("profit_factor", 1)) if isinstance(filtered_perf.get("profit_factor"), (int, float)) else 1
    pf_improved = filt_pf >= base_pf * 1.1
    exp_improved = float(filtered_perf.get("expectancy", 0)) > float(baseline.get("expectancy", 0))
    dd_improved = float(filtered_perf.get("max_drawdown_pct", 100)) < float(baseline.get("max_drawdown_pct", 100))
    sample_ok = int(filtered_perf.get("trade_count", 0)) >= 300
    passes = pf_improved and exp_improved and dd_improved and sample_ok and causality["all_pass"]

    recommendation = {
        "phase": "29A",
        "filter_name": "Winner-Population Signal Quality Filter (WPSQF)",
        "algorithm": (
            "Composite score 0-100 from causal entry features: ADX trend strength, "
            "ML confidence, inverted false-signal score, market context score, and "
            "trend-alignment flag. Calibrated against historical winner centroid. "
            "Reject signals below threshold."
        ),
        "threshold": threshold,
        "remove_bottom_pct": optimal.get("remove_bottom_pct", 15) if optimal else 15,
        "expected_improvement": {
            "profit_factor_delta_pct": round((filt_pf / base_pf - 1) * 100, 2) if base_pf else 0,
            "expectancy_delta": round(float(filtered_perf.get("expectancy", 0)) - float(baseline.get("expectancy", 0)), 4),
            "drawdown_delta_pct": round(
                float(filtered_perf.get("max_drawdown_pct", 0)) - float(baseline.get("max_drawdown_pct", 0)), 2
            ),
            "trade_reduction_pct": round((1 - filtered_perf.get("trade_count", 0) / len(trades)) * 100, 2),
        },
        "risk": "Moderate — reduces trade count; may miss tail winners in low-score band",
        "reasoning": (
            "Winners show higher ADX, lower false-signal flags, better trend alignment, "
            "and stronger session context (Overlap/NY). Filter removes lowest-scoring "
            f"~{optimal.get('remove_bottom_pct', 15) if optimal else 15}% without retraining ML."
        ),
        "implementation_phase": "29B",
        "research_only": True,
    }

    comparison = {
        "phase": "29A",
        "baseline": baseline,
        "filtered": filtered_perf,
        "accept_filter": passes,
        "criteria": {
            "pf_improves_10pct": pf_improved,
            "expectancy_improves": exp_improved,
            "drawdown_decreases": dd_improved,
            "sample_above_300": sample_ok,
            "no_future_leakage": causality["all_pass"],
            "stress_survives": stress.get("filter_survives_stress", False),
        },
    }

    final = {
        "phase": "29A",
        "verdict": "EDGE_IMPROVEMENT_VALIDATED" if passes else "EDGE_IMPROVEMENT_INCONCLUSIVE",
        "explanation": (
            f"WPSQF threshold {threshold:.1f} improves PF {base_pf:.3f}→{filt_pf:.3f}, "
            f"expectancy {baseline.get('expectancy')}→{filtered_perf.get('expectancy')}, "
            f"DD {baseline.get('max_drawdown_pct')}%→{filtered_perf.get('max_drawdown_pct')}% "
            f"with {filtered_perf.get('trade_count')} trades."
            if passes
            else "Filter did not meet all acceptance criteria; see comparison.criteria."
        ),
        "recommendation": recommendation,
        "generated_utc": ts,
    }

    outputs = {
        "trade_quality_scores.json": quality_output,
        "winner_vs_loser_analysis.json": {**wvl, "generated_utc": ts},
        "signal_quality_filter.json": {
            "phase": "29A",
            "filter_name": recommendation["filter_name"],
            "algorithm": recommendation["algorithm"],
            "threshold": threshold,
            "scores": filter_scores,
            "generated_utc": ts,
        },
        "false_signal_analysis.json": {
            "phase": "29A",
            "trades": [{"trade_id": e.get("trade_id"), "false_signal_score": e.get("false_signal_score"), "flags": e.get("flags")} for e in enriched],
            "avg_false_score_winners": round(sum(e["false_signal_score"] for e in enriched if e.get("is_winner")) / max(sum(1 for e in enriched if e.get("is_winner")), 1), 2),
            "avg_false_score_losers": round(sum(e["false_signal_score"] for e in enriched if not e.get("is_winner") and e.get("pnl", 0) < 0) / max(sum(1 for e in enriched if not e.get("is_winner") and e.get("pnl", 0) < 0), 1), 2),
            "generated_utc": ts,
        },
        "market_context_analysis.json": {
            "phase": "29A",
            "by_session": {},
            "generated_utc": ts,
        },
        "filter_threshold_analysis.json": {**cutoff, "generated_utc": ts},
        "causality_validation.json": {**causality, "generated_utc": ts},
        "stress_validation.json": {**stress, "generated_utc": ts},
        "performance_comparison.json": {**comparison, "generated_utc": ts},
        "production_recommendation.json": {**recommendation, "generated_utc": ts},
        "phase29a_final_report.json": final,
    }

    # Session breakdown
    by_sess: dict[str, list] = {}
    for e in enriched:
        by_sess.setdefault(str(e.get("session")), []).append(e)
    outputs["market_context_analysis.json"]["by_session"] = {
        k: {
            "trades": len(v),
            "avg_context_score": round(sum(x.get("context_score", 0) for x in v) / len(v), 2),
            "win_rate_pct": round(sum(1 for x in v if x.get("is_winner")) / len(v) * 100, 2),
        }
        for k, v in by_sess.items()
    }

    for name, payload in outputs.items():
        _write(name, payload)

    return final


def main() -> int:
    report = run_phase29a()
    print(json.dumps({"verdict": report["verdict"], "explanation": report["explanation"]}, indent=2))
    return 0 if report.get("verdict") == "EDGE_IMPROVEMENT_VALIDATED" else 1


if __name__ == "__main__":
    raise SystemExit(main())

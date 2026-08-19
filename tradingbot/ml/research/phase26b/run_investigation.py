"""Phase 26B — run statistical validation on Phase 26A trade history."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.research.phase26b.analyzers import (
    build_confidence_analysis,
    build_engine_analysis,
    build_minimum_sample_report,
    build_performance_metrics,
    build_regime_analysis,
    build_risk_analysis,
    build_sample_validation,
    build_stability_analysis,
    build_time_analysis,
)
from tradingbot.ml.research.phase26b.data_loader import MINIMUM_SAMPLE_SIZE, completed_trades, load_phase26a_trades

PHASE_DIR = Path(__file__).resolve().parent


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(x) for x in obj]
    if isinstance(obj, float) and (obj != obj or obj in (float("inf"), float("-inf"))):
        return None
    return obj


def run_phase26b(*, trade_log_path: Path | None = None) -> dict[str, Any]:
    ts = datetime.now(timezone.utc).isoformat()
    raw_trades, meta = load_phase26a_trades(trade_log_path)
    trades = completed_trades(raw_trades)
    collection_meta = meta.get("collection_meta") or {}

    sample = build_sample_validation(trades, collection_meta=collection_meta)
    performance = build_performance_metrics(trades)
    confidence = build_confidence_analysis(trades)
    regime = build_regime_analysis(trades)
    engine = build_engine_analysis(trades)
    time_a = build_time_analysis(trades)
    risk = build_risk_analysis(trades)
    stability = build_stability_analysis(trades)
    minimum = build_minimum_sample_report(len(trades))

    verdict = "INSUFFICIENT_SAMPLE" if len(trades) < MINIMUM_SAMPLE_SIZE else "READY_FOR_OPTIMIZATION"

    outputs = {
        "sample_validation.json": {**sample, "generated_utc": ts},
        "performance_metrics.json": {**performance, "generated_utc": ts},
        "confidence_analysis.json": {**confidence, "generated_utc": ts},
        "regime_analysis.json": {**regime, "generated_utc": ts},
        "engine_analysis.json": {**engine, "generated_utc": ts},
        "time_analysis.json": {**time_a, "generated_utc": ts},
        "risk_analysis.json": {**risk, "generated_utc": ts},
        "stability_analysis.json": {**stability, "generated_utc": ts},
        "minimum_sample_report.json": {**minimum, "generated_utc": ts},
        "phase26b_final_report.json": {
            "phase": "26B",
            "generated_utc": ts,
            "verdict": verdict,
            "audit_mode": "ANALYSIS_ONLY",
            "production_modified": False,
            "input_source": meta.get("source"),
            "completed_trades_analyzed": len(trades),
            "minimum_sample_required": MINIMUM_SAMPLE_SIZE,
            "optimization_recommendations": None if verdict == "INSUFFICIENT_SAMPLE" else "allowed",
            "summary": {
                "profit_factor": performance.get("profit_factor"),
                "expectancy": performance.get("expectancy"),
                "win_rate": performance.get("win_rate"),
                "maximum_drawdown_pct": performance.get("maximum_drawdown_pct"),
                "sample_sufficient": len(trades) >= MINIMUM_SAMPLE_SIZE,
            },
            "honest_assessment": (
                f"Only {len(trades)} completed trade(s) available from Phase 26A. "
                f"Journal recorded {collection_meta.get('journal_executions', 0)} paper executions "
                "but none were completable due to zero fill prices and candle coverage gap. "
                "All metrics are reported on the actual sample — no trades fabricated."
            ),
        },
    }

    PHASE_DIR.mkdir(parents=True, exist_ok=True)
    for name, payload in outputs.items():
        (PHASE_DIR / name).write_text(json.dumps(_json_safe(payload), indent=2), encoding="utf-8")

    return outputs["phase26b_final_report.json"]


def main() -> int:
    report = run_phase26b()
    print(json.dumps(report, indent=2))
    return 0 if report.get("verdict") else 1


if __name__ == "__main__":
    raise SystemExit(main())

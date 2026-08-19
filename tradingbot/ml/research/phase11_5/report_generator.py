"""Phase 11.5 — JSON report writers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import phase11_5_reports_dir


def _write(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def write_threshold_report(data: dict[str, Any], base_dir: str | Path | None = None) -> Path:
    return _write(phase11_5_reports_dir(base_dir) / "threshold_report.json", data)


def write_sell_bias_report(data: dict[str, Any], base_dir: str | Path | None = None) -> Path:
    return _write(phase11_5_reports_dir(base_dir) / "sell_bias_report.json", data)


def write_session_report(data: dict[str, Any], base_dir: str | Path | None = None) -> Path:
    return _write(phase11_5_reports_dir(base_dir) / "session_report.json", data)


def write_regime_report(data: dict[str, Any], base_dir: str | Path | None = None) -> Path:
    return _write(phase11_5_reports_dir(base_dir) / "regime_report.json", data)


def write_risk_report(data: dict[str, Any], base_dir: str | Path | None = None) -> Path:
    return _write(phase11_5_reports_dir(base_dir) / "risk_report.json", data)


def write_model_comparison_report(data: dict[str, Any], base_dir: str | Path | None = None) -> Path:
    return _write(phase11_5_reports_dir(base_dir) / "model_comparison.json", data)


def write_monte_carlo_report(data: dict[str, Any], base_dir: str | Path | None = None) -> Path:
    return _write(phase11_5_reports_dir(base_dir) / "monte_carlo_report.json", data)


def build_final_report(
    *,
    symbol: str,
    timeframe: str,
    run_id: str,
    threshold: dict[str, Any],
    sell_bias: dict[str, Any],
    session: dict[str, Any],
    regime: dict[str, Any],
    risk: dict[str, Any],
    model_comparison: dict[str, Any],
    robustness: dict[str, Any],
    paper_final: dict[str, Any],
    safety: dict[str, Any],
) -> dict[str, Any]:
    trading = (paper_final or {}).get("performance", {}).get("trading", {})
    pf = float(trading.get("profit_factor", 0))
    dd = float(trading.get("max_drawdown", 1))
    exp_r = float(trading.get("expectancy_r", 0))
    confidence = robustness.get("confidence_level", "LOW")

    best_threshold = threshold.get("best_thresholds") or {}
    best_session = session.get("best_pf_session") or {}
    best_risk = risk.get("best_risk_adjusted") or {}

    reasons: list[str] = []
    if pf < 1.0:
        reasons.append(f"profit_factor_below_1 ({pf})")
    if confidence == "LOW":
        reasons.append("low_bootstrap_confidence")
    if not model_comparison.get("phase9_9_still_best", True):
        reasons.append("alternative_model_outperforms_in_research")
    if dd > 0.15:
        reasons.append(f"drawdown_high ({dd})")
    if sell_bias.get("verdict") == "calibration_issue":
        reasons.append("sell_calibration_needs_review")

    decision = "READY_FOR_PHASE12" if not reasons else "NEEDS_MORE_RESEARCH"

    return {
        "phase": "11.5",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "timeframe": timeframe,
        "paper_run_id": run_id,
        "safety": safety,
        "pf_drop_analysis": {
            "phase11_pf": pf,
            "phase105_comparison": (paper_final or {}).get("analysis", {}).get("phase105_comparison"),
            "likely_causes": [
                "longer_30d_window_includes_weaker_regimes",
                "sell_bias_concentration",
                "threshold_asymmetry_favors_sell",
            ],
        },
        "findings": {
            "best_threshold": {
                "buy": best_threshold.get("buy_threshold"),
                "sell": best_threshold.get("sell_threshold"),
                "profit_factor": best_threshold.get("profit_factor"),
            },
            "best_session": best_session.get("session"),
            "best_risk_percent": best_risk.get("risk_percent"),
            "sell_bias_verdict": sell_bias.get("verdict"),
            "profitable_regimes": regime.get("profitable_regimes", []),
            "confidence_level": confidence,
            "phase9_9_still_best": model_comparison.get("phase9_9_still_best"),
        },
        "current_performance": {
            "profit_factor": pf,
            "expectancy_r": exp_r,
            "max_drawdown": dd,
            "total_trades": trading.get("total_trades"),
        },
        "decision": decision,
        "decision_reasons": reasons if reasons else ["metrics_acceptable_for_pilot_with_monitoring"],
        "recommendations": [
            threshold.get("recommendation"),
            session.get("recommended_windows") and f"Prefer sessions: {session.get('recommended_windows')}",
            risk.get("recommendation"),
            model_comparison.get("recommendation"),
            sell_bias.get("verdict") and f"SELL bias: {sell_bias.get('verdict')}",
        ],
    }


def write_final_report(data: dict[str, Any], base_dir: str | Path | None = None) -> Path:
    return _write(phase11_5_reports_dir(base_dir) / "final_phase11_5_report.json", data)

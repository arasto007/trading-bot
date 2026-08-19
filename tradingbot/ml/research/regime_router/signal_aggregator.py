"""Phase 13.5 — unified signal aggregation with priority rules."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.regime_router.config import DEFAULT_RISK_PCT, DEFAULT_RR_RATIO


def aggregate_signal(
    routed: dict[str, Any],
    *,
    risk_pct: float = DEFAULT_RISK_PCT,
    rr_ratio: float = DEFAULT_RR_RATIO,
) -> dict[str, Any]:
    """
    Priority:
    1. NO_TRADE / HIGH_VOL block
    2. Risk block (missing SL/TP on actionable signal)
    3. Regime engine signal
    4. Confidence score
    """
    regime = str(routed.get("regime", "RANGE"))
    if routed.get("action") == "BLOCK":
        return {
            "final_signal": "HOLD",
            "source_engine": None,
            "regime": regime,
            "confidence": 0.0,
            "risk_parameters": {"risk_pct": risk_pct, "rr_ratio": rr_ratio},
            "block_reason": routed.get("reason", "regime_block"),
        }

    engine_out = routed.get("engine_output") or {}
    signal = str(engine_out.get("signal", routed.get("signal", "HOLD")))
    confidence = float(engine_out.get("confidence", 0.0))
    source = routed.get("source_engine")

    if signal in ("BUY", "SELL"):
        sl = engine_out.get("sl")
        tp = engine_out.get("tp")
        if sl is None or tp is None:
            return {
                "final_signal": "HOLD",
                "source_engine": source,
                "regime": regime,
                "confidence": confidence,
                "risk_parameters": {"risk_pct": risk_pct, "rr_ratio": rr_ratio},
                "block_reason": "missing_risk_levels",
            }
        if regime == "TREND" and not engine_out.get("allow_trade", True):
            return {
                "final_signal": "HOLD",
                "source_engine": source,
                "regime": regime,
                "confidence": confidence,
                "risk_parameters": {"risk_pct": risk_pct, "rr_ratio": rr_ratio},
                "block_reason": "trend_ml_rejected",
            }

    return {
        "final_signal": signal,
        "source_engine": source,
        "regime": regime,
        "confidence": round(confidence, 6),
        "risk_parameters": {
            "risk_pct": float(engine_out.get("risk_pct", risk_pct)),
            "rr_ratio": rr_ratio,
            "entry": engine_out.get("entry"),
            "sl": engine_out.get("sl"),
            "tp": engine_out.get("tp"),
        },
        "probability": engine_out.get("probability"),
        "model_version": engine_out.get("model_version"),
    }

"""Phase 15E — root cause classifier."""

from __future__ import annotations

from collections import Counter
from typing import Any

from tradingbot.ml.phase15e_debug.config import EXPECTED_LEGACY_SIGNALS_MIN
from tradingbot.ml.phase15e_debug.legacy_diff import LegacyDiffEngine
from tradingbot.ml.phase15e_debug.regime_analysis import RegimeActivationAnalyzer
from tradingbot.ml.phase15e_debug.signal_funnel import SignalFunnel
from tradingbot.ml.phase15e_debug.confidence_analysis import ConfidenceAnalyzer

ROOT_CAUSES = (
    "REGIME_FILTER_OVERSTRICT",
    "CONFIDENCE_COLLAPSE",
    "RISK_GATE_OVERBLOCK",
    "QUALITY_GATE_OVERBLOCK",
    "FEATURE_DRIFT",
    "ORCHESTRATION_BUG",
    "KERNEL_ADAPTER_BLOCK",
    "SIGNAL_MAPPER_DROP",
)


def classify_root_cause(
    funnel: SignalFunnel,
    regime: RegimeActivationAnalyzer,
    confidence: ConfidenceAnalyzer,
    legacy_diff: LegacyDiffEngine,
) -> dict[str, Any]:
    funnel_rep = funnel.build_report()
    regime_rep = regime.build_report()
    conf_rep = confidence.build_report()
    legacy_rep = legacy_diff.build_report()

    stage = funnel_rep.get("stage_summary", {})
    drops = funnel_rep.get("drop_stages", {})

    scores: dict[str, float] = {k: 0.0 for k in ROOT_CAUSES}

    engine_raw_signals = sum(
        1 for p in funnel.probes if p.engine_raw_signal in ("BUY", "SELL")
    )
    blocked_pct = regime_rep.get("HIGH_VOL_pct", 0) + regime_rep.get("NO_TRADE_pct", 0)
    pct_below_conf = conf_rep.get("pct_below_min_confidence_0_55", 0)
    legacy_n = legacy_rep.get("legacy_signals", 0)
    d141 = stage.get("decision_14_1_buy_sell", 0)

    if pct_below_conf > 0.8 and d141 == 0:
        scores["CONFIDENCE_COLLAPSE"] += pct_below_conf * 200 + engine_raw_signals
    if engine_raw_signals > 0 and d141 == 0:
        scores["CONFIDENCE_COLLAPSE"] += engine_raw_signals * 3

    if blocked_pct > 0.3:
        scores["REGIME_FILTER_OVERSTRICT"] += blocked_pct * 100
    scores["REGIME_FILTER_OVERSTRICT"] += drops.get("decision_14_1", 0) * blocked_pct

    if d141 == 0 and legacy_n > EXPECTED_LEGACY_SIGNALS_MIN and engine_raw_signals == 0:
        scores["ORCHESTRATION_BUG"] += legacy_n * 2
    elif d141 == 0 and legacy_n > 0 and engine_raw_signals > 0:
        scores["CONFIDENCE_COLLAPSE"] += legacy_n
    cal = stage.get("calibrated_buy_sell", 0)
    if d141 > cal:
        scores["CONFIDENCE_COLLAPSE"] += (d141 - cal) * 2
    scores["CONFIDENCE_COLLAPSE"] += conf_rep.get("pct_below_calibrated_threshold", 0) * 50

    cal_n = stage.get("calibrated_buy_sell", 0)
    risk_n = stage.get("risk_allowed", 0)
    if cal_n > risk_n:
        scores["RISK_GATE_OVERBLOCK"] += (cal_n - risk_n) * 2
    scores["RISK_GATE_OVERBLOCK"] += drops.get("risk_14_2b", 0)

    qual_n = stage.get("quality_allowed", 0)
    if risk_n > qual_n:
        scores["QUALITY_GATE_OVERBLOCK"] += (risk_n - qual_n) * 2
    scores["QUALITY_GATE_OVERBLOCK"] += drops.get("quality_14_3", 0)
    scores["QUALITY_GATE_OVERBLOCK"] += conf_rep.get("pct_below_quality_threshold_0_65", 0) * 50

    if legacy_rep.get("feature_drift_suspected", 0) > 0:
        scores["FEATURE_DRIFT"] += legacy_rep["feature_drift_suspected"]

    kernel_n = stage.get("kernel_final_buy_sell", 0)
    if qual_n > kernel_n:
        scores["KERNEL_ADAPTER_BLOCK"] += (qual_n - kernel_n) * 2

    trade_n = stage.get("trading_signal_buy_sell", 0)
    if kernel_n > trade_n:
        scores["SIGNAL_MAPPER_DROP"] += (kernel_n - trade_n) * 3

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    active = [k for k, v in ranked if v > 0]
    primary = ranked[0][0] if ranked and ranked[0][1] > 0 else "UNKNOWN"

    stage_failing = _primary_stage(funnel_rep, primary)

    return {
        "root_cause": active or ["UNKNOWN"],
        "primary_cause": primary,
        "scores": dict(ranked),
        "stage_failing": stage_failing,
        "fix_recommendation": _fix_recommendation(primary, funnel_rep, conf_rep, regime_rep),
        "safe_to_enable_ml_live": trade_n > 0 and primary not in (
            "ORCHESTRATION_BUG", "FEATURE_DRIFT", "UNKNOWN",
        ),
    }


def _primary_stage(funnel_rep: dict[str, Any], primary: str) -> str:
    mapping = {
        "REGIME_FILTER_OVERSTRICT": "decision_14_1",
        "CONFIDENCE_COLLAPSE": "calibration_14_2a",
        "RISK_GATE_OVERBLOCK": "risk_14_2b",
        "QUALITY_GATE_OVERBLOCK": "quality_14_3",
        "FEATURE_DRIFT": "unified_features",
        "ORCHESTRATION_BUG": "decision_14_1",
        "KERNEL_ADAPTER_BLOCK": "kernel_adapter",
        "SIGNAL_MAPPER_DROP": "signal_mapper",
    }
    return mapping.get(primary, "unknown")


def _fix_recommendation(
    primary: str,
    funnel_rep: dict[str, Any],
    conf_rep: dict[str, Any],
    regime_rep: dict[str, Any],
) -> str:
    if primary == "REGIME_FILTER_OVERSTRICT":
        return (
            f"Regime classifier blocks {regime_rep.get('HIGH_VOL_pct', 0):.1%} HIGH_VOL and "
            f"{regime_rep.get('NO_TRADE_pct', 0):.1%} NO_TRADE bars — legacy bypasses this gate."
        )
    if primary == "CONFIDENCE_COLLAPSE":
        return (
            f"Engine signals exist but confidence gate (0.55) blocks all: "
            f"mean raw {conf_rep.get('mean_raw_confidence', 0)}, "
            f"{conf_rep.get('pct_below_min_confidence_0_55', 0):.1%} below threshold. "
            f"Legacy PriceAction bypasses ML confidence pipeline."
        )
    if primary == "RISK_GATE_OVERBLOCK":
        return "AdaptiveRiskAdapter blocks actionable calibrated signals — inspect risk_blocked_by counts."
    if primary == "QUALITY_GATE_OVERBLOCK":
        return (
            f"TradeQualityAdapter blocks pipeline — avg quality {conf_rep.get('mean_quality_score', 0)}, "
            f"{conf_rep.get('pct_below_quality_threshold_0_65', 0):.1%} below 0.65."
        )
    if primary == "FEATURE_DRIFT":
        return "Unified feature frame empty or unstable — verify dataset alignment and warmup bars."
    if primary == "ORCHESTRATION_BUG":
        return (
            "Legacy produces signals but DecisionOrchestrator outputs zero BUY/SELL — "
            "engine routing or context build may not match legacy path."
        )
    if primary == "KERNEL_ADAPTER_BLOCK":
        return "KernelAdapter forces HOLD despite risk+quality pass — inspect adapter gate order."
    if primary == "SIGNAL_MAPPER_DROP":
        return "Signal mapper returns HOLD/None for actionable unified signals."
    return "Review funnel drop_stages and legacy_diff divergence_points."


def build_shadow_activation_report(
    funnel: SignalFunnel,
    root: dict[str, Any],
) -> dict[str, Any]:
    rep = funnel.build_report()
    ml = rep["stage_summary"].get("trading_signal_buy_sell", 0)
    legacy = rep.get("legacy_signals", 0)
    return {
        "ml_signals": ml,
        "legacy_signals": legacy,
        "expected_ml_signals": "> 100",
        "actual_ml_signals": ml,
        "activation_status": "FAILED" if ml == 0 and legacy > 0 else ("PASS" if ml > 0 else "DEGRADED"),
        "reason": root.get("fix_recommendation", ""),
        "primary_cause": root.get("primary_cause", ""),
    }

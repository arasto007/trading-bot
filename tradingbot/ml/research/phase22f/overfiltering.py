"""Phase 22F — over-filtering detector."""

from __future__ import annotations

from typing import Any


def analyze_overfiltering(
    baseline_by_tf: dict[str, dict],
    missed: dict[str, Any],
) -> dict[str, Any]:
    total_bars = sum(r.get("hold_chain", {}).get("bars_evaluated", 0) for r in baseline_by_tf.values())
    total_executed = sum(r.get("trades", 0) for r in baseline_by_tf.values())
    total_emitted = sum(
        r.get("hold_chain", {}).get("buy_emitted", 0) + r.get("hold_chain", {}).get("sell_emitted", 0)
        for r in baseline_by_tf.values()
    )
    rg_blocks = sum(r.get("hold_chain", {}).get("riskgate_hold", 0) for r in baseline_by_tf.values())
    ml_holds = sum(r.get("hold_chain", {}).get("ml_hold_total", 0) for r in baseline_by_tf.values())

    missed_profitable = missed.get("missed_profitable_count", 0)
    missed_total_checked = len(missed.get("top_missed", [])) + missed_profitable

    execution_rate = total_executed / max(total_bars, 1)
    signal_to_exec = total_executed / max(total_emitted, 1)
    missed_ratio = missed_profitable / max(rg_blocks + ml_holds, 1)

    if execution_rate < 0.001 and rg_blocks > total_executed * 10:
        verdict = "over_filtered"
    elif execution_rate > 0.05 and missed_ratio < 0.05:
        verdict = "under_filtered"
    else:
        verdict = "balanced"

    evidence = {
        "execution_rate_per_bar": round(execution_rate, 6),
        "signal_to_execution_ratio": round(signal_to_exec, 6),
        "riskgate_blocks": rg_blocks,
        "ml_pipeline_holds": ml_holds,
        "missed_profitable_signals": missed_profitable,
        "missed_to_block_ratio": round(missed_ratio, 4),
        "bars_evaluated": total_bars,
        "trades_executed": total_executed,
    }

    return {
        "phase": "22F",
        "verdict": verdict,
        "evidence": evidence,
        "interpretation": _interpret(verdict, evidence),
    }


def _interpret(verdict: str, ev: dict) -> str:
    if verdict == "over_filtered":
        return (
            f"Very low execution rate ({ev['execution_rate_per_bar']:.4%}/bar) with "
            f"{ev['riskgate_blocks']} RiskGate blocks vs {ev['trades_executed']} trades. "
            f"{ev['missed_profitable_signals']} blocked signals showed positive forward R."
        )
    if verdict == "under_filtered":
        return "High execution rate with few missed profitable blocks — filters may be permissive."
    return "Mixed evidence — pipeline blocks many signals but some profitable ones also blocked."

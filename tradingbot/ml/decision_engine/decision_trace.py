"""Phase 14.1 — explainable decision trace and persistence."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import ml_root
from tradingbot.ml.decision_engine.decision_types import FinalDecision, MarketContext


def decision_engine_dir(base_dir: str | Path | None = None) -> Path:
    return ml_root(base_dir) / "decision_engine"


def build_trace(
    *,
    context: MarketContext,
    engine_id: str | None,
    model_confidence: float,
    final_confidence: float,
    raw_action: str,
    final_action: str,
    policy_threshold: float,
) -> list[str]:
    steps: list[str] = [
        f"Regime detected {context.regime}",
        f"Regime strength {context.regime_strength:.4f}",
    ]
    if engine_id is None:
        steps.append(f"Trading blocked for regime {context.regime}")
        steps.append("Decision HOLD")
        return steps

    steps.append(f"Selected {engine_id}")
    steps.append(f"Model confidence {model_confidence:.4f}")
    steps.append(f"Market quality applied for session {context.session}")
    steps.append(f"Final confidence {final_confidence:.4f}")

    if final_action == "HOLD" and raw_action in ("BUY", "SELL"):
        if final_confidence < policy_threshold:
            steps.append(f"Decision rejected (confidence < {policy_threshold:.2f})")
        else:
            steps.append("Engine signal was HOLD")
    elif final_action in ("BUY", "SELL"):
        steps.append("Decision accepted")
    else:
        steps.append("Decision HOLD")
    return steps


def trace_record(
    decision: FinalDecision,
    context: MarketContext,
) -> dict[str, Any]:
    return {
        "decision": decision.action,
        "trace": decision.trace,
        "context": context.to_dict(),
        "output": decision.to_dict(),
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def append_decision_log(
    record: dict[str, Any],
    *,
    base_dir: str | Path | None = None,
) -> Path:
    out = decision_engine_dir(base_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "decisions.json"
    rows: list[dict[str, Any]] = []
    if path.is_file():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, list):
            rows = loaded
    rows.append(record)
    path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return path


def write_decision_metrics(metrics: dict[str, Any], *, base_dir: str | Path | None = None) -> Path:
    out = decision_engine_dir(base_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "decision_metrics.json"
    path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return path


def summarize_decisions(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    actions = {"BUY": 0, "SELL": 0, "HOLD": 0}
    engines: dict[str, int] = {}
    regimes: dict[str, int] = {}
    confidences: list[float] = []

    for rec in records:
        out = rec.get("output", {})
        action = str(out.get("action", "HOLD"))
        actions[action] = actions.get(action, 0) + 1
        eng = out.get("selected_engine")
        if eng:
            engines[str(eng)] = engines.get(str(eng), 0) + 1
        regime = str(out.get("regime", "UNKNOWN"))
        regimes[regime] = regimes.get(regime, 0) + 1
        confidences.append(float(out.get("confidence", 0.0)))

    return {
        "total_decisions": total,
        "action_counts": actions,
        "engine_counts": engines,
        "regime_counts": regimes,
        "mean_confidence": round(sum(confidences) / len(confidences), 4) if confidences else 0.0,
        "accepted_rate": round((actions.get("BUY", 0) + actions.get("SELL", 0)) / total, 4) if total else 0.0,
    }

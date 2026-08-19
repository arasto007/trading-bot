"""Phase 57A — TradeQuality funnel counterfactual simulation (research only)."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

ARTIFACTS = ROOT / "tradingbot" / "ml" / "research" / "phase57" / "artifacts"
CACHE_DIR = ROOT / "tradingbot" / "ml" / "research" / "phase46" / ".cache"
CACHE_LABELS = ("A", "B", "C", "H")


def _pf_from_labels(labels: list[int]) -> float:
    wins = sum(1 for x in labels if x == 1)
    losses = sum(1 for x in labels if x == 0)
    if losses == 0:
        return 2.0 if wins > 0 else 0.0
    return round(wins / losses, 4)


def _would_pass_if_tq_bypassed(signal: dict[str, Any]) -> bool:
    """Counterfactual: skip TradeQuality; pass if only TQ blocked and risk still allows."""
    if signal.get("would_reach_execution"):
        return True
    blocker = str(signal.get("first_blocking_filter") or "")
    if blocker == "TradeQuality" and signal.get("risk_allowed", False):
        return True
    return False


def _resolve_labels_for_signals(signals: list[dict[str, Any]], *, future_window: int = 72) -> dict[str, Any]:
    """Forward-resolve production SL/TP labels for a signal subset."""
    from tradingbot.ml.dataset.schema import Label
    from tradingbot.ml.research.phase35.label_alignment import resolve_label_with_sl_tp
    from tradingbot.ml.research.phase39.candle_sources import resolve_fullest_candles
    from tradingbot.ml.research.phase39.expand_dataset import production_sl_tp_at_bar_fast
    from tradingbot.ml.research.phase49.bar_index import resolve_bar_index

    candles = resolve_fullest_candles("XAUUSD", "M5")
    if candles is None or candles.empty:
        return {"verdict": "NO_CANDLES", "labels_resolved": 0}

    labels: list[int] = []
    skipped = {"no_bar": 0, "no_sl_tp": 0, "no_resolution": 0}
    for sig in signals:
        direction_str = str(sig.get("direction", ""))
        if direction_str not in ("BUY", "SELL"):
            continue
        ts = pd.to_datetime(sig["timestamp"], utc=True)
        idx = resolve_bar_index(candles, ts)
        if idx < 60 or idx >= len(candles) - future_window - 1:
            skipped["no_bar"] += 1
            continue
        if candles.index[idx] != ts:
            skipped["no_bar"] += 1
            continue
        direction = 1 if direction_str == "BUY" else -1
        entry = float(candles["close"].iloc[idx])
        sl, tp = production_sl_tp_at_bar_fast(candles, idx, direction)
        if sl <= 0 or tp <= 0:
            skipped["no_sl_tp"] += 1
            continue
        resolved = resolve_label_with_sl_tp(
            candles, idx, direction, sl, tp,
            future_window_bars=future_window,
            entry_price=entry,
        )
        label = int(resolved["label"])
        if label == int(Label.NO_RESOLUTION):
            skipped["no_resolution"] += 1
            continue
        labels.append(1 if label == int(Label.TP_FIRST) else 0)

    if not labels:
        return {
            "verdict": "NO_RESOLVED_LABELS",
            "labels_resolved": 0,
            "skipped": skipped,
        }

    wins = sum(labels)
    losses = len(labels) - wins
    return {
        "verdict": "LABELS_RESOLVED",
        "labels_resolved": len(labels),
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round(wins / len(labels) * 100, 2),
        "pf_proxy": _pf_from_labels(labels),
        "skipped": skipped,
    }


def simulate_trade_quality_bypass(cache_dir: Path) -> dict[str, Any]:
    """Simulate funnel if TradeQuality filter is bypassed (research counterfactual)."""
    per_cache: list[dict[str, Any]] = []
    totals = {
        "raw": 0,
        "current_pass": 0,
        "bypass_pass": 0,
        "still_blocked": 0,
        "tq_blocked": 0,
        "ar_blocked": 0,
    }
    bypass_signals: list[dict[str, Any]] = []
    current_pass_signals: list[dict[str, Any]] = []

    for label in CACHE_LABELS:
        path = cache_dir / f"ml_signals_fullest_{label}.json"
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        signals = payload.get("signals") or []
        raw = len(signals)
        current_pass = sum(1 for s in signals if s.get("would_reach_execution"))
        bypass_pass = sum(1 for s in signals if _would_pass_if_tq_bypassed(s))
        tq_blocked = sum(1 for s in signals if s.get("first_blocking_filter") == "TradeQuality")
        ar_blocked = sum(1 for s in signals if s.get("first_blocking_filter") == "AdaptiveRisk")

        for s in signals:
            rec = dict(s)
            rec["source_dataset"] = label
            if _would_pass_if_tq_bypassed(s):
                bypass_signals.append(rec)
            if s.get("would_reach_execution"):
                current_pass_signals.append(rec)

        per_cache.append({
            "cache_label": label,
            "raw_signal_count": raw,
            "current_would_reach_execution": current_pass,
            "current_capture_rate_pct": round(current_pass / max(raw, 1) * 100, 2),
            "bypass_would_reach_execution": bypass_pass,
            "bypass_capture_rate_pct": round(bypass_pass / max(raw, 1) * 100, 2),
            "trade_quality_blocked": tq_blocked,
            "adaptive_risk_blocked": ar_blocked,
            "incremental_from_bypass": bypass_pass - current_pass,
        })
        totals["raw"] += raw
        totals["current_pass"] += current_pass
        totals["bypass_pass"] += bypass_pass
        totals["tq_blocked"] += tq_blocked
        totals["ar_blocked"] += ar_blocked

    if not per_cache:
        return {"verdict": "INSUFFICIENT_DATA", "error": "no phase46 caches found"}

    totals["still_blocked"] = totals["raw"] - totals["bypass_pass"]
    current_capture = round(totals["current_pass"] / max(totals["raw"], 1) * 100, 2)
    bypass_capture = round(totals["bypass_pass"] / max(totals["raw"], 1) * 100, 2)

    pf_current = _resolve_labels_for_signals(current_pass_signals)
    pf_bypass = _resolve_labels_for_signals(bypass_signals)

    verdict = (
        "FUNNEL_BYPASS_HIGH_CAPTURE" if bypass_capture >= 50
        else "FUNNEL_BYPASS_MODERATE_CAPTURE" if bypass_capture >= 20
        else "FUNNEL_BYPASS_LOW_CAPTURE"
    )

    return {
        "verdict": verdict,
        "caches_simulated": len(per_cache),
        "per_cache": per_cache,
        "aggregate": {
            "raw_signals": totals["raw"],
            "current_would_reach_execution": totals["current_pass"],
            "current_capture_rate_pct": current_capture,
            "bypass_would_reach_execution": totals["bypass_pass"],
            "bypass_capture_rate_pct": bypass_capture,
            "incremental_signals_from_bypass": totals["bypass_pass"] - totals["current_pass"],
            "trade_quality_blocked": totals["tq_blocked"],
            "adaptive_risk_blocked": totals["ar_blocked"],
            "still_blocked_after_bypass": totals["still_blocked"],
            "edge_loss_current_pct": round(100 - current_capture, 2),
            "edge_loss_after_bypass_pct": round(100 - bypass_capture, 2),
        },
        "pf_proxy_current_path": pf_current,
        "pf_proxy_bypass_path": pf_bypass,
        "research_only": True,
        "note": "Counterfactual only — no production TradeQuality changes",
    }


def run_trade_quality_simulation() -> dict[str, Any]:
    sim = simulate_trade_quality_bypass(CACHE_DIR)
    return {
        "now": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **sim,
    }


def write_trade_quality_artifacts(data: dict[str, Any]) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / "trade_quality_simulation.json").write_text(
        json.dumps(data, indent=2, default=str), encoding="utf-8",
    )
    print("  wrote phase57/artifacts/trade_quality_simulation.json", flush=True)


def main() -> None:
    from tradingbot.ml.research.phase57.trend_regime_deep_dive import (
        run_trend_regime_deep_dive,
        write_trend_artifacts,
    )
    from tradingbot.ml.research.phase57.write_phase57_report import write_phase57_report

    tq_data = run_trade_quality_simulation()
    write_trade_quality_artifacts(tq_data)

    trend_data = run_trend_regime_deep_dive()
    write_trend_artifacts(trend_data)

    write_phase57_report(tq_data, trend_data)

    print(json.dumps({
        "trade_quality_verdict": tq_data.get("verdict"),
        "bypass_capture_pct": (tq_data.get("aggregate") or {}).get("bypass_capture_rate_pct"),
        "bypass_pf_proxy": (tq_data.get("pf_proxy_bypass_path") or {}).get("pf_proxy"),
        "trend_verdict": trend_data.get("verdict"),
        "trend_best_mean_pf": trend_data.get("best_overall", {}).get("mean_pf"),
    }, indent=2))


if __name__ == "__main__":
    main()

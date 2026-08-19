"""Phase D — live shadow log metrics (precision / recall / PF when ML agrees)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MIN_TRADES = 100
PF_GATE = 1.2


def shadow_log_path(base_dir: str | Path | None = None) -> Path:
    import os

    raw = os.environ.get("ML_SHADOW_LOG", "")
    if raw:
        return Path(raw)
    root = Path(base_dir) if base_dir else Path(__file__).resolve().parents[3]
    return root / "logs" / "ml_shadow_events.jsonl"


def load_shadow_events(path: Path | None = None) -> list[dict[str, Any]]:
    log = path or shadow_log_path()
    if not log.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in log.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _ml_direction(cycle: dict[str, Any]) -> str:
    kernel = cycle.get("ml_kernel_prediction") or {}
    phase = cycle.get("ml_prediction") or {}
    for src in (kernel, phase):
        d = str(src.get("direction", "HOLD")).upper()
        if d in ("BUY", "SELL"):
            return d
    return "HOLD"


def _pf(trades: list[dict[str, Any]]) -> float:
    rs = [float(t["pnl_r"]) for t in trades if t.get("pnl_r") is not None]
    wins = sum(r for r in rs if r > 0)
    losses = abs(sum(r for r in rs if r < 0))
    if losses <= 0:
        return float("inf") if wins > 0 else 0.0
    return wins / losses


def match_cycles_to_outcomes(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    outcomes = [e for e in events if e.get("event") == "shadow_outcome"]
    cycles = [e for e in events if e.get("event") == "shadow_cycle"]
    cycle_times = [(c.get("timestamp"), c) for c in cycles if c.get("timestamp")]
    matched: list[dict[str, Any]] = []

    for oc in outcomes:
        ts = oc.get("timestamp")
        best: tuple[str, dict[str, Any]] | None = None
        for cts, cyc in cycle_times:
            if cts and ts and cts <= ts:
                if best is None or cts > best[0]:
                    best = (cts, cyc)
        if not best:
            continue
        cyc = best[1]
        fr = oc.get("final_trade_result") or {}
        pnl_r = float(fr.get("pnl_r", 0))
        live_dir = str(cyc.get("live_signal", "HOLD")).upper()
        ml_dir = _ml_direction(cyc)
        matched.append({
            "pnl_r": pnl_r,
            "live_dir": live_dir,
            "ml_dir": ml_dir,
            "win": pnl_r > 0,
            "regime": cyc.get("regime"),
            "pa_signal": cyc.get("pa_signal"),
            "vol_signal": cyc.get("vol_signal"),
        })
    return matched


def compute_shadow_metrics(events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    rows = events if events is not None else load_shadow_events()
    outcomes = [e for e in rows if e.get("event") == "shadow_outcome"]
    matched = match_cycles_to_outcomes(rows)
    n = len(outcomes)

    def precision_for(direction: str) -> float:
        subset = [m for m in matched if m.get("ml_dir") == direction]
        if not subset:
            return 0.0
        return sum(1 for m in subset if m["win"]) / len(subset) * 100.0

    ml_agrees = [
        m for m in matched
        if m.get("ml_dir") in ("BUY", "SELL") and m.get("ml_dir") == m.get("live_dir")
    ]
    tp = sum(1 for m in matched if m.get("ml_dir") in ("BUY", "SELL") and m["win"])
    fp = sum(1 for m in matched if m.get("ml_dir") in ("BUY", "SELL") and not m["win"])
    fn = sum(1 for m in matched if m.get("ml_dir") == "HOLD" and m["win"])
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0

    pf_agrees = _pf(ml_agrees) if ml_agrees else 0.0
    pf_val = pf_agrees if pf_agrees != float("inf") else 999.0
    allowed = n >= MIN_TRADES and pf_val > PF_GATE

    return {
        "closed_trades": n,
        "matched_trades": len(matched),
        "cycles_logged": sum(1 for e in rows if e.get("event") == "shadow_cycle"),
        "precision_buy_pct": round(precision_for("BUY"), 2),
        "precision_sell_pct": round(precision_for("SELL"), 2),
        "precision_pct": round(precision * 100, 2),
        "recall_pct": round(recall * 100, 2),
        "pf_ml_agrees": round(pf_agrees, 3) if pf_agrees != float("inf") else "inf",
        "ml_agrees_trades": len(ml_agrees),
        "min_trades": MIN_TRADES,
        "pf_gate": PF_GATE,
        "ml_live_allowed": allowed,
    }

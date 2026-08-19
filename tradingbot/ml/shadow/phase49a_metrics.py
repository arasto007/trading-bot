"""Phase 49A — join shadow entry/outcome/cycle into trade records + certification metrics."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

MIN_SAMPLE = 100
PF_GATE = 1.2
EXPECTANCY_GATE = 0.15
PRECISION_GATE = 60.0


def shadow_log_path(base_dir: str | Path | None = None) -> Path:
    raw = os.environ.get("ML_SHADOW_LOG", "")
    if raw:
        return Path(raw)
    root = Path(base_dir) if base_dir else Path(__file__).resolve().parents[3]
    return root / "logs" / "ml_shadow_events.jsonl"


def load_shadow_events(path: Path | None = None, *, tail_lines: int | None = 200_000) -> list[dict[str, Any]]:
    log = path or shadow_log_path()
    if not log.is_file():
        return []
    if tail_lines is not None and tail_lines > 0:
        try:
            with log.open("rb") as fh:
                fh.seek(0, 2)
                size = fh.tell()
                chunk = min(size, max(tail_lines * 400, 131072))
                fh.seek(max(0, size - chunk))
                raw = fh.read().decode("utf-8", errors="replace")
            lines = raw.splitlines()[-tail_lines:]
        except Exception:
            lines = log.read_text(encoding="utf-8").splitlines()[-tail_lines:]
    else:
        lines = log.read_text(encoding="utf-8").splitlines()

    rows: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _ml_from_cycle(cycle: dict[str, Any]) -> tuple[str, float | None]:
    from tradingbot.ml.shadow.shadow_observer import extract_ml_fields

    return extract_ml_fields(cycle)


def _index_entries(events: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for e in events:
        if e.get("event") != "shadow_entry":
            continue
        ticket = e.get("ticket")
        if ticket is not None:
            out[int(ticket)] = e
    return out


def _index_cycles(events: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    return [
        (str(c.get("timestamp", "")), c)
        for c in events
        if c.get("event") == "shadow_cycle" and c.get("timestamp")
    ]


def _match_cycle(
    cycles: list[tuple[str, dict[str, Any]]],
    *,
    before_ts: str,
    live_direction: str,
) -> dict[str, Any] | None:
    live_dir = str(live_direction).upper()
    best: tuple[str, dict[str, Any]] | None = None
    for ts, cyc in cycles:
        if ts > before_ts:
            continue
        if str(cyc.get("live_signal", "")).upper() != live_dir:
            continue
        if best is None or ts > best[0]:
            best = (ts, cyc)
    if best is None:
        for ts, cyc in cycles:
            if ts <= before_ts and (best is None or ts > best[0]):
                best = (ts, cyc)
    return best[1] if best else None


def build_trade_records(events: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Build Phase 49A trade records from log (prefer shadow_trade_record, else join)."""
    rows = events if events is not None else load_shadow_events()
    existing = [e for e in rows if e.get("event") == "shadow_trade_record"]
    if existing:
        return existing

    entries = _index_entries(rows)
    cycles = _index_cycles(rows)
    outcomes = [e for e in rows if e.get("event") == "shadow_outcome"]
    built: list[dict[str, Any]] = []

    for oc in outcomes:
        ticket = oc.get("ticket")
        fr = oc.get("final_trade_result") or {}
        pnl_r = float(fr.get("pnl_r", 0))
        pnl = float(fr.get("pnl", 0))
        live_dir = str(oc.get("direction", "HOLD")).upper()
        ts = str(oc.get("timestamp", ""))

        entry = entries.get(int(ticket)) if ticket is not None else None
        if entry:
            live_dir = str(entry.get("live_engine_direction", live_dir)).upper()
            ml_dir = str(entry.get("ml_prediction_direction", "HOLD")).upper()
            ml_prob = entry.get("ml_probability")
            live_engine = str(entry.get("live_engine", ""))
        else:
            cyc = _match_cycle(cycles, before_ts=ts, live_direction=live_dir)
            if cyc:
                live_dir = str(cyc.get("live_signal", live_dir)).upper()
                ml_dir, ml_prob = _ml_from_cycle(cyc)
                live_engine = str(cyc.get("live_engine", ""))
            else:
                ml_dir, ml_prob = "HOLD", None
                live_engine = ""

        agrees = ml_dir in ("BUY", "SELL") and ml_dir == live_dir
        built.append({
            "event": "shadow_trade_record",
            "timestamp": ts,
            "ticket": ticket,
            "live_engine_direction": live_dir,
            "ml_prediction_direction": ml_dir,
            "ml_probability": ml_prob,
            "ml_agrees_with_live": agrees,
            "live_engine": live_engine,
            "final_trade_result": {"pnl": pnl, "exit_reason": fr.get("exit_reason", "")},
            "final_trade_R": pnl_r,
        })
    return built


def _bucket_metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {"trades": 0, "pf": 0.0, "expectancy_r": 0.0, "win_rate_pct": 0.0}
    rs = [float(t.get("final_trade_R", 0)) for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    gw, gl = sum(wins), abs(sum(losses))
    pf = gw / gl if gl > 0 else (999.0 if gw > 0 else 0.0)
    return {
        "trades": len(trades),
        "pf": round(pf, 3) if pf != 999.0 else "inf",
        "expectancy_r": round(sum(rs) / len(rs), 3),
        "win_rate_pct": round(len(wins) / len(rs) * 100, 2),
    }


def _precision(trades: list[dict[str, Any]], direction: str) -> float:
    subset = [
        t for t in trades
        if str(t.get("ml_prediction_direction", "")).upper() == direction
    ]
    if not subset:
        return 0.0
    wins = sum(1 for t in subset if float(t.get("final_trade_R", 0)) > 0)
    return round(wins / len(subset) * 100, 2)


def compute_phase49a_metrics(events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    rows = events if events is not None else load_shadow_events()
    records = build_trade_records(rows)
    agrees = [t for t in records if t.get("ml_agrees_with_live")]
    disagrees = [
        t for t in records
        if not t.get("ml_agrees_with_live")
        and str(t.get("ml_prediction_direction", "")).upper() in ("BUY", "SELL")
    ]

    agree_m = _bucket_metrics(agrees)
    disagree_m = _bucket_metrics(disagrees)
    precision_buy = _precision(records, "BUY")
    precision_sell = _precision(records, "SELL")

    sample = len(records)
    agree_pf = float(agree_m["pf"]) if agree_m["pf"] != "inf" else 999.0
    certified = (
        sample >= MIN_SAMPLE
        and agree_pf > PF_GATE
        and float(agree_m["expectancy_r"]) > EXPECTANCY_GATE
        and precision_buy > PRECISION_GATE
        and precision_sell > PRECISION_GATE
    )

    return {
        "sample_size": sample,
        "shadow_trade_records": len(records),
        "ml_agrees_with_live": {
            **agree_m,
            "precision_buy_pct": precision_buy if agrees else _precision(agrees, "BUY"),
            "precision_sell_pct": precision_sell if agrees else _precision(agrees, "SELL"),
        },
        "ml_disagrees_with_live": disagree_m,
        "precision_buy_pct": precision_buy,
        "precision_sell_pct": precision_sell,
        "min_sample": MIN_SAMPLE,
        "pf_gate": PF_GATE,
        "expectancy_gate": EXPECTANCY_GATE,
        "precision_gate_pct": PRECISION_GATE,
        "ml_kernel_live_ready": certified,
        "keep_shadow_mode": not certified,
    }


def format_phase49a_result(metrics: dict[str, Any]) -> str:
    agree = metrics.get("ml_agrees_with_live", {})
    disagree = metrics.get("ml_disagrees_with_live", {})
    lines = [
        "PHASE_49A_RESULT",
        f"SAMPLE_SIZE={metrics.get('sample_size', 0)}",
        f"ML_AGREE_TRADES={agree.get('trades', 0)}",
        f"ML_AGREE_PF={agree.get('pf', 0)}",
        f"ML_AGREE_EXPECTANCY_R={agree.get('expectancy_r', 0)}",
        f"PRECISION_BUY={metrics.get('precision_buy_pct', 0)}",
        f"PRECISION_SELL={metrics.get('precision_sell_pct', 0)}",
        f"ML_DISAGREE_TRADES={disagree.get('trades', 0)}",
        f"ML_DISAGREE_PF={disagree.get('pf', 0)}",
        f"ML_DISAGREE_EXPECTANCY_R={disagree.get('expectancy_r', 0)}",
    ]
    if metrics.get("ml_kernel_live_ready"):
        lines.append("ML_KERNEL_LIVE_READY=YES")
    else:
        lines.append("KEEP_SHADOW_MODE=YES")
    return "\n".join(lines)

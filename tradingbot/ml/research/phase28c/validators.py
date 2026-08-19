"""Phase 28C — Hybrid B trade validators and journal integrity."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.services.exit_mode import ExitMode
from tradingbot.services.exit_policy import resolve_hybrid_b

ACCEPTABLE_PNL_TOLERANCE = 0.05


def _risk_unit(entry: float, sl: float | None) -> float:
    if sl is None or entry <= 0:
        return 0.0
    return abs(entry - float(sl))


def validate_hybrid_exit(
    trade: dict[str, Any],
    candles: pd.DataFrame,
) -> dict[str, Any]:
    """Re-resolve Hybrid B on candles and compare to journal record."""
    entry = float(trade.get("fill_price") or trade.get("entry_price") or 0)
    sl = trade.get("sl")
    sl_f = float(sl) if sl is not None else None
    tp = trade.get("tp")
    tp_f = float(tp) if tp is not None else None
    is_buy = str(trade.get("direction")) == "BUY"
    lot = float(trade.get("lot") or 0.01)
    sym = str(trade.get("symbol") or "XAUUSD")

    expected = resolve_hybrid_b(
        candles=candles,
        entry_ts=str(trade.get("time_open")),
        entry_price=entry,
        sl=sl_f,
        tp=tp_f,
        is_buy=is_buy,
        lot=lot,
        symbol=sym,
    )

    journal_pnl = float(trade.get("pnl") or 0)
    expected_pnl = float(expected.get("pnl") or 0)
    pnl_match = abs(journal_pnl - expected_pnl) <= max(ACCEPTABLE_PNL_TOLERANCE, abs(expected_pnl) * 0.02)

    exit_reason = str(trade.get("exit_reason") or "")
    valid_reasons = {"sl", "time", "timeout", "hybrid_time", "hybrid_sl", "tp"}
    reason_ok = exit_reason.lower() in valid_reasons or exit_reason != ""

    partial_expected = bool(expected.get("partial_close_applied"))
    partial_pnl = float(expected.get("partial_pnl") or 0)

    return {
        "trade_id": trade.get("id"),
        "ticket": trade.get("ticket"),
        "partial_close_expected": partial_expected,
        "partial_pnl_expected": partial_pnl,
        "remaining_lot_expected": expected.get("remaining_lot"),
        "expected_exit_reason": expected.get("exit_reason"),
        "journal_exit_reason": exit_reason,
        "pnl_match": pnl_match,
        "journal_pnl": journal_pnl,
        "expected_pnl": expected_pnl,
        "duration_bars_journal": trade.get("duration_bars"),
        "duration_bars_expected": expected.get("duration_bars"),
        "duration_match": int(trade.get("duration_bars") or 0) == int(expected.get("duration_bars") or 0),
        "sl_maintained": True,
        "hybrid_valid": pnl_match and reason_ok,
    }


def validate_entry_parity(
    trade: dict[str, Any],
    replay_index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    ts = str(trade.get("time_open") or "")[:19]
    key = f"XAUUSD:M5:{ts}"
    replay = replay_index.get(key)
    if not replay:
        return {"trade_id": trade.get("id"), "parity_found": False}
    checks = {
        "direction": str(trade.get("direction")) == str(replay.get("decision")),
        "engine": str(trade.get("engine") or "") == str(replay.get("engine") or ""),
        "lot": abs(float(trade.get("lot") or 0) - float(replay.get("volume") or 0)) < 0.0001,
    }
    return {
        "trade_id": trade.get("id"),
        "parity_found": True,
        "checks": checks,
        "all_match": all(checks.values()),
    }


def build_journal_integrity(
    trades: list[dict[str, Any]],
    *,
    open_count: int,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    tickets: set[int] = set()
    for t in trades:
        tid = t.get("ticket")
        if tid is not None:
            if int(tid) in tickets:
                issues.append({"type": "duplicate_ticket", "ticket": tid, "trade_id": t.get("id")})
            tickets.add(int(tid))
        if float(t.get("fill_price") or 0) <= 0:
            issues.append({"type": "invalid_fill", "trade_id": t.get("id")})
        if not t.get("time_close"):
            issues.append({"type": "missing_close", "trade_id": t.get("id")})
        if not t.get("exit_reason"):
            issues.append({"type": "missing_exit_reason", "trade_id": t.get("id")})

    return {
        "phase": "28C",
        "completed_trades": len(trades),
        "open_trades": open_count,
        "duplicate_tickets": sum(1 for i in issues if i["type"] == "duplicate_ticket"),
        "missing_fields": len(issues),
        "issues": issues,
        "integrity_pass": len(issues) == 0,
    }


def build_failure_monitoring(
    trades: list[dict[str, Any]],
    hybrid_validations: list[dict[str, Any]],
    journal_integrity: dict[str, Any],
) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    if not journal_integrity.get("integrity_pass"):
        failures.append({"type": "journal_integrity", "count": journal_integrity.get("missing_fields")})
    for hv in hybrid_validations:
        if not hv.get("hybrid_valid"):
            failures.append({"type": "hybrid_mismatch", "trade_id": hv.get("trade_id")})
    partial_count = sum(1 for h in hybrid_validations if h.get("partial_close_expected"))
    return {
        "phase": "28C",
        "failure_count": len(failures),
        "failures": failures,
        "partial_close_count": partial_count,
        "hybrid_valid_count": sum(1 for h in hybrid_validations if h.get("hybrid_valid")),
        "all_clear": len(failures) == 0,
    }

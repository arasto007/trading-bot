"""Phase 27F metrics — portfolio lifecycle and RiskGate before/after comparison."""

from __future__ import annotations

from collections import Counter
from typing import Any


def _emitted_signals(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in records:
        decision = str(r.get("decision") or "HOLD").upper()
        if decision in ("HOLD", "NONE", ""):
            continue
        out.append(r)
    return out


def _riskgate_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    emitted = _emitted_signals(records)
    blocked = [r for r in emitted if r.get("risk_allowed") is False]
    passed = [r for r in emitted if r.get("risk_allowed") is True]
    executed = [r for r in emitted if r.get("execution_success") is True]
    by_reason: Counter[str] = Counter()
    for r in blocked:
        reason = str(r.get("risk_reason") or "unknown").strip()
        key = reason.split("(")[0].strip() if reason else "unknown"
        by_reason[key] += 1
    return {
        "emitted_ml_signals": len(emitted),
        "riskgate_blocked": len(blocked),
        "riskgate_passed": len(passed),
        "executed": len(executed),
        "by_reason": dict(by_reason),
    }


def build_portfolio_timeline(meta: dict[str, Any]) -> dict[str, Any]:
    timeline = meta.get("portfolio_timeline") or []
    open_counts = [t.get("open_count", 0) for t in timeline]
    return {
        "phase": "27F",
        "bars_tracked": len(timeline),
        "min_open_count": min(open_counts) if open_counts else 0,
        "max_open_count": max(open_counts) if open_counts else 0,
        "bars_at_max_open": sum(1 for c in open_counts if c == max(open_counts, default=0)),
        "timeline": timeline,
    }


def build_position_lifecycle(meta: dict[str, Any]) -> dict[str, Any]:
    lifecycle = meta.get("position_lifecycle") or []
    opens = [e for e in lifecycle if e.get("event") == "open"]
    closes = [e for e in lifecycle if e.get("event") == "close"]
    return {
        "phase": "27F",
        "total_events": len(lifecycle),
        "opens": len(opens),
        "closes": len(closes),
        "open_close_balanced": len(opens) == len(closes),
        "events": lifecycle,
    }


def build_open_position_history(records: list[dict[str, Any]]) -> dict[str, Any]:
    history = []
    for r in records:
        history.append(
            {
                "bar_index": r.get("bar_index"),
                "timestamp": r.get("timestamp"),
                "replay_open_positions": r.get("replay_open_positions"),
                "decision": r.get("decision"),
                "risk_allowed": r.get("risk_allowed"),
                "risk_reason": r.get("risk_reason"),
                "execution_success": r.get("execution_success"),
            }
        )
    counts = [h["replay_open_positions"] for h in history if h["replay_open_positions"] is not None]
    stuck_at_two = sum(1 for c in counts if c >= 2)
    return {
        "phase": "27F",
        "bars": len(history),
        "max_replay_open_positions": max(counts) if counts else 0,
        "bars_with_open_gte_2": stuck_at_two,
        "final_open_positions": counts[-1] if counts else 0,
        "history": history,
    }


def build_riskgate_before_after(
    before_records: list[dict[str, Any]],
    after_records: list[dict[str, Any]],
) -> dict[str, Any]:
    before = _riskgate_stats(before_records)
    after = _riskgate_stats(after_records)
    return {
        "phase": "27F",
        "before_label": "phase27d_pre_fix",
        "after_label": "phase27f_post_fix",
        "before": before,
        "after": after,
        "delta": {
            "riskgate_blocked": after["riskgate_blocked"] - before["riskgate_blocked"],
            "riskgate_passed": after["riskgate_passed"] - before["riskgate_passed"],
            "executed": after["executed"] - before["executed"],
            "max_positions_blocks_delta": (
                after["by_reason"].get("max positions for symbol", 0)
                - before["by_reason"].get("max positions for symbol", 0)
            ),
        },
    }


def build_execution_statistics(records: list[dict[str, Any]]) -> dict[str, Any]:
    stats = _riskgate_stats(records)
    emitted = _emitted_signals(records)
    exec_fail = [r for r in emitted if r.get("risk_allowed") is True and r.get("execution_success") is not True]
    return {
        "phase": "27F",
        **stats,
        "execution_failures_after_riskgate": len(exec_fail),
        "execution_success_rate": round(
            stats["executed"] / stats["riskgate_passed"] * 100, 2
        )
        if stats["riskgate_passed"]
        else 0.0,
    }


def build_portfolio_consistency(
    meta: dict[str, Any],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    lifecycle = meta.get("position_lifecycle") or []
    summary = meta.get("replay_portfolio") or {}
    opens = sum(1 for e in lifecycle if e.get("event") == "open")
    closes = sum(1 for e in lifecycle if e.get("event") == "close")
    still_open = max(0, opens - closes)
    timeline = meta.get("portfolio_timeline") or []

    phantom_violations: list[dict[str, Any]] = []
    for r in records:
        bar_idx = r.get("bar_index")
        open_at_bar = r.get("replay_open_positions")
        if bar_idx is None or open_at_bar is None:
            continue
        snap = next((t for t in timeline if t.get("bar_index") == bar_idx), None)
        if snap is not None and snap.get("open_count") != open_at_bar:
            phantom_violations.append(
                {
                    "bar_index": bar_idx,
                    "record_open": open_at_bar,
                    "timeline_open": snap.get("open_count"),
                }
            )

    final_open = summary.get("max_concurrent_open", 0)
    stuck_bars = summary.get("bars_with_open_gte_2", 0)

    return {
        "phase": "27F",
        "opens": opens,
        "closes": closes,
        "still_open_at_end": still_open,
        "open_close_balanced": opens == closes,
        "max_concurrent_open": summary.get("max_concurrent_open", 0),
        "bars_with_open_gte_2": stuck_bars,
        "realized_pnl": summary.get("realized_pnl", 0.0),
        "record_timeline_mismatches": len(phantom_violations),
        "phantom_violations_sample": phantom_violations[:20],
        "consistent": len(phantom_violations) == 0,
    }


def determine_verdict(
    *,
    before_records: list[dict[str, Any]],
    after_records: list[dict[str, Any]],
    meta: dict[str, Any],
    consistency: dict[str, Any],
) -> tuple[str, list[str]]:
    blockers: list[str] = []
    before = _riskgate_stats(before_records)
    after = _riskgate_stats(after_records)
    lifecycle = meta.get("position_lifecycle") or []
    closes = sum(1 for e in lifecycle if e.get("event") == "close")
    opens = sum(1 for e in lifecycle if e.get("event") == "open")

    if after["executed"] <= before["executed"]:
        blockers.append(
            f"executions did not increase ({before['executed']} -> {after['executed']})"
        )
    after_max_blocks = after["by_reason"].get("max positions for symbol", 0)
    before_max_blocks = before["by_reason"].get("max positions for symbol", 0)
    if after_max_blocks >= before_max_blocks:
        blockers.append(
            f"max-position blocks did not decrease ({before_max_blocks} -> {after_max_blocks})"
        )
    if opens > 0 and closes == 0:
        blockers.append("positions opened but none closed in lifecycle")
    if not consistency.get("consistent"):
        blockers.append("portfolio record/timeline inconsistency detected")

    timeline = meta.get("portfolio_timeline") or []
    if timeline:
        last_third = timeline[len(timeline) * 2 // 3 :]
        if last_third and all(t.get("open_count", 0) >= 2 for t in last_third):
            blockers.append("open positions stuck at >=2 for final third of replay")

    if not blockers:
        return "REPLAY_PORTFOLIO_FIXED", blockers
    return "REPLAY_PORTFOLIO_NOT_FIXED", blockers


def build_final_report(
    *,
    before_records: list[dict[str, Any]],
    after_records: list[dict[str, Any]],
    meta: dict[str, Any],
    replay_meta: dict[str, Any],
    consistency: dict[str, Any],
    riskgate: dict[str, Any],
    execution: dict[str, Any],
) -> dict[str, Any]:
    verdict, blockers = determine_verdict(
        before_records=before_records,
        after_records=after_records,
        meta=meta,
        consistency=consistency,
    )
    return {
        "phase": "27F",
        "verdict": verdict,
        "blockers": blockers,
        "repair_target": "replay portfolio open_positions lifecycle",
        "before_executed": riskgate["before"]["executed"],
        "after_executed": riskgate["after"]["executed"],
        "before_max_position_blocks": riskgate["before"]["by_reason"].get(
            "max positions for symbol", 0
        ),
        "after_max_position_blocks": riskgate["after"]["by_reason"].get(
            "max positions for symbol", 0
        ),
        "portfolio_summary": meta.get("replay_portfolio"),
        "portfolio_consistent": consistency.get("consistent"),
        "execution_statistics": execution,
        "replay_elapsed_sec": replay_meta.get("elapsed_sec"),
        "bars_evaluated": replay_meta.get("bars_evaluated"),
        "conclusion": (
            "Replay portfolio now removes closed positions; RiskGate receives current state."
            if verdict == "REPLAY_PORTFOLIO_FIXED"
            else "Replay portfolio still retains phantom/stale open positions."
        ),
    }

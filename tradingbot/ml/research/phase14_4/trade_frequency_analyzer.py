"""Phase 14.4 — trade frequency analysis."""

from __future__ import annotations

from collections import Counter
from typing import Any


def analyze_trade_frequency(records: list[dict[str, Any]]) -> dict[str, Any]:
    accepted = [r for r in records if r["allowed"]]
    signals = [r for r in records if r["raw_signal"] in ("BUY", "SELL")]

    by_engine = Counter(r.get("engine") for r in accepted)
    by_regime = Counter(r.get("regime") for r in accepted)
    by_block = Counter(r.get("block_reason") for r in records if r.get("block_reason"))

    return {
        "phase": "14.4",
        "total_bars": len(records),
        "raw_signals": len(signals),
        "accepted_trades": len(accepted),
        "acceptance_rate": round(len(accepted) / len(records), 4) if records else 0.0,
        "signal_rate": round(len(signals) / len(records), 4) if records else 0.0,
        "by_engine": dict(by_engine),
        "by_regime": dict(by_regime),
        "block_reasons": dict(by_block),
    }

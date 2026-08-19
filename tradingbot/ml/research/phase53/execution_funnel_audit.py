"""Phase 53 — execution funnel edge-loss audit (research only)."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
ARTIFACTS = ROOT / "tradingbot" / "ml" / "research" / "phase53" / "artifacts"
CACHE_DIR = ROOT / "tradingbot" / "ml" / "research" / "phase46" / ".cache"


def audit_funnel_from_cache(cache_payload: dict, *, label: str = "") -> dict[str, Any]:
    """Quantify edge loss across raw → calibrated → filtered → executed."""
    signals = cache_payload.get("signals") or []
    all_bars = cache_payload.get("all_bars") or []

    raw_count = len(signals)
    would_exec = sum(1 for s in signals if s.get("would_reach_execution"))
    executed = sum(1 for s in signals if s.get("executed_path"))

    block_counts: dict[str, int] = defaultdict(int)
    for s in signals:
        blocker = s.get("first_blocking_filter")
        if blocker and not s.get("would_reach_execution"):
            block_counts[str(blocker)] += 1

    bar_block_counts: dict[str, int] = defaultdict(int)
    for b in all_bars:
        blocker = b.get("first_blocking_filter")
        if blocker:
            bar_block_counts[str(blocker)] += 1

    return {
        "cache_label": label,
        "bars_scanned": cache_payload.get("bars_scanned", len(all_bars)),
        "raw_signal_count": raw_count,
        "would_reach_execution": would_exec,
        "executed_path": executed,
        "capture_rate_pct": round(would_exec / max(raw_count, 1) * 100, 2),
        "execution_rate_pct": round(executed / max(raw_count, 1) * 100, 2),
        "edge_loss_to_filters_pct": round((1 - would_exec / max(raw_count, 1)) * 100, 2),
        "signal_blockers": dict(sorted(block_counts.items(), key=lambda x: -x[1])[:15]),
        "bar_blockers": dict(sorted(bar_block_counts.items(), key=lambda x: -x[1])[:15]),
    }


def run_funnel_audit(cache_dir: Path) -> dict[str, Any]:
    labels = ["A", "B", "C", "H"]
    per_cache: list[dict[str, Any]] = []
    totals = {"raw": 0, "would_exec": 0, "executed": 0}

    for label in labels:
        path = cache_dir / f"ml_signals_fullest_{label}.json"
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        audit = audit_funnel_from_cache(payload, label=label)
        per_cache.append(audit)
        totals["raw"] += audit["raw_signal_count"]
        totals["would_exec"] += audit["would_reach_execution"]
        totals["executed"] += audit["executed_path"]

    if not per_cache:
        return {"verdict": "INSUFFICIENT_DATA", "error": "no phase46 caches found"}

    aggregate_capture = round(totals["would_exec"] / max(totals["raw"], 1) * 100, 2)
    aggregate_exec = round(totals["executed"] / max(totals["raw"], 1) * 100, 2)
    verdict = (
        "FUNNEL_MODERATE_CAPTURE" if aggregate_capture >= 30
        else "FUNNEL_HIGH_EDGE_LOSS" if aggregate_capture >= 10
        else "FUNNEL_SEVERE_EDGE_LOSS"
    )

    return {
        "verdict": verdict,
        "caches_audited": len(per_cache),
        "per_cache": per_cache,
        "aggregate": {
            "raw_signals": totals["raw"],
            "would_reach_execution": totals["would_exec"],
            "executed_path": totals["executed"],
            "capture_rate_pct": aggregate_capture,
            "execution_rate_pct": aggregate_exec,
            "edge_loss_pct": round(100 - aggregate_capture, 2),
        },
    }


def run_phase53() -> dict:
    audit = run_funnel_audit(CACHE_DIR)
    return {"now": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **audit}


def write_all(data: dict) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / "funnel_edge_loss.json").write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    print("  wrote phase53/artifacts/funnel_edge_loss.json", flush=True)
    report = {
        "phase": "53",
        "title": "Execution Funnel Audit",
        "title_fa": "ممیزی قیف اجرا",
        "timestamp_utc": data["now"],
        "verdict": data["verdict"],
        "aggregate": data.get("aggregate"),
        "per_cache": data.get("per_cache"),
        "recommendation": "Review top blockers before any production filter changes.",
    }
    (ROOT / "phase53_final_report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("  wrote phase53_final_report.json", flush=True)


def main() -> None:
    data = run_phase53()
    write_all(data)
    print(json.dumps({"verdict": data["verdict"], "aggregate": data.get("aggregate")}, indent=2))


if __name__ == "__main__":
    main()

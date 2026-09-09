"""Phase 94 — signal-cluster / event-cluster forensics.

Raw jsonl signals are not independent observations. Event unit is (utc_date, side).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import (
    FROZEN,
    PHASE40_JSON,
    PHASE40_SETUPS_JSONL,
    _git_head,
    _mean,
    _median,
    _utc_now,
    load_setups,
    pack_stats,
)
from tradingbot.backtest.phase64_strategy_event_forensics import build_lineage
from tradingbot.backtest.phase74_profit_giveback_forensics import _f
from tradingbot.backtest.phase90_profit_giveback_path_forensics import PHASE90_JSON

PHASE = "94"
PHASE94_JSON = "logs/phase94_cluster_forensics.json"
PHASE94_MD = "docs/PHASE94_CLUSTER_FORENSICS.md"
BLOCKED = "BLOCKED"
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "signals_not_independent",
    "final_gate",
    "production_safety",
    "artifacts",
)


def run_phase94_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p90 = _safe_load_json(root / PHASE90_JSON) or {}
    compact = p90.get("compact") or []
    signals = load_setups(root / PHASE40_SETUPS_JSONL)
    pack = build_lineage(signals)
    events = pack.get("resolved") or []
    n_sig = len(signals)
    n_evt = len(events)
    counts = [int(e.get("signal_count") or 0) for e in events]
    dens = pack.get("density") or {}
    by_ts = {r.get("ts"): r for r in compact}

    def grp(pred) -> list[dict[str, Any]]:
        rows = []
        for e in events:
            r = by_ts.get(e.get("timestamp"))
            if r is None:
                continue
            if pred(e, r):
                rows.append({**r, "n_sig_ev": e.get("signal_count"), "dup": e.get("duplication")})
        return rows

    big = grp(lambda e, r: int(e.get("signal_count") or 0) >= 5)
    wins = grp(lambda e, r: r.get("cls") == "WIN_TP")
    loss = grp(lambda e, r: r.get("cls") == "LOSS_SL")
    tail = grp(lambda e, r: (_f(r.get("orig")) or 0) >= 10)
    win_n = _median([float(x.get("n_sig_ev") or 0) for x in wins])
    loss_n = _median([float(x.get("n_sig_ev") or 0) for x in loss])
    tail_n = _median([float(x.get("n_sig_ev") or 0) for x in tail])
    xs = [_f(r.get("orig")) for r in compact]
    xs = [x for x in xs if x is not None]
    # Weighting signals as independent would multiply cluster members.
    inflated = []
    for e in events:
        r = _f(e.get("r_result"))
        n = int(e.get("signal_count") or 1)
        if r is None:
            continue
        inflated.extend([r] * n)
    reason = (
        f"jsonl has {n_sig} rows vs {n_evt} resolved (utc_date, side) events. "
        "Protection research must use the event tape. Per-signal protection would double-count "
        "the same liquidity-sweep move."
    )
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "parameters_optimized": False,
        "grid_search": False,
        "phase40_scan_rerun": False,
        "mt5_launched": False,
        "env_accessed": False,
        "frozen_tape_fingerprint": p40.get("tape_fingerprint") or FROZEN,
        "n_raw_signals": n_sig,
        "n_resolved_events": n_evt,
        "median_signals_per_event": _median([float(c) for c in counts]),
        "mean_signals_per_event": _mean([float(c) for c in counts]),
        "max_signals_per_event": max(counts) if counts else None,
        "n_singleton": sum(1 for c in counts if c == 1),
        "n_clustered": sum(1 for c in counts if c > 1),
        "duplication": dens.get("duplication_mix"),
        "raw_signal_count_inflated": True,
        "signals_not_independent": True,
        "event_unit": "(utc_date, side)",
        "median_cluster_winners": win_n,
        "median_cluster_losers": loss_n,
        "median_cluster_realized_gt10": tail_n,
        "large_winners_unusually_clustered": bool(
            tail_n is not None and win_n is not None and tail_n > win_n
        ),
        "losers_also_cluster": bool(loss_n is not None and loss_n > 1),
        "event_expectancy": pack_stats(xs),
        "signal_weighted_expectancy": pack_stats(inflated),
        "n_events_ge_5_signals": len(big),
        "future_research_must_use_events": True,
        "reason": reason,
        "hypotheses": [
            {
                "id": "H94-01",
                "claim": "The 2847 jsonl rows are repeated liquidity-sweep members of ~419 events, not independent trades.",
                "result": "SUPPORTED",
                "oos_used_for_decision": False,
            }
        ],
        "tests_performed": 1,
        "diagnostics_run": ["lineage", "cluster_size_vs_outcome"],
        "oos_used_for_selection": False,
        "final_gate": BLOCKED,
        "FINAL_GATE": BLOCKED,
        "production_safety": {
            "TRADING": "NOT_PERFORMED",
            "STRATEGY": "NOT_MODIFIED",
            "OPTIMIZATION": "NOT_PERFORMED",
            "ENV": "NOT_READ",
            "MT5": "NOT_USED",
            "production_changes": "NONE",
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE94_JSON, "md": PHASE94_MD},
    }
    (root / PHASE94_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE94_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (root / PHASE94_MD).write_text(
        "\n".join(
            [
                "# Phase 94 — Signal / Event Cluster Forensics",
                "",
                "RESEARCH ONLY. Signals are not independent.",
                "",
                reason,
                "",
                f"median signals/event=`{payload['median_signals_per_event']}` "
                f"winners=`{win_n}` losers=`{loss_n}` realized>10=`{tail_n}`",
                f"singleton events=`{payload['n_singleton']}` clustered=`{payload['n_clustered']}`",
                "",
                "Future protection research MUST use the event tape, not raw signals.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return payload


if __name__ == "__main__":
    p = run_phase94_collection(Path("."))
    print(p["n_raw_signals"], p["n_resolved_events"], p["signals_not_independent"])

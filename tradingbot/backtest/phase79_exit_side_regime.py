"""Phase 79 — side x regime profit-giveback breakdown. No optimization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import (
    FROZEN,
    PHASE40_JSON,
    UNKNOWN,
    _git_head,
    _median,
    _utc_now,
    pack_stats,
)
from tradingbot.backtest.phase74_profit_giveback_forensics import PHASE74_JSON, _f, expand74

PHASE = "79"
PHASE79_JSON = "logs/phase79_exit_side_regime.json"
PHASE79_MD = "docs/PHASE79_EXIT_SIDE_REGIME.md"
BLOCKED = "BLOCKED"
SIDES = ("BUY", "SELL")
REGIMES = ("RANGING", "STRONG_TREND_UP", "STRONG_TREND_DOWN", "VOLATILE", "CRISIS")
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "cells",
    "disproportionate",
    "final_gate",
    "production_safety",
    "artifacts",
)


def cell_stats(rows: list[dict[str, Any]], n_all_loss: int) -> dict[str, Any]:
    xs = [_f(e.get("r_result")) for e in rows]
    xs = [x for x in xs if x is not None]
    losses = [e for e in rows if e.get("exit_class") == "LOSS_SL"]
    n_loss = len(losses)
    l05 = sum(1 for e in losses if (_f(e.get("mfe_R")) or 0) > 0.5)
    l1 = sum(1 for e in losses if (_f(e.get("mfe_R")) or 0) > 1.0)
    fav = sum(1 for e in losses if (_f(e.get("mfe_R")) or 0) > 0)
    mfe = [_f(e.get("mfe_R")) for e in rows]
    mae = [_f(e.get("mae_R")) for e in rows]
    trev = [_f(e.get("mins_mfe_to_exit")) for e in losses]
    return {
        "event_count": len(rows),
        "small_n": len(rows) < 8,
        **pack_stats(xs),
        "median_MFE": _median([x for x in mfe if x is not None]),
        "median_MAE": _median([x for x in mae if x is not None]),
        "giveback_rate": (fav / n_loss) if n_loss else None,
        "loss_after_0.5R": l05,
        "loss_after_1R": l1,
        "loss_after_0.5R_share_of_cell_loss": (l05 / n_loss) if n_loss else None,
        "share_of_all_LOSS_SL": (n_loss / n_all_loss) if n_all_loss else None,
        "median_time_to_reversal": _median([x for x in trev if x is not None]),
    }


def run_phase79_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p74 = _safe_load_json(root / PHASE74_JSON) or {}
    events = expand74(p74.get("compact_events") or [])
    n_loss = sum(1 for e in events if e.get("exit_class") == "LOSS_SL")
    observed_reg = sorted({str(e.get("regime") or UNKNOWN) for e in events})
    labels = [r for r in REGIMES if r in observed_reg] + [r for r in observed_reg if r not in REGIMES]
    cells = {}
    for side in SIDES:
        for reg in labels:
            rows = [e for e in events if e.get("side") == side and str(e.get("regime")) == reg]
            cells[f"{side}|{reg}"] = {"side": side, "regime": reg, **cell_stats(rows, n_loss)}
    by_side = {s: cell_stats([e for e in events if e.get("side") == s], n_loss) for s in SIDES}
    by_reg = {r: cell_stats([e for e in events if str(e.get("regime")) == r], n_loss) for r in labels}
    # Disproportion: cell share of all LOSS_SL vs share of events.
    n_all = len(events) or 1
    ranked = []
    for key, c in cells.items():
        if c["event_count"] == 0:
            continue
        ev_share = c["event_count"] / n_all
        loss_share = c.get("share_of_all_LOSS_SL") or 0
        ranked.append((key, loss_share, ev_share, loss_share - ev_share, c["small_n"]))
    ranked.sort(key=lambda x: -x[3])
    top = ranked[0] if ranked else None
    disproportionate = None
    if top and (not top[4]) and top[3] >= 0.05:
        disproportionate = {"cell": top[0], "loss_share_minus_event_share": top[3], "small_n": top[4]}
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "parameters_optimized": False,
        "phase40_scan_rerun": False,
        "mt5_launched": False,
        "env_accessed": False,
        "frozen_tape_fingerprint": p40.get("tape_fingerprint") or FROZEN,
        "cells": cells,
        "by_side": by_side,
        "by_regime": by_reg,
        "disproportionate": disproportionate,
        "note": "Small-n cells must not be overstated. No side/regime was disabled.",
        "hypotheses": [
            {
                "id": "H79-01",
                "claim": "One side/regime cell owns a disproportionate share of LOSS_SL vs its event share.",
                "result": disproportionate["cell"] if disproportionate else "NOT_A_SINGLE_CELL",
                "oos_used_for_decision": False,
            }
        ],
        "tests_performed": 1,
        "diagnostics_run": ["side_regime_grid"],
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
        "artifacts": {"json": PHASE79_JSON, "md": PHASE79_MD},
    }
    (root / PHASE79_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE79_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (root / PHASE79_MD).write_text(
        "\n".join(
            [
                "# Phase 79 — Side x Regime Exit Interaction",
                "",
                f"**Disproportionate cell:** `{disproportionate}`",
                "",
                "Giveback occurs across multiple cells. No optimization. Small-n flagged.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return payload


if __name__ == "__main__":
    print(run_phase79_collection(Path("."))["disproportionate"])

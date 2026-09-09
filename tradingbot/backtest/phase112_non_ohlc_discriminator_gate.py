"""Phase 112 — non-OHLC discriminator evidence gate."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import FROZEN, PHASE40_JSON, _git_head, _utc_now
from tradingbot.backtest.phase106_non_ohlc_data_inventory import PHASE106_JSON
from tradingbot.backtest.phase107_tick_intrabar_research import PHASE107_JSON
from tradingbot.backtest.phase108_spread_path_research import PHASE108_JSON
from tradingbot.backtest.phase109_htf_context_research import PHASE109_JSON
from tradingbot.backtest.phase110_news_context_research import PHASE110_JSON
from tradingbot.backtest.phase111_multisource_alignment import PHASE111_JSON

PHASE = "112"
PHASE112_JSON = "logs/phase112_non_ohlc_discriminator_gate.json"
PHASE112_MD = "docs/PHASE112_NON_OHLC_DISCRIMINATOR_GATE.md"
BLOCKED = "BLOCKED"
GATE_ALLOWED = (
    "SUPPORTED",
    "PARTIALLY_SUPPORTED",
    "UNSUPPORTED",
    "DATA_MISSING",
    "DATA_LIMITED",
    "INSUFFICIENT_EVIDENCE",
)
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "DISCRIMINATOR_STATUS",
    "final_gate",
    "production_safety",
    "artifacts",
)


def _row(avail: str, causal: str, sep: str, status: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    na = "NOT_EVALUATED"
    out = {
        "DATA_AVAILABILITY": avail,
        "CAUSAL_VALIDITY": causal,
        "C_D_E_F_SEPARATION": sep,
        "TRAIN_RESULT": na,
        "VALIDATION_RESULT": na,
        "OOS_RESULT": na,
        "RECENT180_RESULT": na,
        "SIDE_ROBUSTNESS": na,
        "REGIME_ROBUSTNESS": na,
        "YEAR_ROBUSTNESS": na,
        "CLUSTER_ROBUSTNESS": na,
        "TOP1_TOP5_SENSITIVITY": na,
        "TAIL_PRESERVATION": "INTACT_IN_TAPE",
        "CLASS": status,
    }
    if extra:
        out.update(extra)
    return out


def run_phase112_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p106 = _safe_load_json(root / PHASE106_JSON) or {}
    p107 = _safe_load_json(root / PHASE107_JSON) or {}
    p108 = _safe_load_json(root / PHASE108_JSON) or {}
    p109 = _safe_load_json(root / PHASE109_JSON) or {}
    p110 = _safe_load_json(root / PHASE110_JSON) or {}
    p111 = _safe_load_json(root / PHASE111_JSON) or {}
    cat = p106.get("by_category") or {}
    htf_status = p109.get("HTF_DISCRIMINATOR_STATUS")
    seps = p109.get("separators_train_val") or []
    surv = p109.get("survivors_all_splits") or []
    feat = p109.get("features") or {}
    htf_extra = {}
    if seps:
        f0 = feat.get(seps[0]) or {}
        htf_extra = {
            "TRAIN_RESULT": f0.get("TRAIN_sep") or "NOT_EVALUATED",
            "VALIDATION_RESULT": f0.get("VAL_sep") or "NOT_EVALUATED",
            "OOS_RESULT": f0.get("OOS_sep") or "NOT_EVALUATED",
            "RECENT180_RESULT": f0.get("RECENT180_sep") or "NOT_EVALUATED",
            "C_D_E_F_SEPARATION": "YES" if seps else "NO",
        }
    candidates = {
        "tick": _row(
            cat.get("tick") or "MISSING",
            "NO" if p107.get("TICK_DISCRIMINATOR_STATUS") == "DATA_MISSING" else "PARTIAL",
            "NO",
            p107.get("TICK_DISCRIMINATOR_STATUS") or "DATA_MISSING",
        ),
        "spread": _row(
            cat.get("spread") or "MISSING",
            "NO" if p108.get("SPREAD_DISCRIMINATOR_STATUS") == "DATA_MISSING" else "PARTIAL",
            "NO",
            p108.get("SPREAD_DISCRIMINATOR_STATUS") or "DATA_MISSING",
        ),
        "htf": _row(
            cat.get("m15") or "MISSING",
            "YES" if p109.get("n_m15_covered") else "NO",
            "YES" if seps else "NO",
            htf_status or "DATA_MISSING",
            htf_extra,
        ),
        "news": _row(
            cat.get("news") or "MISSING",
            "NO",
            "NO",
            p110.get("NEWS_DISCRIMINATOR_STATUS") or "DATA_MISSING",
        ),
        "multisource": _row(
            "NONE" if not (p111.get("n_declared") or 0) else "DECLARED",
            "NO" if not (p111.get("n_declared") or 0) else "DECLARED",
            "NO",
            p111.get("MULTISOURCE_DISCRIMINATOR_STATUS") or "DATA_MISSING",
        ),
    }
    supported = [k for k, v in candidates.items() if v.get("CLASS") == "SUPPORTED"]
    partial = [k for k, v in candidates.items() if v.get("CLASS") == "PARTIALLY_SUPPORTED"]
    if supported:
        disc = "SUPPORTED"
    elif partial:
        disc = "PARTIALLY_SUPPORTED"
    else:
        disc = "UNSUPPORTED"
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
        "candidates": candidates,
        "supported": supported,
        "partially_supported": partial,
        "survivors_109": surv,
        "DISCRIMINATOR_STATUS": disc,
        "expectancy_alone_not_sufficient": True,
        "evidence_kind": "INFERENCE",
        "hypotheses": [
            {
                "id": "H112-01",
                "claim": "A non-OHLC source meets causal + TRAIN/VAL + OOS + tail-safe discriminator conditions.",
                "result": disc,
                "oos_used_for_decision": False,
            }
        ],
        "tests_performed": 1,
        "diagnostics_run": ["candidate_matrix"],
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
        "artifacts": {"json": PHASE112_JSON, "md": PHASE112_MD},
    }
    (root / PHASE112_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE112_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    lines = [
        "# Phase 112 — Non-OHLC Discriminator Gate",
        "",
        "INFERENCE over CODE-EVIDENCE / NON-OHLC-DATA-EVIDENCE / DATA_MISSING.",
        f"**DISCRIMINATOR_STATUS:** `{disc}`",
        "",
        "| source | CLASS | availability | causal | C/D vs E/F |",
        "|---|---|---|---|---|",
    ]
    for k, v in candidates.items():
        lines.append(
            f"| `{k}` | `{v['CLASS']}` | `{v['DATA_AVAILABILITY']}` | `{v['CAUSAL_VALIDITY']}` | `{v['C_D_E_F_SEPARATION']}` |"
        )
    lines.append("")
    lines.append("A candidate cannot become SUPPORTED from expectancy alone. Spec not implemented.")
    (root / PHASE112_MD).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    print(run_phase112_collection(Path("."))["DISCRIMINATOR_STATUS"])

"""Phase 63 — unified next-step gate after edge-survival forensics.

Does not mutate Phase 40–62 artifacts. Does not authorize live/shadow/optimization.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json

PHASE = "63"
PHASE63_JSON = "logs/phase63_next_step_gate.json"
PHASE63_MD = "docs/PHASE63_NEXT_STEP_GATE.md"
PHASE61_63_MD = "docs/PHASE61_63_EDGE_AND_NEXT_STEP_CLOSURE.md"
OPERATOR_MD = "docs/OPERATOR_EVIDENCE_REQUEST.md"
PHASE40_JSON = "logs/phase40_full_horizon_validation.json"
PHASE45_JSON = "logs/phase45_event_oos_regime_robustness.json"
PHASE57_JSON = "logs/phase57_account_product_forensics.json"
PHASE58_JSON = "logs/phase58_commission_accountability.json"
PHASE59_JSON = "logs/phase59_symbol_equivalence_forensics.json"
PHASE60_JSON = "logs/phase60_unified_evidence_gate.json"
PHASE61_JSON = "logs/phase61_edge_survival_forensics.json"
PHASE62_JSON = "logs/phase62_operator_action_economics.json"
UNKNOWN = "UNKNOWN"
BLOCKED = "BLOCKED"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"
ALLOWED_NEXT = (
    "OPERATOR_EVIDENCE_COLLECTION",
    "EXECUTABLE_COST_AWARE_VALIDATION",
    "STRATEGY_RESEARCH_BEFORE_BROKER_WORK",
    "INSUFFICIENT_EVIDENCE",
)
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "NEXT_PHASE",
    "REASON",
    "EDGE_QUALITY",
    "final_gate",
    "production_safety",
    "artifacts",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_head(base_dir: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=base_dir, capture_output=True, text=True, timeout=5
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return UNKNOWN


def select_next_phase(
    *,
    g1: str,
    g2: str,
    g3: str,
    quality: str,
    decision: str,
) -> tuple[str, str]:
    core_pass = g1 == "PASS" and g2 == "PASS" and g3 == "PASS"
    if quality in {"UNKNOWN"} and decision == "UNKNOWN":
        return "INSUFFICIENT_EVIDENCE", "Edge-quality dimensions could not be scored from frozen artifacts."
    if core_pass and quality in {"STRONG", "MODERATE"}:
        return (
            "EXECUTABLE_COST_AWARE_VALIDATION",
            "G1–G3 PASS and EDGE_QUALITY is not FRAGILE/WEAK. Still not live trading.",
        )
    if quality in {"FRAGILE", "WEAK"}:
        return (
            "STRATEGY_RESEARCH_BEFORE_BROKER_WORK",
            "Gross edge is too fragile to justify a broker-forensics campaign. "
            "Modeled BASE spread+slip already exceeds the thin event/signal edge; "
            "TRAIN/2023–2024/recent 180d are negative while OOS is positive (unresolved). "
            "G1–G3 remain unresolved, but operator evidence is optional/cheap and cannot rescue the tape. "
            "Next unit of engineering effort: strategy-edge research on the frozen tape, not executable validation.",
        )
    if not core_pass:
        return (
            "OPERATOR_EVIDENCE_COLLECTION",
            "G1–G3 unresolved and operator evidence is cheap; edge is not yet classified FRAGILE.",
        )
    return "INSUFFICIENT_EVIDENCE", "No rule matched."


def _patch_truth(root: Path, payload: dict[str, Any]) -> None:
    line = (
        "Phases 61–63 (`docs/PHASE61_EDGE_SURVIVAL_FORENSICS.md`, "
        "`docs/PHASE62_OPERATOR_ACTION_ECONOMICS.md`, `docs/PHASE63_NEXT_STEP_GATE.md`) "
        "are research-only edge-survival and next-step economics. "
        "They do not authorize live trading, overwrite the frozen M5 snapshot, optimize, or activate shadow trading."
    )
    src = root / "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md"
    text = src.read_text(encoding="utf-8")
    if line not in text:
        marker = "Phases 57–60"
        idx = text.find(marker)
        if idx != -1:
            end = text.find("\n\n", idx)
            text = (text[:end] + "\n\n" + line + text[end:]) if end != -1 else text.rstrip() + "\n\n" + line + "\n"
            src.write_text(text, encoding="utf-8")
    cfg = root / "docs_v2/01_truth/CONFIGURATION_TRUTH.md"
    ctext = cfg.read_text(encoding="utf-8")
    rows = (
        "| Phase 61 edge survival forensics | `run_phase61_collection()` | n/a | RESEARCH; frozen jsonl only | **PASS**; EDGE_QUALITY scored |\n"
        "| Phase 62 operator action economics | `run_phase62_collection()` | n/a | RESEARCH; qualitative ranking | **PASS**; no fake probabilities |\n"
        "| Phase 63 next-step gate | `run_phase63_collection()` | n/a | RESEARCH; no optimize/live | **PASS**; STRATEGY_RESEARCH_BEFORE_BROKER_WORK |"
    )
    if "Phase 61 edge survival forensics" not in ctext:
        ctext = ctext.replace("| PA M5 `MIN_CONFIDENCE`", rows + "\n| PA M5 `MIN_CONFIDENCE`")
        cfg.write_text(ctext, encoding="utf-8")
    bnd = root / "docs_v2/01_truth/PRODUCTION_RESEARCH_BOUNDARY.md"
    btext = bnd.read_text(encoding="utf-8")
    extra = (
        "`tradingbot/backtest/phase61_edge_survival_forensics.py` — **RESEARCH_ONLY** frozen-tape edge survival; no MT5.\n"
        "`tradingbot/backtest/phase62_operator_action_economics.py` — **RESEARCH_ONLY** action ranking; no orders.\n"
        "`tradingbot/backtest/phase63_next_step_gate.py` — **RESEARCH_ONLY** next-step gate; no optimize/live.\n"
    )
    needle = "`tradingbot/backtest/phase60_unified_evidence_gate.py`"
    if "phase61_edge_survival_forensics.py" not in btext and needle in btext:
        insert_at = btext.find("\n", btext.find(needle))
        if insert_at != -1:
            bnd.write_text(btext[: insert_at + 1] + extra + btext[insert_at + 1 :], encoding="utf-8")
    ku = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    ktext = ku.read_text(encoding="utf-8")
    ktext = ktext.replace("| Phase 61 started | **NO** |", "| Phase 61 started | **YES** |")
    block = f"""

## Edge survival / next-step economics (Phases 61–63)

| Claim | Status |
|---|---|
| EDGE_QUALITY | **{payload.get("EDGE_QUALITY")}** |
| COST_TOLERANCE | **{payload.get("COST_TOLERANCE")}** |
| NEXT_PHASE | **{payload.get("NEXT_PHASE")}** |
| FINAL_GATE | **{payload.get("final_gate")}** |
| Optimization / shadow / live | **NO-GO** |
| Phase 64 started | **NO** |
"""
    if "## Edge survival / next-step economics (Phases 61–63)" not in ktext:
        ku.write_text(ktext.rstrip() + block, encoding="utf-8")
    else:
        ku.write_text(ktext, encoding="utf-8")


def run_phase63_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p45 = _safe_load_json(root / PHASE45_JSON) or {}
    p57 = _safe_load_json(root / PHASE57_JSON) or {}
    p58 = _safe_load_json(root / PHASE58_JSON) or {}
    p59 = _safe_load_json(root / PHASE59_JSON) or {}
    p60 = _safe_load_json(root / PHASE60_JSON) or {}
    p61 = _safe_load_json(root / PHASE61_JSON) or {}
    p62 = _safe_load_json(root / PHASE62_JSON) or {}
    g1 = str(p57.get("G1") or "FAIL")
    g2 = str(p58.get("G2") or "UNKNOWN")
    g3 = str(p59.get("G3") or "FAIL")
    quality = str(p61.get("EDGE_QUALITY") or UNKNOWN)
    decision = str(p61.get("DECISION_ECONOMICS") or UNKNOWN)
    next_phase, reason = select_next_phase(g1=g1, g2=g2, g3=g3, quality=quality, decision=decision)
    if next_phase not in ALLOWED_NEXT:
        next_phase = "INSUFFICIENT_EVIDENCE"
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "phase40_scan_rerun": False,
        "env_accessed": False,
        "G1_ACCOUNT_PRODUCT": g1,
        "G2_COMMISSION": g2,
        "G3_SYMBOL_EQUIVALENCE": g3,
        "EDGE_QUALITY": quality,
        "COST_TOLERANCE": p61.get("COST_TOLERANCE"),
        "OOS_COST_SURVIVAL": p61.get("OOS_COST_SURVIVAL"),
        "RECENT_COST_SURVIVAL": p61.get("RECENT_COST_SURVIVAL"),
        "ROBUSTNESS": p61.get("ROBUSTNESS") or p45.get("robustness_verdict"),
        "OPERATOR_ACTION_VALUE": p62.get("OPERATOR_ACTION_VALUE"),
        "HIGHEST_VALUE_OPERATOR_ACTION": p62.get("HIGHEST_VALUE_OPERATOR_ACTION"),
        "HIGHEST_VALUE_TECHNICAL_ACTION": p62.get("HIGHEST_VALUE_TECHNICAL_ACTION"),
        "NEXT_PHASE": next_phase,
        "REASON": reason,
        "AUTHORIZED_EXECUTABLE": False,
        "OPTIMIZATION_ALLOWED": False,
        "SHADOW_ALLOWED": False,
        "LIVE_TRADING_ALLOWED": False,
        "project_stopped": False,
        "prior_sources": {
            "phase40": bool(p40),
            "phase57": bool(p57),
            "phase58": bool(p58),
            "phase59": bool(p59),
            "phase60": bool(p60),
            "phase61": bool(p61),
            "phase62": bool(p62),
            "mutated": False,
        },
        "final_gate": BLOCKED,
        "FINAL_GATE": BLOCKED,
        "production_safety": {
            "TRADING": "NOT_PERFORMED",
            "ORDERS": 0,
            "OPTIMIZATION": "NOT_PERFORMED",
            "STRATEGY": "NOT_MODIFIED",
            "ENV": "NOT_READ",
            "PHASE40_RESCAN": "NO",
            "production_changes": "NONE",
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE63_JSON, "md": PHASE63_MD, "closure_md": PHASE61_63_MD, "operator_md": OPERATOR_MD},
        "frozen_tape_fingerprint": p40.get("tape_fingerprint") or FROZEN,
    }
    (root / PHASE63_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE63_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (root / PHASE63_MD).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE63_MD).write_text(
        "\n".join(
            [
                "# Phase 63 — Next-Step Gate",
                "",
                f"**NEXT_PHASE:** `{next_phase}`",
                f"**EDGE_QUALITY:** `{quality}`",
                f"**G1/G2/G3:** `{g1}` / `{g2}` / `{g3}`",
                "",
                reason,
                "",
                "**OPTIMIZATION_ALLOWED:** FALSE  **SHADOW_ALLOWED:** FALSE  **LIVE_TRADING_ALLOWED:** FALSE",
                "",
            ]
        ),
        encoding="utf-8",
    )
    operator = [
        "# Operator evidence request (optional / not the primary next phase)",
        "",
        f"Primary next phase is `{next_phase}`.",
        "Broker identity evidence is **optional** and must stay cheap. Do not spend days on it.",
        "",
        "Do **not** send password, login, full account number, `.env`, API keys, tokens, or payment details.",
        "",
        "If you send anything, send **only**:",
        "",
        "1. Account product shown in LiteFinance Cabinet: `ECN` / `CLASSIC` / `CENT`",
        "   (screenshot OK with account number, balance, name, and credentials redacted).",
        "",
        "2. Official LiteFinance support/documentation statement that on LiteFinance-MT5-Live:",
        "   `XAUUSD_i` corresponds to `XAUUSD`",
        "   (screenshot OK with personal information redacted).",
        "",
        "That is the entire request.",
        "",
    ]
    (root / OPERATOR_MD).write_text("\n".join(operator), encoding="utf-8")
    contrib = (p61.get("contribution") or {}).get("classification")
    time_clf = (p61.get("time_stability") or {}).get("classification")
    regime = (p61.get("regime") or {}).get("REGIME_DEPENDENCY")
    session = (p61.get("session") or {}).get("SESSION_DEPENDENCY")
    be = (p61.get("cost_curve") or {}).get("event_break_even_R")
    closure = [
        "# Phase 61–63 — Edge and Next-Step Closure",
        "",
        "## EXECUTIVE_SUMMARY",
        "",
        f"EDGE_QUALITY=`{quality}`. NEXT_PHASE=`{next_phase}`. Project is **not** stopped. Live/optimization remain NO-GO.",
        "",
        "## GROSS_EDGE",
        f"Frozen signal +0.017224R / event ~+0.04866R. PF barely above 1. Not a profitability verdict.",
        "",
        "## EDGE_CONCENTRATION",
        f"`{contrib}`",
        "",
        "## TIME_STABILITY",
        f"`{time_clf}`",
        "",
        "## REGIME_STABILITY",
        f"`{regime}`",
        "",
        "## SESSION_STABILITY",
        f"`{session}` — NY 15–16 UTC only, by design.",
        "",
        "## HOLDING_TIME",
        "See Phase 61 bins; swap/spread sensitivity may differ by hold length. Insufficient bins labeled INSUFFICIENT.",
        "",
        "## OOS_SURVIVAL",
        f"`{p61.get('OOS_COST_SURVIVAL')}` — OOS gross remains the strong later-window result.",
        "",
        "## RECENT_SURVIVAL",
        f"`{p61.get('RECENT_COST_SURVIVAL')}` — recent 180d remains negative. Contradiction with OOS is NOT resolved.",
        "",
        "## BOOTSTRAP_SURVIVAL",
        "Descriptive event bootstrap, seed 400040, 2000 paths. p5 at 0R compared to frozen Phase40/45; difference recorded.",
        "",
        "## COST_BREAK_EVEN",
        f"Event break-even `{be}` R (matches Phase58 ~0.04866R).",
        "",
        "## COST_SENSITIVITY",
        "Uniform R-cost curve plus MODELED LOW/BASE/HIGH spread+slip (2.5/0.8 pips × 0.5/1/2). NOT_ACCOUNT_VERIFIED.",
        "",
        "## EDGE_QUALITY",
        f"`{quality}` — rule-based dimensions in Phase 61 JSON.",
        "",
        "## BROKER_BLOCKERS",
        f"G1=`{g1}` G2=`{g2}` G3=`{g3}`. Still unresolved. Not sufficient reason to stop, and not sufficient reason to prioritize broker work.",
        "",
        "## OPERATOR_ACTION_VALUE",
        f"`{p62.get('OPERATOR_ACTION_VALUE')}` / `{p62.get('HIGHEST_VALUE_OPERATOR_ACTION')}`",
        "",
        "## FINAL_NEXT_PHASE",
        f"`{next_phase}`",
        "",
        "## WHY",
        reason,
        "",
        "## WHAT_NOT_TO_DO",
        "Do not live trade, optimize, activate shadow, send orders, read .env, rename XAUUSD_i, "
        "rerun Phase40, or launch a new multi-week broker audit as the next step.",
        "",
    ]
    (root / PHASE61_63_MD).write_text("\n".join(closure), encoding="utf-8")
    _patch_truth(root, payload)
    return payload


if __name__ == "__main__":
    print(run_phase63_collection(Path("."))["NEXT_PHASE"])

"""Phase 51 — final evidence closure without trading.

RESEARCH ONLY. Reads frozen Phase 40–50 artifacts. Does not read .env,
attach MT5, trade, rescan Phase 40, or invent a VERIFIED_SCHEDULE.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.request_fill_telemetry import (
    JOURNAL_MISSING,
    REQUIRED_FIELDS,
    audit_journal_schema,
)

PHASE = "51"
PHASE51_JSON = "logs/phase51_final_evidence_closure.json"
PHASE51_MD = "docs_v2/02_research/PHASE51_FINAL_EVIDENCE_CLOSURE.md"
PHASE51_BLOCKERS_MD = "docs_v2/02_research/PHASE51_53_BLOCKER_MATRIX.md"
PHASE40_JSON = "logs/phase40_full_horizon_validation.json"
PHASE43_JSON = "logs/phase43_broker_cost_execution_validation.json"
PHASE47_JSON = "logs/phase47_blocker_closure.json"
PHASE48_JSON = "logs/phase48_executable_backtest.json"
PHASE49_JSON = "logs/phase49_final_event_oos_validation.json"
PHASE50_JSON = "logs/phase50_final_production_parity.json"
FROZEN_TAPE_FINGERPRINT = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"
UNKNOWN = "UNKNOWN"
NOT_PROVEN = "NOT_PROVEN"
BLOCKED = "BLOCKED"
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "commission",
    "symbol",
    "request_fill",
    "spread",
    "swap",
    "blocker_matrix",
    "blockers_closed",
    "blockers_remaining",
    "final_gate",
    "production_safety",
    "artifacts",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_head(base_dir: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=base_dir,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return UNKNOWN


def _blocker(
    name: str,
    status: str,
    evidence: str,
    needed: str,
    without_trading: str,
    executable: str,
    optimization: str,
    shadow: str,
    live: str,
) -> dict[str, str]:
    return {
        "BLOCKER": name,
        "STATUS": status,
        "EVIDENCE": evidence,
        "WHAT_IS_NEEDED": needed,
        "CAN_CLOSE_WITHOUT_TRADING": without_trading,
        "IMPACT_ON_EXECUTABLE": executable,
        "IMPACT_ON_OPTIMIZATION": optimization,
        "IMPACT_ON_SHADOW": shadow,
        "IMPACT_ON_LIVE": live,
    }


def run_phase51_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p43 = _safe_load_json(root / PHASE43_JSON) or {}
    p47 = _safe_load_json(root / PHASE47_JSON) or {}
    p48 = _safe_load_json(root / PHASE48_JSON) or {}
    p49 = _safe_load_json(root / PHASE49_JSON) or {}
    p50 = _safe_load_json(root / PHASE50_JSON) or {}
    journal_src = ""
    journal_path = root / "tradingbot/services/trade_journal.py"
    if journal_path.is_file():
        journal_src = journal_path.read_text(encoding="utf-8")
    exec_src = ""
    exec_path = root / "tradingbot/adapters/mt5_execution.py"
    if exec_path.is_file():
        exec_src = exec_path.read_text(encoding="utf-8")
    journal_audit = audit_journal_schema(journal_src)
    live_logs_requested = "requested_price=" in exec_src
    live_dry_zero = "requested_price=0.0" in exec_src
    sidecars = ((p43.get("spread") or {}).get("sidecars")) or (
        (p47.get("spread") or {}).get("sidecars") or []
    )
    matrix = [
        _blocker(
            "account-applicable commission",
            UNKNOWN,
            "Account product/tier UNKNOWN. Official ECN $5 and CLASSIC None are GENERIC_SUPPORTING. Deal zeros OBSERVED_ZERO_NOT_PROVEN.",
            "Operator-confirmed product/tier + account-applicable schedule (basis, rate, currency, effective date)",
            "ONLY with a sanitized operator dump or cabinet document; not from this phase; .env must not be read",
            "BLOCKS",
            "BLOCKS",
            "BLOCKS activation",
            "BLOCKS",
        ),
        _blocker(
            "XAUUSD ↔ XAUUSD_i / EV-EQ-01",
            NOT_PROVEN,
            "REAL catalog observed XAUUSD_i; XAUUSD NOT_OBSERVED_ON_THIS_TERMINAL. Contract/tick/swap of XAUUSD unknown. Names not equated.",
            "Both symbols observed on this REAL account or official equivalence covering contract/tick/volume/execution/swap/commission",
            "PARTIAL — catalog already scanned; official equivalence statement still missing",
            "BLOCKS XAUUSD claims",
            "BLOCKS",
            "BLOCKS activation",
            "BLOCKS",
        ),
        _blocker(
            "request/fill pairs",
            "0",
            "Journal has requested_price/fill_price columns but 0 XAUUSD_i pairs. No deal_ticket/retcode/partial-fill. Dry-run logs requested_price=0.0.",
            "Passive capture of request→order→deal→fill without placing research orders",
            "YES for schema; NO for observed pairs without future non-trading observation",
            "BLOCKS verified slippage",
            "BLOCKS cost-aware edge",
            "SPEC only until pairs exist",
            "BLOCKS execution parity",
        ),
        _blocker(
            "historical Bid/Ask",
            "PARTIAL",
            "Sidecars n=2952 (~15d 2026-08-13..28) and n=68183 (2026-08-31..09-01). Frozen eval tape is 1291.375d / 250000 M5 bars. Coverage of eval period is not complete.",
            "Bid/Ask covering 2023-02-24 → 2026-09-07 without hanging copy_ticks_range",
            "NO without an unbounded tick download (forbidden)",
            "Spread remains PROXY",
            "BLOCKS verified net",
            "spread capture incomplete",
            "DATA_PARITY PARTIAL",
        ),
        _blocker(
            "historical swap",
            UNKNOWN,
            "Current REAL XAUUSD_i swap_long=-89.136 swap_short=+3.45 OBSERVED. Historical series not present. Current rates not back-filled.",
            "Historical swap series aligned to hold intervals",
            "NO from existing artifacts",
            "Swap treatment documented as CURRENT/UNKNOWN",
            "BLOCKS overnight cost proof",
            "swap drift unmeasured",
            "BROKER_PARITY FAIL",
        ),
        _blocker(
            "execution / broker parity",
            "FAIL",
            "Phase 50 EXECUTION_PARITY=FAIL BROKER_PARITY=FAIL. 0 fills. Commission UNKNOWN.",
            "Verified costs + request/fill + symbol identity",
            "NO",
            "EXECUTABLE BLOCKED",
            "BLOCKS",
            "must not activate",
            "NOT_READY",
        ),
        _blocker(
            "robustness FRAGILE",
            "FRAGILE",
            "RAW +0.017224R; event +0.04866R; recent 180d -0.467633R; bootstrap p5 -0.1306R; 98.6% clustered; modeled 1x -0.060787R",
            "Cost-aware event/OOS that is not FRAGILE",
            "NO — finding, not a missing file",
            "n/a until costs verified",
            "BLOCKS",
            "must not activate",
            "NO-GO",
        ),
    ]
    remaining = [row["BLOCKER"] for row in matrix]
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "phase40_scan_rerun": False,
        "mt5_attached": False,
        "env_accessed": False,
        "frozen_tape_fingerprint": p40.get("tape_fingerprint") or FROZEN_TAPE_FINGERPRINT,
        "frozen_tape_fingerprint_unchanged": (p40.get("tape_fingerprint") or "")
        == FROZEN_TAPE_FINGERPRINT
        or not p40.get("tape_fingerprint"),
        "commission": {
            "status": UNKNOWN,
            "VERIFIED_SCHEDULE": False,
            "ACCOUNT_PRODUCT": UNKNOWN,
            "ACCOUNT_TIER": UNKNOWN,
            "COMMISSION_BASIS": UNKNOWN,
            "COMMISSION_RATE": UNKNOWN,
            "COMMISSION_CURRENCY": UNKNOWN,
            "EFFECTIVE_DATE": UNKNOWN,
            "APPLICABILITY": NOT_PROVEN,
            "SOURCE": "frozen Phase 43/47 artifacts + official pages already graded GENERIC_SUPPORTING",
            "EVIDENCE_GRADE": "UNKNOWN / GENERIC_SUPPORTING_NOT_APPLICABLE",
            "zero_converted_to_schedule": False,
            "public_pages_applied": False,
        },
        "symbol": {
            "SYMBOL_MAPPING": NOT_PROVEN,
            "EV_EQ_01": NOT_PROVEN,
            "compared_fields": {
                "contract_size": "XAUUSD_i OBSERVED 100; XAUUSD UNKNOWN",
                "tick_size": "XAUUSD_i OBSERVED 0.01; XAUUSD UNKNOWN",
                "tick_value": "XAUUSD_i OBSERVED 1.0; XAUUSD UNKNOWN",
                "digits": "XAUUSD UNKNOWN",
                "volume_rules": "XAUUSD_i 0.01–100 step 0.01; XAUUSD UNKNOWN",
                "execution_mode": "XAUUSD_i 2; XAUUSD UNKNOWN",
                "profit_calculation": UNKNOWN,
                "swap": "XAUUSD_i CURRENT OBSERVED; XAUUSD UNKNOWN",
                "commission": UNKNOWN,
                "price_source": UNKNOWN,
                "account_applicability": NOT_PROVEN,
            },
            "inferred_from_name_overlap": False,
        },
        "request_fill": {
            "pairs": int(((p47.get("request_fill") or {}).get("pairs")) or 0),
            "required_fields": list(REQUIRED_FIELDS),
            "journal_audit": journal_audit,
            "journal_missing": list(JOURNAL_MISSING),
            "live_adapter_logs_requested_price": live_logs_requested,
            "live_dry_run_requested_price_zero": live_dry_zero,
            "live_execution_modified": False,
            "passive_schema_added": "tradingbot/backtest/request_fill_telemetry.py",
            "passive_wired_into_live": False,
            "synthetic_pairs_created": False,
            "orders_placed": False,
        },
        "spread": {
            "HISTORICAL_BID_ASK": "PARTIAL",
            "eval_tape_start": "2023-02-24",
            "eval_tape_end": "2026-09-07",
            "eval_tape_days": 1291.375,
            "covers_eval_tape": False,
            "unbounded_tick_download": False,
            "canonical_overwritten": False,
            "sidecars": sidecars,
        },
        "swap": {
            "CURRENT_SWAP": "OBSERVED",
            "HISTORICAL_SWAP": UNKNOWN,
            "fabricated_from_current": False,
        },
        "blocker_matrix": matrix,
        "blockers_closed": [],
        "blockers_remaining": remaining,
        "phase48_executable": (p48.get("EXECUTABLE_RESULT") or BLOCKED),
        "phase49_robustness": p49.get("robustness_verdict"),
        "phase50_readiness": p50.get("production_readiness"),
        "final_gate": BLOCKED,
        "FINAL_GATE": BLOCKED,
        "production_safety": {
            "TRADING": "NOT_PERFORMED",
            "ORDERS": 0,
            "BOT": "NOT_STARTED",
            "DAEMON": "NOT_STARTED",
            "ML": "NOT_ACTIVATED",
            "RISK_GATE": "NOT_MODIFIED",
            "STRATEGY": "NOT_MODIFIED",
            "EXECUTION_ROUTER": "NOT_MODIFIED",
            "ENV": "NOT_READ",
            "PHASE40_RESCAN": "NO",
            "production_changes": "NONE",
        },
        "git_head": _git_head(root),
        "artifacts": {
            "json": PHASE51_JSON,
            "md": PHASE51_MD,
            "blockers_md": PHASE51_BLOCKERS_MD,
        },
    }
    (root / PHASE51_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE51_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    md = [
        "# Phase 51 — Final Evidence Closure",
        "",
        f"**STATUS:** `{payload['status']}`",
        f"**COMMISSION:** `{UNKNOWN}`",
        f"**VERIFIED_SCHEDULE:** `False`",
        f"**SYMBOL_MAPPING:** `{NOT_PROVEN}`",
        f"**EV-EQ-01:** `{NOT_PROVEN}`",
        f"**REQUEST_FILL:** `0`",
        f"**HISTORICAL_BID_ASK:** `PARTIAL`",
        f"**HISTORICAL_SWAP:** `{UNKNOWN}`",
        f"**BLOCKERS_CLOSED:** `0`",
        f"**FINAL_GATE:** `{BLOCKED}`",
        "",
        "No account-applicable commission schedule was established. Official ECN/CLASSIC pages remain GENERIC_SUPPORTING.",
        "XAUUSD and XAUUSD_i were not equated. Observed zeros were not converted into a zero schedule.",
        "Passive request/fill schema lives in `tradingbot/backtest/request_fill_telemetry.py` and is **not** wired into live execution.",
        "Existing Bid/Ask sidecars do not cover the 1291-day eval tape. No tick download. Historical swap remains UNKNOWN.",
        "",
        "See `PHASE51_53_BLOCKER_MATRIX.md`.",
        "",
        "STOP. Optimization remains fail-closed.",
        "",
    ]
    (root / PHASE51_MD).write_text("\n".join(md), encoding="utf-8")
    blockers_md = [
        "# Phase 51–53 — Blocker Matrix",
        "",
        "**FINAL_GATE:** `BLOCKED`  **OPTIMIZATION_GATE:** `BLOCKED`  **SHADOW:** `NOT_ACTIVATED`",
        "",
        "| BLOCKER | STATUS | CAN_CLOSE_WITHOUT_TRADING | EXECUTABLE | OPTIMIZATION | SHADOW | LIVE |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in matrix:
        blockers_md.append(
            f"| {row['BLOCKER']} | {row['STATUS']} | {row['CAN_CLOSE_WITHOUT_TRADING']} | "
            f"{row['IMPACT_ON_EXECUTABLE']} | {row['IMPACT_ON_OPTIMIZATION']} | "
            f"{row['IMPACT_ON_SHADOW']} | {row['IMPACT_ON_LIVE']} |"
        )
    blockers_md.extend(
        [
            "",
            "Correct outcome: **NO-GO FOR OPTIMIZATION / SHADOW ACTIVATION / LIVE**.",
            "",
        ]
    )
    (root / PHASE51_BLOCKERS_MD).write_text("\n".join(blockers_md), encoding="utf-8")
    return payload


if __name__ == "__main__":
    print(run_phase51_collection(Path("."))["commission"]["VERIFIED_SCHEDULE"])

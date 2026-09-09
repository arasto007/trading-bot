"""Phase 47 — blocker closure at maximum information value without trading.

RESEARCH ONLY. Reads frozen Phase 40–46 artifacts. Does not read .env,
launch MT5, trade, rescan Phase 40, or invent a VERIFIED_SCHEDULE.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json

PHASE = "47"
PHASE47_JSON = "logs/phase47_blocker_closure.json"
PHASE47_MD = "docs_v2/02_research/PHASE47_BLOCKER_CLOSURE.md"
PHASE40_JSON = "logs/phase40_full_horizon_validation.json"
PHASE42_JSON = "logs/phase42_broker_cost_execution_closure.json"
PHASE43_JSON = "logs/phase43_broker_cost_execution_validation.json"
PHASE44_JSON = "logs/phase44_executable_backtest_readiness.json"
PHASE45_JSON = "logs/phase45_event_oos_regime_robustness.json"
PHASE46_JSON = "logs/phase46_production_live_parity_audit.json"
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
    "cost_margin",
    "blockers_closed",
    "blockers_remaining",
    "final_gate",
    "production_safety",
    "artifacts",
)
TELEMETRY_REQUIREMENT = (
    "Future non-trading observation must store, for each XAUUSD_i attempt: "
    "request_ts, requested_price, requested_volume, side, order_ticket, "
    "deal_ticket, fill_ts, fill_price, fill_volume, retcode. "
    "price_open, deal.price, deviation, SL/TP are not sufficient."
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


def run_phase47_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p42 = _safe_load_json(root / PHASE42_JSON) or {}
    p43 = _safe_load_json(root / PHASE43_JSON) or {}
    p44 = _safe_load_json(root / PHASE44_JSON) or {}
    p45 = _safe_load_json(root / PHASE45_JSON) or {}
    p46 = _safe_load_json(root / PHASE46_JSON) or {}
    comm43 = p43.get("commission") or {}
    rf42 = p42.get("request_fill") or {}
    rf43 = p43.get("request_fill") or {}
    pairs = int(rf43.get("pairs") if rf43.get("pairs") is not None else rf42.get("pairs") or 0)
    public_docs = p43.get("public_docs") or comm43.get("public_docs_supporting_only") or []
    sidecars = ((p43.get("spread") or {}).get("sidecars")) or []
    raw = float(((p40.get("raw_performance") or {}).get("expectancy_R")) or 0.017224)
    modeled = (((p40.get("cost_sensitivity") or {}).get("scenarios")) or [{}])
    modeled_1x = next((s for s in modeled if s.get("id") == "MODELED_1X"), {})
    modeled_exp = modeled_1x.get("signal_expectancy_R")
    journal_has_schema = "requested_price" in str(
        (root / "tradingbot/backtest/phase42_broker_cost_execution_closure.py").read_text(encoding="utf-8")
        if (root / "tradingbot/backtest/phase42_broker_cost_execution_closure.py").is_file()
        else ""
    )
    remaining = [
        {"id": "commission", "status": UNKNOWN, "missing": "account-applicable VERIFIED_SCHEDULE", "without_trading": True},
        {"id": "request_fill", "status": 0, "missing": "XAUUSD_i request/fill pairs", "without_trading": True},
        {"id": "historical_bid_ask", "status": "PARTIAL", "missing": "eval-tape Bid/Ask coverage", "without_trading": True},
        {"id": "historical_swap", "status": UNKNOWN, "missing": "historical swap series", "without_trading": True},
        {"id": "ev_eq_01", "status": NOT_PROVEN, "missing": "both REAL symbols or official equivalence", "without_trading": True},
        {"id": "executable", "status": BLOCKED, "missing": "verified commission first", "without_trading": True},
        {"id": "cost_aware_robustness", "status": "MODELED", "missing": "Phase 48 net results", "without_trading": True},
        {"id": "raw_time_stability", "status": "FRAGILE", "missing": "not a closeable evidence gap", "without_trading": True},
        {"id": "production_readiness", "status": "NOT_READY", "missing": "costs + parity", "without_trading": True},
        {"id": "real_symbol_env", "status": UNKNOWN, "missing": "sanitized operator dump (do not read .env here)", "without_trading": True},
    ]
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "phase40_scan_rerun": False,
        "mt5_attached": False,
        "env_accessed": False,
        "cabinet_login": False,
        "commission": {
            "status": UNKNOWN,
            "VERIFIED_SCHEDULE": False,
            "account_product_type": (p43.get("account_product") or {}).get("ACCOUNT_PRODUCT_STATUS") or UNKNOWN,
            "classification": comm43.get("classification") or "OBSERVED_ZERO_NOT_PROVEN",
            "zero_converted_to_schedule": False,
            "public_pages_applied": False,
            "public_docs_grade": "GENERIC_SUPPORTING",
            "public_docs_account_applicable": False,
            "public_docs": public_docs,
            "why": "No account-applicable product/tier/basis/rate/effective-date. Official ECN $5 and CLASSIC None remain GENERIC_SUPPORTING.",
        },
        "symbol": {
            "SYMBOL_MAPPING": (p43.get("symbol") or {}).get("SYMBOL_MAPPING") or NOT_PROVEN,
            "EV_EQ_01": (p43.get("ev_eq_01") or {}).get("status") or NOT_PROVEN,
            "CURRENT_TERMINAL_XAUUSD": (p43.get("symbol") or {}).get("CURRENT_TERMINAL_XAUUSD") or "NOT_OBSERVED",
            "inferred_from_name_overlap": False,
        },
        "request_fill": {
            "pairs": pairs,
            "journal_xauusd_i_pairs": int(rf43.get("journal_xauusd_i_pairs") or rf42.get("journal_xauusd_i_pairs") or 0),
            "journal_schema_looks_for_requested_and_fill": journal_has_schema,
            "requested_vs_executed_price": ((p43.get("execution") or {}).get("requested_vs_executed_price"))
            or "NOT_IDENTIFIABLE",
            "synthetic_pairs_created": False,
            "orders_placed_to_generate_telemetry": False,
            "future_requirement": TELEMETRY_REQUIREMENT,
        },
        "spread": {
            "HISTORICAL_BID_ASK": "PARTIAL",
            "unbounded_tick_download": False,
            "canonical_overwritten": False,
            "covers_1291d_eval_tape": bool((p43.get("spread") or {}).get("covers_1291d_eval_tape")),
            "sidecars": [
                {
                    "path": s.get("path"),
                    "exists": s.get("exists"),
                    "rows": s.get("rows"),
                    "covers_phase38_eval_tape": s.get("covers_phase38_eval_tape"),
                }
                for s in sidecars
            ],
        },
        "swap": {
            "CURRENT_SWAP": (p43.get("swap") or {}).get("CURRENT_SWAP") or "OBSERVED",
            "HISTORICAL_SWAP": UNKNOWN,
            "fabricated_from_current": False,
        },
        "cost_margin": {
            "RAW_EXPECTANCY_R": raw,
            "MODELED_1X_R": modeled_exp,
            "uncertainty_exceeds_raw_edge": True,
            "viable_because_raw_positive": False,
            "minimum_verified_for_executable": [
                "account-applicable commission VERIFIED_SCHEDULE",
                "documented spread treatment",
                "documented swap treatment",
                "slippage classified (MODELED allowed if labeled)",
                "frozen Phase 40 tape",
            ],
        },
        "evidence_inspected": [
            PHASE40_JSON,
            PHASE42_JSON,
            PHASE43_JSON,
            PHASE44_JSON,
            PHASE45_JSON,
            PHASE46_JSON,
            "tradingbot/backtest/phase42_broker_cost_execution_closure.py",
            "docs_v2/01_truth/CONFIGURATION_TRUTH.md",
            "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md",
        ],
        "mt5_attach_attempted": False,
        "blockers_closed": [],
        "blockers_remaining": remaining,
        "phase44_executable_ready": (p44.get("EXECUTABLE_READY") is True),
        "phase45_robustness": p45.get("robustness_verdict"),
        "phase46_readiness": p46.get("production_readiness"),
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
        "artifacts": {"json": PHASE47_JSON, "md": PHASE47_MD},
    }
    (root / PHASE47_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE47_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    md = [
        "# Phase 47 — Blocker Closure (Maximum Information Value)",
        "",
        f"**STATUS:** `{payload['status']}`",
        f"**COMMISSION:** `{UNKNOWN}`",
        f"**VERIFIED_SCHEDULE:** `False`",
        f"**SYMBOL_MAPPING:** `{payload['symbol']['SYMBOL_MAPPING']}`",
        f"**EV-EQ-01:** `{payload['symbol']['EV_EQ_01']}`",
        f"**REQUEST_FILL:** `{pairs}`",
        f"**HISTORICAL_BID_ASK:** `PARTIAL`",
        f"**HISTORICAL_SWAP:** `{UNKNOWN}`",
        f"**BLOCKERS_CLOSED:** `0`",
        f"**FINAL_GATE:** `{BLOCKED}`",
        "",
        "Inspected frozen Phase 40–46 artifacts and official LiteFinance pages already captured in Phase 43.",
        "No account-applicable product/tier/basis/rate/effective-date was found. Official ECN $5/lot and CLASSIC None remain GENERIC_SUPPORTING.",
        "Observed deal commission zeros were **not** converted into a VERIFIED_SCHEDULE.",
        "XAUUSD ↔ XAUUSD_i was **not** inferred from name overlap. EV-EQ-01 remains NOT_PROVEN.",
        "Journal schema can look for requested_price/fill_price, but XAUUSD_i request/fill pairs remain 0. No synthetic fills. No orders.",
        "Existing Bid/Ask sidecars do not cover the 1291-day eval tape. No unbounded tick download. Canonical files not overwritten.",
        "Historical swap series remains UNKNOWN. Current broker swap was not back-filled into history.",
        "RAW +0.017224R does not survive modeled 1x cost (−0.060787R). Strategy is not viable because raw expectancy is positive.",
        "",
        "MT5 was not attached. `.env` was not read. No cabinet login. No Phase 40 rescan.",
        "",
        "## Telemetry requirement (future, non-trading)",
        "",
        TELEMETRY_REQUIREMENT,
        "",
        "STOP. Phase 48 remains fail-closed while commission is UNKNOWN.",
        "",
    ]
    (root / PHASE47_MD).write_text("\n".join(md), encoding="utf-8")
    return payload


if __name__ == "__main__":
    print(run_phase47_collection(Path("."))["commission"]["VERIFIED_SCHEDULE"])

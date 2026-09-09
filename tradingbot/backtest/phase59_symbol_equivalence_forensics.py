"""Phase 59 — XAUUSD ↔ XAUUSD_i equivalence forensics.

Does not rename symbols. Path/swap match is SUPPORTING only.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase42_broker_cost_execution_closure import attach_if_running
from tradingbot.backtest.phase54_account_broker_evidence import (
    FROZEN_TAPE_FINGERPRINT,
    compare_identity,
    snapshot_symbol,
)

PHASE = "59"
PHASE59_JSON = "logs/phase59_symbol_equivalence_forensics.json"
PHASE59_MD = "docs/PHASE59_SYMBOL_EQUIVALENCE_FORENSICS.md"
PHASE40_JSON = "logs/phase40_full_horizon_validation.json"
PHASE54_JSON = "logs/phase54_account_broker_evidence.json"
UNKNOWN = "UNKNOWN"
NOT_PROVEN = "NOT_PROVEN"
BLOCKED = "BLOCKED"
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "SYMBOL_MAPPING",
    "PROOF_BASIS",
    "OPERATOR_OR_BROKER_EVIDENCE_REQUIRED",
    "final_gate",
    "production_safety",
    "artifacts",
)
OFFICIAL_XAUUSD_PAGE = {
    "url": "https://www.litefinance.org/trading/trading-instruments/commodities/xauusd/",
    "fetched_utc": "2026-09-08",
    "symbol_named": "XAUUSD",
    "available_in_accounts": ["ECN", "CLASSIC"],
    "swap_long": -89.136,
    "swap_short": 3.45,
    "contract_size": 100,
    "explicit_alias_statement_for_XAUUSD_i": False,
}
OFFICIAL_CABINET_XAUUSD = {
    "url": "https://my.litefinance.org/trading/info?symbol=XAUUSD",
    "fetched_utc": "2026-09-08",
    "symbol_named": "XAUUSD",
    "lot_size": "100 Oz",
    "min_volume": 0.01,
    "max_volume": 100,
    "volume_step": 0.01,
    "price_of_point_usd": 1.00,
    "swap_long_points": -89.136,
    "swap_short_points": 3.45,
    "triple_swap_day": "Wednesday",
    "mentions_XAUUSD_i": False,
    "explicit_alias_statement_for_XAUUSD_i": False,
    "grade": "SUPPORTING_EVIDENCE",
}


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


def run_phase59_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p54 = _safe_load_json(root / PHASE54_JSON) or {}
    pack = attach_if_running()
    attached = bool((pack.get("attach") or {}).get("ok"))
    symbols: dict[str, Any] = {}
    if attached:
        import MetaTrader5 as mt5

        for name in ("XAUUSD", "XAUUSD_i", "XAUPUSD_cl"):
            symbols[name] = snapshot_symbol(mt5, name)
    else:
        symbols = p54.get("symbols") or {}
    xi = symbols.get("XAUUSD_i") or {}
    identity = compare_identity(symbols.get("XAUUSD") or {}, xi)
    def _num(value: Any) -> float | None:
        try:
            if value in (None, UNKNOWN):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    xi_long = _num(xi.get("swap_long"))
    xi_short = _num(xi.get("swap_short"))
    swap_match = (
        xi_long is not None
        and xi_short is not None
        and abs(xi_long - OFFICIAL_XAUUSD_PAGE["swap_long"]) < 1e-6
        and abs(xi_short - OFFICIAL_XAUUSD_PAGE["swap_short"]) < 1e-6
    )
    contract_match = _num(xi.get("contract_size")) == float(OFFICIAL_XAUUSD_PAGE["contract_size"])
    supporting = []
    if swap_match:
        supporting.append("Official XAUUSD marketing/spec page swap long/short equals observed XAUUSD_i swaps")
    if contract_match:
        supporting.append("Official XAUUSD contract size 100 equals observed XAUUSD_i")
    supporting.append("CODE PRIMARY_SYMBOL / research tape is XAUUSD_i; REAL catalog exposes XAUUSD_i")
    supporting.append("Operator-stated REAL name XAUUSD remains a CX, not silently mapped")
    live_txt = ""
    live_path = root / "tradingbot/config/live.py"
    if live_path.is_file():
        live_txt = live_path.read_text(encoding="utf-8")
    code_symbol = "XAUUSD_i" if 'PRIMARY_SYMBOL = "XAUUSD_i"' in live_txt else UNKNOWN
    mapping = identity["IDENTITY_STATUS"]
    if mapping == "PROVEN" and not OFFICIAL_XAUUSD_PAGE["explicit_alias_statement_for_XAUUSD_i"]:
        mapping = "PARTIAL"
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "phase40_scan_rerun": False,
        "mt5_launched": False,
        "mt5_attached": attached,
        "env_accessed": False,
        "symbols": symbols,
        "identity": identity,
        "XAUUSD_CURRENT_TERMINAL": identity.get("CURRENT_TERMINAL_XAUUSD"),
        "broker_wide_absence_concluded": False,
        "path_analysis": {
            "XAUUSD_i_path": xi.get("path"),
            "classification": "SUPPORTING_EVIDENCE",
            "proves_account_type": False,
            "proves_equivalence": False,
            "note": "CLS_LOW_SPREAD_i is a broker category path. Official meaning not published. Not used as G1 or G3 proof.",
        },
        "official_xauusd_page": OFFICIAL_XAUUSD_PAGE,
        "official_cabinet_xauusd": OFFICIAL_CABINET_XAUUSD,
        "economics_match_official_xauusd": {"swap": swap_match, "contract_size": contract_match, "grade": "SUPPORTING_EVIDENCE"},
        "code_research_symbol": code_symbol,
        "historical_tape_symbol": "XAUUSD_i",
        "datasets_renamed": False,
        "SYMBOL_MAPPING": mapping if mapping != "PROVEN" else "PARTIAL",
        "EV_EQ_01": NOT_PROVEN if mapping != "PROVEN" else "VERIFIED",
        "PROOF_BASIS": supporting
        + [
            "No official LiteFinance document fetched in this phase states that XAUUSD_i is the tradable alias of XAUUSD.",
            "Third-party suffix taxonomies were not used as official evidence.",
            "Matching contract/tick/swap/price is supporting only.",
            "Official cabinet instrument page names XAUUSD with matching swap/contract/point value and does not mention XAUUSD_i.",
            "No official LiteFinance page fetched states that suffix _i means alias of the unsuffixed symbol.",
        ],
        "OPERATOR_OR_BROKER_EVIDENCE_REQUIRED": [
            "Official LiteFinance statement or support reply: XAUUSD_i on LiteFinance-MT5-Live is the REAL tradable symbol corresponding to XAUUSD.",
            "Or an official catalog that lists both names as equivalent for this account type.",
            "Screenshot acceptable with account number, balance, credentials, and personal information redacted.",
        ],
        "G3": "FAIL" if mapping in {NOT_PROVEN, "CONTRADICTED"} else "PARTIAL" if mapping == "PARTIAL" else "PASS",
        "final_gate": BLOCKED,
        "FINAL_GATE": BLOCKED,
        "production_safety": {
            "TRADING": "NOT_PERFORMED",
            "ORDERS": 0,
            "ENV": "NOT_READ",
            "PHASE40_RESCAN": "NO",
            "STRATEGY": "NOT_MODIFIED",
            "production_changes": "NONE",
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE59_JSON, "md": PHASE59_MD},
        "frozen_tape_fingerprint": p40.get("tape_fingerprint") or FROZEN_TAPE_FINGERPRINT,
    }
    if identity.get("CURRENT_TERMINAL_XAUUSD") == "NOT_OBSERVED":
        payload["SYMBOL_MAPPING"] = NOT_PROVEN
        payload["G3"] = "FAIL"
    (root / PHASE59_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE59_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    md = [
        "# Phase 59 — Symbol Equivalence Forensics",
        "",
        f"**SYMBOL_MAPPING:** `{payload['SYMBOL_MAPPING']}`",
        f"**XAUUSD_CURRENT_TERMINAL:** `{payload['XAUUSD_CURRENT_TERMINAL']}`",
        f"**G3:** `{payload['G3']}`",
        "",
        "XAUUSD absence is NOT_OBSERVED, not BROKER_ABSENT, not CONTRADICTED.",
        "Official XAUUSD page swaps/contract match XAUUSD_i — SUPPORTING only; no explicit `_i` alias statement.",
        "Cabinet instrument page for XAUUSD matches the same economics and still does not name XAUUSD_i.",
        "CLS_LOW_SPREAD_i path is SUPPORTING_EVIDENCE only.",
        "",
        "CODE/research uses XAUUSD_i. Operator REAL=XAUUSD remains CX-REAL-SYMBOL.",
        "",
    ]
    (root / PHASE59_MD).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE59_MD).write_text("\n".join(md), encoding="utf-8")
    return payload


if __name__ == "__main__":
    print(run_phase59_collection(Path("."))["SYMBOL_MAPPING"])

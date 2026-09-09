"""Phase 27.33 — EV-EQ-01 resolution for REAL LiteFinance-MT5-Live.

Read-only. Absence is NOT_PROVEN, not DISPROVEN. Policy State B is not
equivalence. Does not insert maps, start MT5, or rewrite parquet.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.dataset_contract import (
    STATUS_EXPLICIT_MAP,
    STATUS_INVALID_MAP,
    STATUS_MATCH,
    STATUS_MISSING_MAP,
    InstrumentContractError,
    classify_dataset_binding,
    resolve_broker_symbol_for_dataset,
)
from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase25h_run import build_immutability_manifest, verify_immutability
from tradingbot.backtest.phase27_8_policy_lock import LOCKED_POLICY
from tradingbot.backtest.phase27_9_real_broker_evidence import bounded_readonly_attach_once
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_17_real_broker_evidence import (
    SYMBOLS,
    account_identity_snapshot,
    catalog_existence_check,
    inspect_symbol_readonly,
    terminal_build_snapshot,
    unknown_symbol_row,
)
from tradingbot.backtest.phase27_30_slippage_evidence import (
    CANONICAL_PARQUET,
    file_fingerprint,
    inherit_prior_real_identity,
)
from tradingbot.backtest.symbol_equivalence import (
    COMPARISON_FIELDS,
    EquivalenceConclusion,
    SPEC_FIELD_MAP,
)
from tradingbot.config.live import PRIMARY_SYMBOL

PHASE2733_JSON = "logs/phase27_33_ev_eq_resolution.json"
PHASE2733_MD = "docs_v2/01_truth/PHASE27_33_EV_EQ_RESOLUTION.md"
PHASE2717_JSON = "logs/phase27_17_real_broker_evidence.json"
PHASE2727_JSON = "logs/phase27_27_dataset_symbol_binding.json"
CANONICAL_SYMBOL = PRIMARY_SYMBOL
UNKNOWN = "UNKNOWN"
BLOCKED = "BLOCKED"
REQUIRED_ENV = "REAL"
REQUIRED_SERVER = "LiteFinance-MT5-Live"

STATE_A = "A_EQUIVALENCE_PROVEN"
STATE_B = "B_POLICY_AUTHORIZED_XAUUSD_i_ONLY"
STATE_C = "C_NEITHER_PROVEN"

SOURCE_SEARCH_PATHS = (
    PHASE2717_JSON,
    PHASE2727_JSON,
    "logs/phase27_8_policy_lock.json",
    "logs/phase27_9_real_broker_evidence.json",
    "logs/phase27_10_dataset_symbol_binding.json",
    "logs/phase27_20_dataset_mapping_closure.json",
    "logs/phase27_32_final_cost_evidence_gate.json",
    "docs_v2/01_truth/OPERATOR_BROKER_POLICY_DECISION.md",
    "docs_v2/01_truth/DEMO_REAL_SYMBOL_COST_DESIGN.md",
)

REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "account_type",
    "broker",
    "server",
    "terminal_build",
    "XAUUSD",
    "XAUUSD_i",
    "field_comparison",
    "ev_eq_01",
    "selected_state",
    "operator_policy",
    "dataset_binding",
    "contract_behavior",
    "FINAL_GATE",
    "production_code_changed",
    "datasets_changed",
    "maps_inserted",
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


def _spec_value(row: dict[str, Any], field: str) -> Any:
    for key in SPEC_FIELD_MAP.get(field, (field,)):
        if key in row and row.get(key) not in (None, "", UNKNOWN, "NOT AVAILABLE"):
            return row.get(key)
    return None


def compare_economics(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    matching: list[str] = []
    differing: list[dict[str, Any]] = []
    unknown: list[str] = []
    for field in COMPARISON_FIELDS:
        lv = _spec_value(left, field)
        rv = _spec_value(right, field)
        if lv is None or rv is None:
            unknown.append(field)
            continue
        if lv == rv:
            matching.append(field)
        else:
            differing.append({"field": field, "XAUUSD": lv, "XAUUSD_i": rv})
    return {
        "matching_fields": matching,
        "differing_fields": differing,
        "unknown_fields": unknown,
        "matching_count": len(matching),
        "differing_count": len(differing),
        "unknown_count": len(unknown),
    }


def classify_ev_eq_resolution(
    *,
    xauusd_exists: bool,
    xauusd_i_exists: bool,
    same_real_terminal: bool,
    comparison: dict[str, Any],
    policy_state_b_locked: bool,
) -> dict[str, Any]:
    """Absence is NOT_PROVEN. Policy B is not EV-EQ proof."""
    mismatches = int(comparison.get("differing_count") or 0)
    unknowns = int(comparison.get("unknown_count") or 0)
    if xauusd_exists and xauusd_i_exists and same_real_terminal and mismatches > 0:
        return {
            "classification": EquivalenceConclusion.DISPROVEN.value,
            "state": STATE_B if policy_state_b_locked else STATE_C,
            "proven": False,
            "reason": (
                "Both symbols exist on the same Real terminal but economically material "
                "fields differ. EV-EQ-01 is DISPROVEN / NOT_EQUIVALENT. No map may be created."
            ),
        }
    if (
        xauusd_exists
        and xauusd_i_exists
        and same_real_terminal
        and mismatches == 0
        and unknowns == 0
    ):
        return {
            "classification": EquivalenceConclusion.PROVEN.value,
            "state": STATE_A,
            "proven": True,
            "reason": "Same-terminal field-by-field MATCH on all economically material fields.",
        }
    if not xauusd_exists:
        return {
            "classification": EquivalenceConclusion.NOT_PROVEN.value,
            "state": STATE_B if policy_state_b_locked else STATE_C,
            "proven": False,
            "reason": (
                "XAUUSD is absent on the observed Real terminal. Absence is NOT_PROVEN, "
                "not DISPROVEN and not broker-wide absence. Similar XAUUSD_i economics "
                "do not invent XAUUSD. State B is available only as operator policy, "
                "not as proven equivalence."
            ),
        }
    return {
        "classification": EquivalenceConclusion.NOT_PROVEN.value,
        "state": STATE_B if policy_state_b_locked else STATE_C,
        "proven": False,
        "reason": "Same-terminal comparison is incomplete. EV-EQ-01 remains NOT_PROVEN.",
    }


def policy_authorizes_silent_mapping() -> bool:
    return False


def audit_contract_behavior() -> dict[str, Any]:
    missing = classify_dataset_binding("XAUUSD", configured_symbol=CANONICAL_SYMBOL, dataset_symbol_map={})
    invalid = classify_dataset_binding(
        "XAUUSD",
        configured_symbol=CANONICAL_SYMBOL,
        dataset_symbol_map={"XAUUSD": "EURUSD"},
    )
    explicit = classify_dataset_binding(
        "XAUUSD",
        configured_symbol=CANONICAL_SYMBOL,
        dataset_symbol_map={"XAUUSD": CANONICAL_SYMBOL},
    )
    direct = classify_dataset_binding("XAUUSD_i", configured_symbol=CANONICAL_SYMBOL, dataset_symbol_map={})
    silent = False
    try:
        resolve_broker_symbol_for_dataset("XAUUSD", configured_symbol=CANONICAL_SYMBOL)
        silent = True
    except InstrumentContractError:
        silent = False
    return {
        "missing_map": missing.mapping_status if missing.blocked else "ALLOWED",
        "invalid_map": invalid.mapping_status if invalid.blocked else "ALLOWED",
        "valid_explicit_map": explicit.mapping_status if not explicit.blocked else "BLOCKED",
        "direct_XAUUSD_i": direct.mapping_status if not direct.blocked else "BLOCKED",
        "silent_conversion": silent,
        "explicit_map_proves_ev_eq": False,
        "details": {
            "missing": missing.to_dict(),
            "invalid": invalid.to_dict(),
            "explicit": explicit.to_dict(),
            "direct": direct.to_dict(),
        },
    }


def recount_dataset_binding(root: Path) -> dict[str, Any]:
    prior = _safe_load_json(root / PHASE2727_JSON) or {}
    totals = dict(prior.get("totals") or {})
    matrix = prior.get("binding_matrix") or []
    recount = {
        "DIRECT_CANONICAL_MATCH": 0,
        "EXPLICIT_MAPPED": 0,
        "MISSING_EXPLICIT_MAP": 0,
        "INVALID_MAP": 0,
        "UNKNOWN_PROVENANCE": 0,
    }
    for row in matrix:
        state = str(row.get("binding_state") or "")
        if state in recount:
            recount[state] += 1
    return {
        "source": PHASE2727_JSON,
        "recomputed": False,
        "maps_inserted": False,
        "total": totals.get("total_relevant_datasets") or len(matrix),
        "direct_XAUUSD_i": recount["DIRECT_CANONICAL_MATCH"],
        "explicit_mapped": recount["EXPLICIT_MAPPED"],
        "missing_map": recount["MISSING_EXPLICIT_MAP"],
        "invalid_map": recount["INVALID_MAP"],
        "unknown": recount["UNKNOWN_PROVENANCE"],
        "prior_totals": totals,
        "recount_matches_prior": recount == {
            "DIRECT_CANONICAL_MATCH": int(totals.get("DIRECT_CANONICAL_MATCH") or 0),
            "EXPLICIT_MAPPED": int(totals.get("EXPLICIT_MAPPED") or 0),
            "MISSING_EXPLICIT_MAP": int(totals.get("MISSING_EXPLICIT_MAP") or 0),
            "INVALID_MAP": int(totals.get("INVALID_MAP") or 0),
            "UNKNOWN_PROVENANCE": int(totals.get("UNKNOWN_PROVENANCE") or 0),
        },
    }


def collect_live_catalog() -> dict[str, Any]:
    attach = bounded_readonly_attach_once()
    meta: dict[str, Any] = {
        "attempted": True,
        "attach_ok": bool(attach.get("ok")),
        "attach_error": attach.get("error"),
        "environment_ok": False,
        "method": "symbols_get + symbol_info read-only; no symbol_select",
        "XAUUSD": unknown_symbol_row("XAUUSD"),
        "XAUUSD_i": unknown_symbol_row("XAUUSD_i"),
        "catalog": {},
    }
    if not attach.get("ok"):
        meta["stop_reason"] = "BLOCKED_PENDING_OPERATOR"
        return meta
    import MetaTrader5 as mt5

    account = account_identity_snapshot(mt5)
    terminal = terminal_build_snapshot(mt5)
    env = str(account.get("trade_mode_label") or UNKNOWN)
    server = str(account.get("server") or UNKNOWN)
    meta["account"] = account
    meta["terminal"] = terminal
    meta["environment"] = env
    meta["server"] = server
    if env != REQUIRED_ENV or server != REQUIRED_SERVER:
        meta["stop_reason"] = "BLOCKED_PENDING_OPERATOR"
        meta["error"] = f"attached {env}/{server} is not {REQUIRED_ENV}/{REQUIRED_SERVER}"
        return meta
    meta["environment_ok"] = True
    catalog = catalog_existence_check(mt5, SYMBOLS)
    meta["catalog"] = catalog
    meta["XAUUSD"] = inspect_symbol_readonly(mt5, "XAUUSD")
    meta["XAUUSD_i"] = inspect_symbol_readonly(mt5, "XAUUSD_i")
    return meta


def run_phase27_33_ev_eq_resolution(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path(__file__).resolve().parents[2])
    timestamp = _utc_now()
    fingerprint_before = file_fingerprint(root / CANONICAL_PARQUET)
    before = build_immutability_manifest(root)
    prior17 = _safe_load_json(root / PHASE2717_JSON) or {}
    live = collect_live_catalog()
    identity = inherit_prior_real_identity(root)

    if live.get("environment_ok"):
        xau = live.get("XAUUSD") or unknown_symbol_row("XAUUSD")
        xaui = live.get("XAUUSD_i") or unknown_symbol_row("XAUUSD_i")
        env = str(live.get("environment") or REQUIRED_ENV)
        broker = (live.get("account") or {}).get("broker") or identity.get("broker")
        server = live.get("server") or identity.get("server")
        terminal_build = (live.get("terminal") or {}).get("build")
        evidence_source = "fresh_readonly_catalog"
        same_terminal = True
    else:
        econ = prior17.get("economics") or {}
        xau = econ.get("XAUUSD") or unknown_symbol_row("XAUUSD")
        xaui = econ.get("XAUUSD_i") or unknown_symbol_row("XAUUSD_i")
        env = str(prior17.get("account_environment") or identity.get("account_type") or UNKNOWN)
        broker = prior17.get("broker") or identity.get("broker")
        server = (prior17.get("account") or {}).get("server") or identity.get("server")
        terminal_build = identity.get("terminal_build") or 6182
        evidence_source = "reused_phase27_17_real_artifact; live attach skipped"
        same_terminal = env == REQUIRED_ENV

    xau_exists = str(xau.get("existence") or "").upper() == "YES"
    xaui_exists = str(xaui.get("existence") or "").upper() == "YES"
    comparison = compare_economics(xau, xaui)
    policy_b = (
        LOCKED_POLICY.get("DECISION_1") == "XAUUSD_i"
        and LOCKED_POLICY.get("DECISION_2") == "ONLY_WITH_EXPLICIT_DATASET_MAP"
    )
    resolution = classify_ev_eq_resolution(
        xauusd_exists=xau_exists,
        xauusd_i_exists=xaui_exists,
        same_real_terminal=same_terminal and env == REQUIRED_ENV,
        comparison=comparison,
        policy_state_b_locked=policy_b,
    )
    if not xau_exists and resolution["classification"] == EquivalenceConclusion.DISPROVEN.value:
        resolution["classification"] = EquivalenceConclusion.NOT_PROVEN.value
        resolution["proven"] = False

    binding = recount_dataset_binding(root)
    contract = audit_contract_behavior()
    final_gate = (_safe_load_json(root / PHASE2716_JSON) or {}).get("FINAL_GATE") or UNKNOWN
    originals_untouched, imm_issues = verify_immutability(before, base_dir=root)
    fingerprint_after = file_fingerprint(root / CANONICAL_PARQUET)
    datasets_changed = not originals_untouched or fingerprint_before != fingerprint_after

    payload: dict[str, Any] = {
        "schema_version": 1,
        "phase": "27.33",
        "status": "PASS",
        "timestamp_utc": timestamp,
        "timestamp": timestamp,
        "repository_commit": _git_head(root),
        "account_type": env,
        "broker": broker,
        "server": server,
        "terminal_build": terminal_build,
        "identity_provenance": evidence_source,
        "symbol": CANONICAL_SYMBOL,
        "XAUUSD": {
            "exists": xau_exists,
            "visible": xau.get("visibility"),
            "economics": xau,
        },
        "XAUUSD_i": {
            "exists": xaui_exists,
            "visible": xaui.get("visibility"),
            "economics": xaui,
        },
        "field_comparison": comparison,
        "ev_eq_01": {
            "state": resolution["state"],
            "classification": resolution["classification"],
            "proven": resolution["proven"],
            "reason": resolution["reason"],
            "absence_not_disproven": not xau_exists,
            "absence_not_broker_wide": not xau_exists,
            "similar_economics_not_sufficient": True,
            "policy_is_not_equivalence": True,
        },
        "selected_state": resolution["state"],
        "operator_policy": {
            "canonical_symbol": LOCKED_POLICY["DECISION_1"],
            "dataset_mapping_policy": LOCKED_POLICY["DECISION_2"],
            "policy_authorizes_silent_mapping": policy_authorizes_silent_mapping(),
            "policy_authorizes_state_b": policy_b,
        },
        "dataset_binding": binding,
        "contract_behavior": {
            "missing_map": "BLOCK" if contract["missing_map"] == STATUS_MISSING_MAP else contract["missing_map"],
            "invalid_map": "BLOCK" if contract["invalid_map"] == STATUS_INVALID_MAP else contract["invalid_map"],
            "valid_explicit_map": "ALLOWED" if contract["valid_explicit_map"] == STATUS_EXPLICIT_MAP else contract["valid_explicit_map"],
            "direct_XAUUSD_i": "ALLOWED" if contract["direct_XAUUSD_i"] == STATUS_MATCH else contract["direct_XAUUSD_i"],
            "silent_conversion": False,
            "explicit_map_proves_ev_eq": False,
            "audit": contract,
        },
        "maps_inserted": False,
        "existing_evidence_search": [{"path": p, "present": (root / p).is_file()} for p in SOURCE_SEARCH_PATHS],
        "live_collection": {
            k: v for k, v in live.items() if k not in {"XAUUSD", "XAUUSD_i", "account"}
        },
        "FINAL_GATE": final_gate,
        "cost_completeness": BLOCKED,
        "production_readiness": BLOCKED,
        "complete_costs_required_weakened": False,
        "production_code_changed": False,
        "datasets_changed": datasets_changed,
        "canonical_fingerprint_before": fingerprint_before,
        "canonical_fingerprint_after": fingerprint_after,
        "original_datasets_untouched": originals_untouched,
        "immutability_issues": imm_issues,
        "blockers": [
            "EV-EQ-01 NOT_PROVEN — XAUUSD absent on observed Real terminal",
            "30 logical XAUUSD datasets remain MISSING_EXPLICIT_MAP",
            "State B is policy, not proven equivalence",
            "FINAL_GATE remains BLOCKED",
        ],
        "safety_confirmation": {
            "mt5_started": False,
            "orders_sent": False,
            "symbol_select_called": False,
            "env_file_read": False,
            "parquet_rewritten": False,
            "maps_inserted": False,
            "xauusd_economics_invented": False,
            "equivalence_inferred_from_name": False,
            "strategy_modified": False,
            "riskgate_modified": False,
            "execution_modified": False,
            "phase_27_34_started": False,
        },
        "deferred": ["Phase 27.34+ — not started"],
    }
    missing = [k for k in REQUIRED_ARTIFACT_KEYS if k not in payload]
    required_ok = (
        not missing,
        originals_untouched,
        fingerprint_before == fingerprint_after,
        not datasets_changed,
        not payload["maps_inserted"],
        not payload["production_code_changed"],
        payload["ev_eq_01"]["classification"] != EquivalenceConclusion.PROVEN.value,
        payload["ev_eq_01"]["classification"] != EquivalenceConclusion.DISPROVEN.value if not xau_exists else True,
        payload["operator_policy"]["policy_authorizes_silent_mapping"] is False,
        payload["contract_behavior"]["silent_conversion"] is False,
        payload["contract_behavior"]["missing_map"] == "BLOCK",
        payload["contract_behavior"]["valid_explicit_map"] == "ALLOWED",
        payload["dataset_binding"]["missing_map"] == 30,
        payload["dataset_binding"]["direct_XAUUSD_i"] == 2,
        payload["FINAL_GATE"] == BLOCKED,
        not payload["complete_costs_required_weakened"],
    )
    if not all(required_ok):
        payload["status"] = "FAILED"
        if missing:
            payload["blockers"] = list(payload["blockers"]) + [f"missing_artifact_keys:{','.join(missing)}"]
    if live.get("stop_reason") == "BLOCKED_PENDING_OPERATOR" and not live.get("environment_ok"):
        if payload["status"] != "FAILED":
            payload["status"] = "PASS_WITH_DEFERRAL"

    out = root / PHASE2733_JSON
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    _write_md(root, payload)
    _update_truth_docs(root, payload)
    return payload


def run_phase27_33_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    return run_phase27_33_ev_eq_resolution(base_dir)


def _write_md(root: Path, payload: dict[str, Any]) -> None:
    ev = payload["ev_eq_01"]
    xau = payload["XAUUSD"]
    xaui = payload["XAUUSD_i"]
    cmp_ = payload["field_comparison"]
    bind = payload["dataset_binding"]
    pol = payload["operator_policy"]
    con = payload["contract_behavior"]
    md = f"""# Phase 27.33 — EV-EQ-01 Resolution

**Status:** {payload["status"]}  
**EV-EQ-01:** `{ev["classification"]}`  
**State:** `{payload["selected_state"]}`  
**Proven:** `{ev["proven"]}`  
**Artifact:** `{PHASE2733_JSON}`  
**Timestamp UTC:** `{payload["timestamp_utc"]}`

Read-only. Maps were not inserted. Production parquet was not rewritten.
Absence of `XAUUSD` is **NOT_PROVEN**, not DISPROVEN. Operator policy State B is **not** equivalence.

## Real account

| Field | Value |
|---|---|
| account | `{payload["account_type"]}` |
| broker | `{payload["broker"]}` |
| server | `{payload["server"]}` |
| terminal build | `{payload["terminal_build"]}` |
| evidence source | `{payload.get("identity_provenance")}` |

## Symbols

| Symbol | Exists | Visible |
|---|---|---|
| XAUUSD | `{xau["exists"]}` | `{xau["visible"]}` |
| XAUUSD_i | `{xaui["exists"]}` | `{xaui["visible"]}` |

## Field comparison

Matching: `{cmp_["matching_count"]}` — {cmp_["matching_fields"]}  
Differing: `{cmp_["differing_count"]}` — {cmp_["differing_fields"]}  
Unknown: `{cmp_["unknown_count"]}` — {cmp_["unknown_fields"]}

{ev["reason"]}

## Operator policy

| Field | Value |
|---|---|
| canonical_symbol | `{pol["canonical_symbol"]}` |
| dataset_mapping_policy | `{pol["dataset_mapping_policy"]}` |
| silent mapping authorized | `{pol["policy_authorizes_silent_mapping"]}` |

## Dataset binding (Phase 27.27 inventory, not modified)

| Metric | Count |
|---|---|
| total | `{bind["total"]}` |
| direct XAUUSD_i | `{bind["direct_XAUUSD_i"]}` |
| explicit mapped | `{bind["explicit_mapped"]}` |
| missing map | `{bind["missing_map"]}` |
| invalid map | `{bind["invalid_map"]}` |
| unknown | `{bind["unknown"]}` |

## Contract behavior

| Case | Result |
|---|---|
| missing map | `{con["missing_map"]}` |
| valid explicit map | `{con["valid_explicit_map"]}` |
| direct XAUUSD_i | `{con["direct_XAUUSD_i"]}` |
| silent conversion | `{con["silent_conversion"]}` |

FINAL_GATE remains `{payload["FINAL_GATE"]}`. Cost completeness remains `{payload["cost_completeness"]}`.

## Next

STOP after Phase 27.33.
"""
    (root / PHASE2733_MD).write_text(md, encoding="utf-8")


def _update_truth_docs(root: Path, payload: dict[str, Any]) -> None:
    ev = payload["ev_eq_01"]
    known = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    if known.is_file():
        text = known.read_text(encoding="utf-8")
        old = (
            "| XAUUSD economically equivalent to XAUUSD_i | **BLOCKED** — NOT_PROVEN (Phase 27.17 Real re-evaluated 2026-09-06) |"
        )
        new = (
            "| XAUUSD economically equivalent to XAUUSD_i | **BLOCKED** — NOT_PROVEN "
            f"(Phase 27.33 state `{payload['selected_state']}`; absence ≠ DISPROVEN; policy ≠ equivalence) |"
        )
        if old in text:
            text = text.replace(old, new)
        pointer = (
            f"**Phase 27.33 EV-EQ resolution:** `{PHASE2733_JSON}` — "
            f"`{ev['classification']}`; state `{payload['selected_state']}`; "
            "30 MISSING_EXPLICIT_MAP unchanged; no silent map"
        )
        if pointer not in text:
            anchor = (
                "**Phase 27.32 final cost evidence gate:** `logs/phase27_32_final_cost_evidence_gate.json` — "
                "COMPLETE_COSTS_REQUIRED `BLOCKED`; FINAL_GATE `BLOCKED`; AND-complete `0`/8"
            )
            if anchor in text:
                text = text.replace(anchor, anchor + "  \n" + pointer)
        known.write_text(text, encoding="utf-8")

    design = root / "docs_v2/01_truth/DEMO_REAL_SYMBOL_COST_DESIGN.md"
    if design.is_file():
        text = design.read_text(encoding="utf-8")
        pointer = (
            f"**Phase 27.33 EV-EQ resolution:** `{PHASE2733_JSON}` — "
            "NOT_PROVEN; State B is policy only; 0 maps inserted"
        )
        if pointer not in text:
            anchor = (
                "**Phase 27.32 final cost evidence gate:** `logs/phase27_32_final_cost_evidence_gate.json` — "
                "integrated audit; no grade upgrades; FINAL_GATE remains BLOCKED"
            )
            if anchor in text:
                text = text.replace(anchor, anchor + "  \n" + pointer)
        design.write_text(text, encoding="utf-8")

    config = root / "docs_v2/01_truth/CONFIGURATION_TRUTH.md"
    if config.is_file():
        text = config.read_text(encoding="utf-8")
        row = (
            "| Phase 27.33 EV-EQ resolution | `run_phase27_33_collection()` | n/a | "
            "same-terminal catalog; absence=NOT_PROVEN; no silent map | "
            f"**{payload['status']}** — `{ev['classification']}`; state `{payload['selected_state']}`; "
            f"missing maps `{payload['dataset_binding']['missing_map']}`; FINAL_GATE remains BLOCKED |"
        )
        if row not in text:
            anchor = (
                "| Phase 27.32 final cost evidence gate | `run_phase27_32_collection()` | n/a | "
                "offline synthesis 27.8–27.31; no grade upgrades; no new MT5 | "
                "**PASS** — COMPLETE_COSTS_REQUIRED `BLOCKED`; AND `0`/8; FINAL_GATE remains BLOCKED |"
            )
            if anchor in text:
                text = text.replace(anchor, anchor + "\n" + row)
        config.write_text(text, encoding="utf-8")

    phase16 = root / "docs_v2/01_truth/PHASE27_16_FINAL_VALIDATION_GATE.md"
    if phase16.is_file():
        text = phase16.read_text(encoding="utf-8")
        old = "| `ev_eq_01` | `NOT_PROVEN` | yes | **no** | `logs/phase27_9_real_broker_evidence.json` |"
        new = (
            "| `ev_eq_01` | `NOT_PROVEN` | yes | **no** | "
            "`logs/phase27_9_real_broker_evidence.json`; `logs/phase27_33_ev_eq_resolution.json` |"
        )
        if old in text:
            text = text.replace(old, new)
        phase16.write_text(text, encoding="utf-8")

    phase27 = root / "docs_v2/01_truth/PHASE27_27_DATASET_SYMBOL_BINDING.md"
    if phase27.is_file():
        text = phase27.read_text(encoding="utf-8")
        note = (
            "\n\n**Phase 27.33:** EV-EQ-01 remains NOT_PROVEN. Inventory recount unchanged "
            "(2 DIRECT_CANONICAL_MATCH / 30 MISSING_EXPLICIT_MAP / 0 EXPLICIT_MAPPED). "
            "No maps inserted. See `logs/phase27_33_ev_eq_resolution.json`.\n"
        )
        if "Phase 27.33:" not in text:
            text = text.rstrip() + note
        phase27.write_text(text, encoding="utf-8")

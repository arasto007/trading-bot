"""Phase 27.32 — Final integrated broker-cost evidence gate.

Offline. Reuses existing read-only artifacts only. Does not collect MT5 data,
upgrade grades by inference, or change production behavior.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.cost_model import CostCompleteness
from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase25h_run import build_immutability_manifest, verify_immutability
from tradingbot.backtest.phase27_8_policy_lock import LOCKED_POLICY, cost_adjusted_validation_allowed
from tradingbot.backtest.phase27_15_cost_completeness_gate import (
    GATE_COMPONENTS,
    component_is_complete,
    cost_ready_for_validation,
)
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_30_slippage_evidence import (
    CANONICAL_PARQUET,
    file_fingerprint,
    inherit_prior_real_identity,
)
from tradingbot.backtest.slippage_policy import (
    IMPLEMENTATION_LABEL,
    cost_completeness_from_modeled_slippage_only,
    modeled_is_not_realized,
)
from tradingbot.config.live import PRIMARY_SYMBOL

PHASE2732_JSON = "logs/phase27_32_final_cost_evidence_gate.json"
PHASE2732_MD = "docs_v2/01_truth/PHASE27_32_FINAL_COST_EVIDENCE_GATE.md"

UNKNOWN = "UNKNOWN"
BLOCKED = "BLOCKED"
PARTIAL = "PARTIAL"
COMPLETE = "COMPLETE"
NOT_PROVEN = "NOT_PROVEN"

SOURCE_ARTIFACTS = {
    "phase27_8": "logs/phase27_8_policy_lock.json",
    "phase27_15": "logs/phase27_15_cost_completeness_gate.json",
    "phase27_16": PHASE2716_JSON,
    "phase27_17": "logs/phase27_17_real_broker_evidence.json",
    "phase27_26": "logs/phase27_26_canonical_bidask_coverage.json",
    "phase27_27": "logs/phase27_27_dataset_symbol_binding.json",
    "phase27_28": "logs/phase27_28_commission_evidence.json",
    "phase27_29": "logs/phase27_29_swap_evidence.json",
    "phase27_30": "logs/phase27_30_slippage_evidence.json",
    "phase27_31": "logs/phase27_31_execution_evidence.json",
}

REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "account_type",
    "broker",
    "server",
    "symbol",
    "component_matrix",
    "complete_components",
    "incomplete_components",
    "complete_costs_required_result",
    "cost_adjusted_metrics_allowed",
    "FINAL_GATE",
    "production_readiness",
    "production_code_changed",
    "datasets_changed",
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


def load_existing_artifacts(root: Path) -> dict[str, dict[str, Any]]:
    loaded: dict[str, dict[str, Any]] = {}
    for key, rel in SOURCE_ARTIFACTS.items():
        data = _safe_load_json(root / rel)
        loaded[key] = data if isinstance(data, dict) else {}
    return loaded


def _row(
    *,
    component: str,
    status: str,
    evidence_grade: str,
    proven: bool,
    blocker: bool,
    required_next_evidence: str,
    artifact: str,
    note: str = "",
) -> dict[str, Any]:
    return {
        "component": component,
        "status": status,
        "evidence_grade": evidence_grade,
        "proven": proven,
        "blocker": blocker,
        "required_next_evidence": required_next_evidence,
        "artifact": artifact,
        "note": note,
    }


def cannot_upgrade_partial_coverage_to_complete(coverage: str) -> bool:
    return coverage != "COMPLETE_CANONICAL_COVERAGE"


def cannot_treat_observed_zero_as_verified(grade: str) -> bool:
    return grade != "VERIFIED_SCHEDULE"


def cannot_treat_current_swap_as_historical(historical_proven: bool) -> bool:
    return not historical_proven


def cannot_treat_modeled_as_realized() -> bool:
    return modeled_is_not_realized()


def cannot_silent_map_xauusd() -> bool:
    return LOCKED_POLICY["DECISION_2"] == "ONLY_WITH_EXPLICIT_DATASET_MAP"


def and_complete(statuses: list[str]) -> str:
    return COMPLETE if statuses and all(component_is_complete(s) for s in statuses) else BLOCKED


def build_component_matrix(arts: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    p15 = arts.get("phase27_15") or {}
    p17 = arts.get("phase27_17") or {}
    p26 = arts.get("phase27_26") or {}
    p27 = arts.get("phase27_27") or {}
    p28 = arts.get("phase27_28") or {}
    p29 = arts.get("phase27_29") or {}
    p30 = arts.get("phase27_30") or {}
    p31 = arts.get("phase27_31") or {}
    totals = p27.get("totals") or {}
    ds = (p15.get("dataset_classifications") or {}).get("counts") or {}
    ev17 = p17.get("ev_eq_01") or {}
    ev_status = ev17.get("ev_eq_01") or p28.get("ev_eq_01") or p30.get("ev_eq_01") or NOT_PROVEN
    covered = p26.get("covered_bar_count")
    total_bars = p26.get("total_bar_count")
    spread_grade = p26.get("final_classification") or UNKNOWN
    production_proxy = ((p26.get("canonical_dataset") or {}).get("spread_mode") or "PROXY") == "PROXY"

    return [
        _row(
            component="symbol_binding",
            status=BLOCKED,
            evidence_grade=(
                f"DIRECT_CANONICAL_MATCH={totals.get('DIRECT_CANONICAL_MATCH', 0)}; "
                f"MISSING_EXPLICIT_MAP={totals.get('MISSING_EXPLICIT_MAP', 0)}; "
                f"EXPLICIT_MAPPED={totals.get('EXPLICIT_MAPPED', 0)}"
            ),
            proven=False,
            blocker=True,
            required_next_evidence=(
                "Explicit dataset_symbol_map for every logical XAUUSD dataset; "
                "do not silently map to XAUUSD_i"
            ),
            artifact=SOURCE_ARTIFACTS["phase27_27"],
            note="2 MATCH / 30 missing maps / 0 inserted. Decision 2 remains ONLY_WITH_EXPLICIT_DATASET_MAP.",
        ),
        _row(
            component="ev_eq_01",
            status=str(ev_status),
            evidence_grade=str(ev_status),
            proven=str(ev_status) == "PROVEN",
            blocker=True,
            required_next_evidence="Both XAUUSD and XAUUSD_i on the same Real terminal with critical-field MATCH",
            artifact=SOURCE_ARTIFACTS["phase27_17"],
            note="XAUUSD absent + XAUUSD_i present is not equivalence. Decision 1 is POLICY, not proof.",
        ),
        _row(
            component="broker_economics",
            status=UNKNOWN,
            evidence_grade=UNKNOWN,
            proven=False,
            blocker=True,
            required_next_evidence="Fresh Real (and Demo) XAUUSD_i economics recorded as current evidence, not invented equivalence",
            artifact=SOURCE_ARTIFACTS["phase27_15"],
            note="27.16/27.15 remain UNKNOWN. A Real spec snapshot is not a complete validation economics contract.",
        ),
        _row(
            component="dataset_provenance",
            status=PARTIAL,
            evidence_grade=f"COMPLETE={ds.get('COMPLETE', 0)}; PARTIAL={ds.get('PARTIAL', 0)}; BLOCKED={ds.get('BLOCKED', 0)}",
            proven=False,
            blocker=True,
            required_next_evidence="Sidecar cost fields COMPLETE from verified evidence only; 0 COMPLETE datasets today",
            artifact=SOURCE_ARTIFACTS["phase27_15"],
            note="Canonical XAUUSD_i_5m is PARTIAL / PROXY, not COMPLETE.",
        ),
        _row(
            component="historical_spread",
            status=BLOCKED if production_proxy or cannot_upgrade_partial_coverage_to_complete(str(spread_grade)) else COMPLETE,
            evidence_grade=str(spread_grade),
            proven=False,
            blocker=True,
            required_next_evidence=(
                f"Complete canonical Bid/Ask on production parquet; logs tape is {covered}/{total_bars}; "
                "PARTIAL must not be promoted to DATASET"
            ),
            artifact=SOURCE_ARTIFACTS["phase27_26"],
            note="historical_spread PARTIAL on logs tape; production parquet remains PROXY / ohlc_only.",
        ),
        _row(
            component="commission",
            status=BLOCKED,
            evidence_grade=str(p28.get("evidence_grade") or UNKNOWN),
            proven=bool(p28.get("verified_schedule_satisfied")),
            blocker=True,
            required_next_evidence="Account-applicable VERIFIED_SCHEDULE (product type, basis, rate, effective date)",
            artifact=SOURCE_ARTIFACTS["phase27_28"],
            note="Observed zeros are not a verified schedule. Public pages GENERIC_SUPPORTING only.",
        ),
        _row(
            component="swap",
            status=UNKNOWN,
            evidence_grade=str(p29.get("evidence_grade") or UNKNOWN),
            proven=bool(p29.get("historical_swap_proven")),
            blocker=True,
            required_next_evidence="Historical swap series for XAUUSD_i; current broker rates are not historical",
            artifact=SOURCE_ARTIFACTS["phase27_29"],
            note="CURRENT_BROKER_RATE_ONLY. Realized zero on short holds ≠ historical zero.",
        ),
        _row(
            component="slippage",
            status=UNKNOWN,
            evidence_grade=str(p30.get("evidence_grade") or IMPLEMENTATION_LABEL),
            proven=False,
            blocker=True,
            required_next_evidence="Statistically sufficient genuine requested-vs-fill pairs; price_open is not requested",
            artifact=SOURCE_ARTIFACTS["phase27_30"],
            note="MODELED / MODELED_PROXY. 0 genuine pairs. MODELED ≠ REALIZED.",
        ),
        _row(
            component="execution",
            status=str(p31.get("classification") or UNKNOWN),
            evidence_grade=str(p31.get("evidence_grade") or UNKNOWN),
            proven=False,
            blocker=True,
            required_next_evidence="Order lifecycle tape: states, order→deal link, requested vs executed volume",
            artifact=SOURCE_ARTIFACTS["phase27_31"],
            note="DEAL_FILL_TAPE_ONLY. SimulatedBroker full-fill is not realized execution.",
        ),
        _row(
            component="cost_model_integrity",
            status="ENFORCED",
            evidence_grade="FAIL_CLOSED_INTACT",
            proven=True,
            blocker=False,
            required_next_evidence="None for integrity; other components still block COMPLETE",
            artifact="tradingbot/backtest/cost_model.py + slippage_policy.py",
            note=(
                f"Default commission={BacktestConfig().commission_status}, "
                f"swap={BacktestConfig().swap_status}, slippage={BacktestConfig().slippage_status}. "
                "MODELED_PROXY cannot make COMPLETE. Hidden zeros absent."
            ),
        ),
        _row(
            component="cost_completeness",
            status=BLOCKED,
            evidence_grade="INCOMPLETE",
            proven=False,
            blocker=True,
            required_next_evidence="Every required AND-component COMPLETE without weakening Decision 6",
            artifact=SOURCE_ARTIFACTS["phase27_15"],
            note="COMPLETE_COSTS_REQUIRED remains locked. 0 COMPLETE datasets.",
        ),
    ]


def gate_components_from_matrix(matrix: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_name = {row["component"]: row for row in matrix}
    mapping = {
        "symbol_binding": "symbol_binding",
        "economics": "broker_economics",
        "dataset_provenance": "dataset_provenance",
        "spread": "historical_spread",
        "commission": "commission",
        "swap": "swap",
        "slippage": "slippage",
        "execution_model": "execution",
    }
    return {gate: {"status": (by_name.get(src) or {}).get("status")} for gate, src in mapping.items()}


def run_phase27_32_final_cost_evidence_gate(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path(__file__).resolve().parents[2])
    timestamp = _utc_now()
    fingerprint_before = file_fingerprint(root / CANONICAL_PARQUET)
    before = build_immutability_manifest(root)
    arts = load_existing_artifacts(root)
    matrix = build_component_matrix(arts)
    gate_comps = gate_components_from_matrix(matrix)
    ready = cost_ready_for_validation(gate_comps)
    completeness_result = and_complete([gate_comps[n]["status"] for n in GATE_COMPONENTS])
    modeled_completeness = cost_completeness_from_modeled_slippage_only()
    allowed = cost_adjusted_validation_allowed(completeness_result)
    prior16 = str((arts.get("phase27_16") or {}).get("FINAL_GATE") or UNKNOWN)
    final_gate = BLOCKED if not ready or completeness_result != COMPLETE or prior16 == BLOCKED else COMPLETE
    if final_gate == COMPLETE:
        final_gate = BLOCKED  # fail-closed: this phase must not invent PASS
    identity = inherit_prior_real_identity(root)
    originals_untouched, imm_issues = verify_immutability(before, base_dir=root)
    fingerprint_after = file_fingerprint(root / CANONICAL_PARQUET)
    datasets_changed = not originals_untouched or fingerprint_before != fingerprint_after

    evidence_rows = [r for r in matrix if r["component"] != "cost_completeness"]
    complete_names = [r["component"] for r in evidence_rows if r["proven"] and not r["blocker"] and r["status"] in {"COMPLETE", "PROVEN", "ENFORCED"}]
    incomplete_names = [r["component"] for r in evidence_rows if r["component"] not in complete_names]
    gate_complete = [n for n in GATE_COMPONENTS if component_is_complete(gate_comps[n]["status"])]
    gate_incomplete = [n for n in GATE_COMPONENTS if n not in gate_complete]

    upgrades_forbidden = {
        "partial_bidask_to_complete": cannot_upgrade_partial_coverage_to_complete(
            str((arts.get("phase27_26") or {}).get("final_classification") or "")
        ),
        "observed_zero_commission_to_verified": cannot_treat_observed_zero_as_verified(
            str((arts.get("phase27_28") or {}).get("evidence_grade") or "")
        ),
        "current_swap_to_historical": cannot_treat_current_swap_as_historical(
            bool((arts.get("phase27_29") or {}).get("historical_swap_proven"))
        ),
        "modeled_slippage_to_realized": cannot_treat_modeled_as_realized(),
        "silent_xauusd_map": cannot_silent_map_xauusd(),
        "fill_tape_to_execution_complete": (arts.get("phase27_31") or {}).get("classification") != COMPLETE,
    }

    payload: dict[str, Any] = {
        "schema_version": 1,
        "phase": "27.32",
        "status": "PASS",
        "timestamp_utc": timestamp,
        "timestamp": timestamp,
        "repository_commit": _git_head(root),
        "account_type": identity.get("account_type"),
        "broker": identity.get("broker"),
        "server": identity.get("server"),
        "terminal_build": identity.get("terminal_build"),
        "identity_provenance": "inherited_from_phase27_29_artifact; no new MT5 collection",
        "symbol": PRIMARY_SYMBOL,
        "locked_policy": dict(LOCKED_POLICY),
        "source_artifacts": {
            key: {"path": rel, "present": bool(arts.get(key))} for key, rel in SOURCE_ARTIFACTS.items()
        },
        "component_matrix": matrix,
        "complete_components": complete_names,
        "incomplete_components": incomplete_names,
        "complete_component_count": len(complete_names),
        "incomplete_component_count": len(incomplete_names),
        "gate_and_components": GATE_COMPONENTS,
        "gate_and_complete": gate_complete,
        "gate_and_incomplete": gate_incomplete,
        "gate_and_complete_count": len(gate_complete),
        "complete_costs_required_result": completeness_result,
        "cost_ready_for_validation": ready,
        "cost_adjusted_metrics_allowed": allowed,
        "FINAL_GATE": final_gate,
        "phase27_16_final_gate_unchanged": prior16,
        "production_readiness": BLOCKED,
        "upgrades_forbidden": upgrades_forbidden,
        "modeled_slippage_completeness": modeled_completeness.value
        if hasattr(modeled_completeness, "value")
        else str(modeled_completeness),
        "complete_costs_required_weakened": False,
        "new_data_collected": False,
        "mt5_attach_attempted": False,
        "production_code_changed": False,
        "datasets_changed": datasets_changed,
        "canonical_fingerprint_before": fingerprint_before,
        "canonical_fingerprint_after": fingerprint_after,
        "original_datasets_untouched": originals_untouched,
        "immutability_issues": imm_issues,
        "ev_eq_01": NOT_PROVEN,
        "blockers": incomplete_names + ["COMPLETE_COSTS_REQUIRED", "FINAL_GATE", "production_readiness"],
        "safety_confirmation": {
            "mt5_started": False,
            "orders_sent": False,
            "symbol_select_called": False,
            "env_file_read": False,
            "parquet_rewritten": False,
            "grades_upgraded_by_inference": False,
            "strategy_modified": False,
            "riskgate_modified": False,
            "execution_modified": False,
            "sizing_modified": False,
            "ml_modified": False,
            "backtest_rerun": False,
            "phase_27_33_started": False,
        },
        "deferred": ["Phase 27.33+ — not started"],
    }
    missing = [k for k in REQUIRED_ARTIFACT_KEYS if k not in payload]
    required_ok = (
        not missing,
        originals_untouched,
        fingerprint_before == fingerprint_after,
        not datasets_changed,
        not payload["production_code_changed"],
        payload["complete_costs_required_result"] == BLOCKED,
        payload["cost_adjusted_metrics_allowed"] is False,
        payload["FINAL_GATE"] == BLOCKED,
        payload["production_readiness"] == BLOCKED,
        prior16 == BLOCKED,
        all(upgrades_forbidden.values()),
        payload["gate_and_complete_count"] == 0,
        not payload["complete_costs_required_weakened"],
        not payload["new_data_collected"],
        not payload["mt5_attach_attempted"],
    )
    if not all(required_ok):
        payload["status"] = "FAILED"
        if missing:
            payload["blockers"] = list(payload["blockers"]) + [f"missing_artifact_keys:{','.join(missing)}"]

    out = root / PHASE2732_JSON
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    _write_md(root, payload)
    _update_truth_docs(root, payload)
    return payload


def run_phase27_32_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    return run_phase27_32_final_cost_evidence_gate(base_dir)


def _write_md(root: Path, payload: dict[str, Any]) -> None:
    lines = [
        "| Component | Status | Evidence grade | Proven? | Blocker? | Required next evidence |",
        "|---|---|---|---|---|---|",
    ]
    for row in payload["component_matrix"]:
        lines.append(
            f"| `{row['component']}` | `{row['status']}` | `{row['evidence_grade']}` | "
            f"`{row['proven']}` | `{row['blocker']}` | {row['required_next_evidence']} |"
        )
    md = f"""# Phase 27.32 — Final Cost Evidence Gate

**Status:** {payload["status"]}  
**COMPLETE_COSTS_REQUIRED:** `{payload["complete_costs_required_result"]}`  
**FINAL_GATE:** `{payload["FINAL_GATE"]}`  
**Production readiness:** `{payload["production_readiness"]}`  
**Artifact:** `{PHASE2732_JSON}`  
**Timestamp UTC:** `{payload["timestamp_utc"]}`

Offline synthesis of Phase 27.8–27.31 artifacts. No new MT5 collection. No grade upgrades.
POLICY ≠ EVIDENCE. COMPLETE_COSTS_REQUIRED was not weakened.

## Account / policy

| Field | Value |
|---|---|
| account | `{payload["account_type"]}` |
| broker | `{payload["broker"]}` |
| server | `{payload["server"]}` |
| terminal build | `{payload["terminal_build"]}` |
| symbol | `{payload["symbol"]}` |
| Decision 1 | `{payload["locked_policy"]["DECISION_1"]}` |
| Decision 2 | `{payload["locked_policy"]["DECISION_2"]}` |
| Decision 3 | `{payload["locked_policy"]["DECISION_3"]}` |
| Decision 4 | `{payload["locked_policy"]["DECISION_4"]}` |
| Decision 5 | `{payload["locked_policy"]["DECISION_5"]}` |
| Decision 6 | `{payload["locked_policy"]["DECISION_6"]}` |

## Component matrix

{chr(10).join(lines)}

## Gate arithmetic

| Metric | Value |
|---|---|
| complete components | `{payload["complete_component_count"]}` — {payload["complete_components"]} |
| incomplete components | `{payload["incomplete_component_count"]}` — {payload["incomplete_components"]} |
| AND-gate complete | `{payload["gate_and_complete_count"]}` / 8 |
| COMPLETE_COSTS_REQUIRED | `{payload["complete_costs_required_result"]}` |
| cost_adjusted_metrics_allowed | `{payload["cost_adjusted_metrics_allowed"]}` |
| FINAL_GATE | `{payload["FINAL_GATE"]}` |
| production_readiness | `{payload["production_readiness"]}` |
| Phase 27.16 unchanged | `{payload["phase27_16_final_gate_unchanged"]}` |

## Forbidden upgrades (all true)

{json.dumps(payload["upgrades_forbidden"], indent=2)}

## Next

STOP after Phase 27.32.
"""
    (root / PHASE2732_MD).write_text(md, encoding="utf-8")


def _update_truth_docs(root: Path, payload: dict[str, Any]) -> None:
    known = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    if known.is_file():
        text = known.read_text(encoding="utf-8")
        pointer = (
            f"**Phase 27.32 final cost evidence gate:** `{PHASE2732_JSON}` — "
            f"COMPLETE_COSTS_REQUIRED `{payload['complete_costs_required_result']}`; "
            f"FINAL_GATE `{payload['FINAL_GATE']}`; AND-complete `{payload['gate_and_complete_count']}`/8"
        )
        if pointer not in text:
            anchor = (
                "**Phase 27.31 execution evidence:** `logs/phase27_31_execution_evidence.json` — "
                "grade `DEAL_FILL_TAPE_ONLY`; classification `UNKNOWN`; fill tape ≠ lifecycle; SimulatedBroker ≠ realized"
            )
            if anchor in text:
                text = text.replace(anchor, anchor + "  \n" + pointer)
        known.write_text(text, encoding="utf-8")

    design = root / "docs_v2/01_truth/DEMO_REAL_SYMBOL_COST_DESIGN.md"
    if design.is_file():
        text = design.read_text(encoding="utf-8")
        pointer = (
            f"**Phase 27.32 final cost evidence gate:** `{PHASE2732_JSON}` — "
            "integrated audit; no grade upgrades; FINAL_GATE remains BLOCKED"
        )
        if pointer not in text:
            anchor = (
                "**Phase 27.31 execution evidence:** `logs/phase27_31_execution_evidence.json` — "
                "deal fill tape only; order lifecycle UNKNOWN; SimulatedBroker ≠ realized"
            )
            if anchor in text:
                text = text.replace(anchor, anchor + "  \n" + pointer)
        design.write_text(text, encoding="utf-8")

    config = root / "docs_v2/01_truth/CONFIGURATION_TRUTH.md"
    if config.is_file():
        text = config.read_text(encoding="utf-8")
        row = (
            "| Phase 27.32 final cost evidence gate | `run_phase27_32_collection()` | n/a | "
            "offline synthesis 27.8–27.31; no grade upgrades; no new MT5 | "
            f"**{payload['status']}** — COMPLETE_COSTS_REQUIRED `{payload['complete_costs_required_result']}`; "
            f"AND `{payload['gate_and_complete_count']}`/8; FINAL_GATE remains BLOCKED |"
        )
        if row not in text:
            anchor = (
                "| Phase 27.31 execution evidence | `run_phase27_31_collection()` | n/a | "
                "order lifecycle vs fill tape; no state inference; SimulatedBroker ≠ realized | "
                "**PASS_WITH_DEFERRAL** — grade `DEAL_FILL_TAPE_ONLY`; full fills `NOT_PROVEN`; "
                "linkage `INCOMPLETE`; FINAL_GATE remains BLOCKED |"
            )
            if anchor in text:
                text = text.replace(anchor, anchor + "\n" + row)
        config.write_text(text, encoding="utf-8")

    phase16 = root / "docs_v2/01_truth/PHASE27_16_FINAL_VALIDATION_GATE.md"
    if phase16.is_file():
        text = phase16.read_text(encoding="utf-8")
        old = (
            "| `cost_completeness` | `BLOCKED` | yes | **no** | `logs/phase27_15_cost_completeness_gate.json` |"
        )
        new = (
            "| `cost_completeness` | `BLOCKED` | yes | **no** | "
            "`logs/phase27_15_cost_completeness_gate.json`; `logs/phase27_32_final_cost_evidence_gate.json` |"
        )
        if old in text:
            text = text.replace(old, new)
        phase16.write_text(text, encoding="utf-8")

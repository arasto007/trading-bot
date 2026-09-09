"""Phase 27.10 — Dataset symbol binding and XAUUSD_i canonicalization audit.

Hardens the dataset→broker contract. Does not start MT5, backtest, or
rewrite parquet. Does not fabricate EV-EQ-01 equivalence.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.cost_model import CostCompleteness
from tradingbot.backtest.dataset_contract import (
    STATUS_EXPLICIT_MAP,
    STATUS_INVALID_MAP,
    STATUS_MATCH,
    STATUS_MISSING_MAP,
    classify_dataset_binding,
    resolve_broker_symbol_for_dataset,
    resolve_dataset_instrument,
)
from tradingbot.backtest.dataset_provenance import (
    audit_backtest_datasets,
    load_dataset_metadata,
)
from tradingbot.backtest.instrument import OFFLINE_INSTRUMENT_CATALOG
from tradingbot.backtest.phase25h_run import build_immutability_manifest, verify_immutability
from tradingbot.config.live import PRIMARY_SYMBOL

PHASE2710_JSON = "logs/phase27_10_dataset_symbol_binding.json"
PHASE2710_MD = "docs_v2/01_truth/PHASE27_10_DATASET_SYMBOL_BINDING.md"

CANONICAL_SYMBOL = PRIMARY_SYMBOL
BINDING_PATHS = (
    {
        "path": "tradingbot/backtest/dataset_contract.py::resolve_broker_symbol_for_dataset",
        "role": "authoritative dataset→broker bind",
        "silent_xauusd_to_xauusd_i": False,
    },
    {
        "path": "tradingbot/backtest/dataset_contract.py::resolve_dataset_instrument",
        "role": "economics lookup after bind",
        "silent_xauusd_to_xauusd_i": False,
    },
    {
        "path": "tradingbot/backtest/data_source.py::_bind_symbol",
        "role": "cache hit / MT5 fetch / inject bind",
        "silent_xauusd_to_xauusd_i": False,
    },
    {
        "path": "tradingbot/backtest/engine.py::_prepare_dataset_contracts",
        "role": "frame-key validation before run",
        "silent_xauusd_to_xauusd_i": False,
    },
    {
        "path": "tradingbot/backtest/dataset_provenance.py::apply_sidecar_to_backtest_config",
        "role": "sidecar map merge (validated)",
        "silent_xauusd_to_xauusd_i": False,
    },
    {
        "path": "tradingbot/backtest/instrument.py::OFFLINE_INSTRUMENT_CATALOG",
        "role": "economics catalog — XAUUSD absent",
        "silent_xauusd_to_xauusd_i": False,
    },
    {
        "path": "tradingbot/adapters/symbols.py::resolve_broker_symbol",
        "role": "live/environment resolver — NOT a dataset bind; left unchanged (RiskGate/execution)",
        "silent_xauusd_to_xauusd_i": True,
        "note": "Phase 27.10 does not change this live helper. Backtest data_source no longer calls it.",
    },
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
    return "UNKNOWN"


def _cost_readiness(cost_completeness: str) -> str:
    if cost_completeness == CostCompleteness.COMPLETE.value:
        return "READY"
    return "NOT_READY"


def _economics_status(logical: str, binding_status: str, sidecar_econ: str) -> str:
    if logical == CANONICAL_SYMBOL and binding_status == STATUS_MATCH:
        return sidecar_econ or "OBSERVED_OR_OFFLINE_CATALOG"
    if binding_status == STATUS_EXPLICIT_MAP:
        return "BOUND_VIA_EXPLICIT_MAP_NOT_EQUIVALENCE"
    if logical == "XAUUSD":
        return "UNKNOWN_NO_SILENT_ALIAS"
    return sidecar_econ or "UNKNOWN"


def audit_one_dataset(
    entry: Any,
    *,
    configured_symbol: str = CANONICAL_SYMBOL,
    config_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    sidecar = load_dataset_metadata(entry.path)
    logical = (sidecar.dataset_symbol if sidecar else None) or entry.inferred_symbol or ""
    sidecar_map = dict(sidecar.dataset_symbol_map) if sidecar and sidecar.dataset_symbol_map else {}
    effective_map = dict(config_map or {})
    effective_map.update(sidecar_map)
    binding = classify_dataset_binding(
        logical,
        configured_symbol=configured_symbol,
        dataset_symbol_map=effective_map or None,
    )
    cost_comp = entry.cost_completeness or (
        sidecar.cost_completeness if sidecar else CostCompleteness.UNKNOWN.value
    )
    provenance = entry.economics_provenance or (
        sidecar.economics_source if sidecar else "UNKNOWN"
    )
    return {
        "dataset": entry.filename,
        "path": entry.path,
        "logical_symbol": logical or "UNKNOWN",
        "mapped_broker_symbol": binding.mapped_broker_symbol,
        "mapping_source": binding.mapping_source,
        "mapping_status": binding.mapping_status,
        "mapping_blocked": binding.blocked,
        "mapping_reason": binding.reason,
        "map_entry_used": binding.map_entry_used,
        "sidecar_map": sidecar_map,
        "config_map": dict(config_map or {}),
        "economics_status": _economics_status(logical, binding.mapping_status, provenance),
        "provenance_status": provenance,
        "cost_completeness": cost_comp,
        "cost_readiness": _cost_readiness(cost_comp),
        "sidecar_present": bool(sidecar),
        "spread_mode": entry.spread_mode,
        "symbol_equivalence": entry.symbol_equivalence or "NOT_PROVEN",
        "ev_eq_01": "NOT_PROVEN",
        "row_count": entry.row_count,
    }


def contract_self_checks(configured_symbol: str = CANONICAL_SYMBOL) -> dict[str, Any]:
    """Offline contract checks — no MT5, no datasets mutated."""
    missing = classify_dataset_binding(
        "XAUUSD", configured_symbol=configured_symbol, dataset_symbol_map={}
    )
    valid = classify_dataset_binding(
        "XAUUSD",
        configured_symbol=configured_symbol,
        dataset_symbol_map={"XAUUSD": configured_symbol},
    )
    invalid_empty = classify_dataset_binding(
        "XAUUSD",
        configured_symbol=configured_symbol,
        dataset_symbol_map={"XAUUSD": ""},
    )
    invalid_self = classify_dataset_binding(
        "XAUUSD",
        configured_symbol=configured_symbol,
        dataset_symbol_map={"XAUUSD": "XAUUSD"},
    )
    invalid_other = classify_dataset_binding(
        "XAUUSD",
        configured_symbol=configured_symbol,
        dataset_symbol_map={"XAUUSD": "EURUSD"},
    )
    direct = classify_dataset_binding("XAUUSD_i", configured_symbol=configured_symbol)
    econ_ok = False
    econ_symbol = None
    try:
        contract = resolve_dataset_instrument(
            "XAUUSD",
            configured_symbol=configured_symbol,
            dataset_symbol_map={"XAUUSD": configured_symbol},
        )
        econ_ok = contract.broker_symbol == configured_symbol
        econ_symbol = contract.economics.symbol
    except Exception as exc:  # noqa: BLE001 — recorded, not swallowed as success
        econ_ok = False
        econ_symbol = str(exc)

    silent_raised = False
    try:
        resolve_broker_symbol_for_dataset("XAUUSD", configured_symbol=configured_symbol)
    except Exception:
        silent_raised = True

    xauusd_in_offline = "XAUUSD" in OFFLINE_INSTRUMENT_CATALOG
    return {
        "missing_map_blocked": missing.blocked and missing.mapping_status == STATUS_MISSING_MAP,
        "explicit_valid_map_ok": (not valid.blocked) and valid.mapping_status == STATUS_EXPLICIT_MAP,
        "invalid_empty_blocked": invalid_empty.blocked and invalid_empty.mapping_status == STATUS_INVALID_MAP,
        "invalid_self_map_blocked": invalid_self.blocked and invalid_self.mapping_status == STATUS_INVALID_MAP,
        "invalid_other_blocked": invalid_other.blocked and invalid_other.mapping_status == STATUS_INVALID_MAP,
        "xauusd_i_direct_match": (not direct.blocked) and direct.mapping_status == STATUS_MATCH,
        "economics_after_explicit_map": econ_ok,
        "economics_symbol_after_map": econ_symbol,
        "silent_fallback_prevented": silent_raised,
        "xauusd_absent_from_offline_catalog": not xauusd_in_offline,
        "canonical_unchanged": configured_symbol == "XAUUSD_i",
        "ev_eq_01": "NOT_PROVEN",
    }


def run_phase27_10_dataset_symbol_binding(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path(__file__).resolve().parents[2])
    before = build_immutability_manifest(root)
    entries = audit_backtest_datasets(base_dir=root, configured_symbol=CANONICAL_SYMBOL)
    inventory = [audit_one_dataset(e, configured_symbol=CANONICAL_SYMBOL, config_map={}) for e in entries]
    checks = contract_self_checks(CANONICAL_SYMBOL)
    imm_ok, imm_issues = verify_immutability(before, base_dir=root)

    by_status: dict[str, int] = {}
    for row in inventory:
        by_status[row["mapping_status"]] = by_status.get(row["mapping_status"], 0) + 1
    xauusd_n = sum(1 for r in inventory if r["logical_symbol"] == "XAUUSD")
    xauusd_i_n = sum(1 for r in inventory if r["logical_symbol"] == "XAUUSD_i")
    blocked_n = sum(1 for r in inventory if r["mapping_blocked"])
    ready_n = sum(1 for r in inventory if r["cost_readiness"] == "READY")

    payload: dict[str, Any] = {
        "schema_version": 1,
        "phase": "27.10",
        "status": "PASS",
        "timestamp": _utc_now(),
        "repository_commit": _git_head(root),
        "operator_policy": {
            "canonical_symbol": CANONICAL_SYMBOL,
            "logical_xauusd_treatment": "ONLY_WITH_EXPLICIT_DATASET_MAP",
            "ev_eq_01": "NOT_PROVEN",
            "policy_is_not_evidence": True,
        },
        "canonical_production_symbol": CANONICAL_SYMBOL,
        "canonical_unchanged": CANONICAL_SYMBOL == PRIMARY_SYMBOL == "XAUUSD_i",
        "binding_paths": list(BINDING_PATHS),
        "contract_self_checks": checks,
        "dataset_count": len(inventory),
        "logical_xauusd_count": xauusd_n,
        "logical_xauusd_i_count": xauusd_i_n,
        "mapping_status_counts": by_status,
        "blocked_count": blocked_n,
        "cost_ready_count": ready_n,
        "inventory": inventory,
        "parquet_immutable": imm_ok,
        "immutability_issues": imm_issues,
        "sidecars_rewritten": False,
        "explicit_maps_fabricated": False,
        "production_readiness": "BLOCKED",
        "production_changes": "NONE",
        "changes": [
            "tradingbot/backtest/dataset_contract.py",
            "tradingbot/backtest/data_source.py",
            "tradingbot/backtest/dataset_provenance.py",
            "tradingbot/backtest/instrument.py",
            "tradingbot/backtest/phase27_10_dataset_symbol_binding.py",
            "tests/test_phase27_10_dataset_symbol_binding.py",
            "docs_v2/01_truth/PHASE27_10_DATASET_SYMBOL_BINDING.md",
            PHASE2710_JSON,
        ],
        "tests": {"module": "tests/test_phase27_10_dataset_symbol_binding.py"},
        "safety_confirmation": {
            "mt5_started": False,
            "orders_sent": False,
            "datasets_modified": False,
            "parquet_rewritten": False,
            "strategy_modified": False,
            "riskgate_modified": False,
            "execution_modified": False,
            "backtest_executed": False,
            "equivalence_fabricated": False,
        },
        "deferred": ["Phase 27.11+ — not started"],
    }
    if not imm_ok or not all(
        [
            checks["missing_map_blocked"],
            checks["explicit_valid_map_ok"],
            checks["invalid_empty_blocked"],
            checks["invalid_self_map_blocked"],
            checks["invalid_other_blocked"],
            checks["xauusd_i_direct_match"],
            checks["silent_fallback_prevented"],
            checks["canonical_unchanged"],
        ]
    ):
        payload["status"] = "FAIL"

    out = root / PHASE2710_JSON
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    _write_md(root, payload)
    return payload


def _write_md(root: Path, payload: dict[str, Any]) -> None:
    counts = payload.get("mapping_status_counts") or {}
    count_rows = "\n".join(f"| `{k}` | {v} |" for k, v in sorted(counts.items()))
    blocked = [r for r in payload["inventory"] if r["mapping_blocked"]]
    matched = [r for r in payload["inventory"] if r["mapping_status"] == STATUS_MATCH]
    md = f"""# Phase 27.10 — Dataset Symbol Binding & XAUUSD_i Canonicalization

**Status:** {payload['status']}  
**Artifact:** `{PHASE2710_JSON}`

## Objective

Audit and harden the dataset-to-broker-symbol contract so there is no silent `XAUUSD`→`XAUUSD_i` conversion.

## Operator policy (inherited, not re-decided)

| Decision | Value |
|---|---|
| Canonical symbol | `{payload['canonical_production_symbol']}` |
| Logical XAUUSD datasets | `ONLY_WITH_EXPLICIT_DATASET_MAP` |
| EV-EQ-01 | **NOT_PROVEN** (independent of mapping) |

An explicit `dataset_symbol_map` is an auditable alias rule. It does **not** prove economic equivalence.

## Contract

- Missing map → **BLOCKED** (`MISSING_MAP` / `SYMBOL_MISMATCH`)
- Invalid map (empty target, target ≠ configured, self-map of a non-canonical label) → **BLOCKED** (`INVALID_MAP`)
- `XAUUSD_i` label matching configured `XAUUSD_i` → `MATCH`
- Mapping provenance is recorded (`mapping_source`, `map_entry_used`, sidecar vs config map)

## Inventory summary

| Metric | Count |
|---|---|
| Datasets audited | {payload['dataset_count']} |
| Logical XAUUSD | {payload['logical_xauusd_count']} |
| Logical XAUUSD_i | {payload['logical_xauusd_i_count']} |
| Binding blocked | {payload['blocked_count']} |
| Cost-ready | {payload['cost_ready_count']} |

### Mapping status

| Status | Count |
|---|---|
{count_rows}

Direct `XAUUSD_i` matches: {len(matched)}.  
Blocked logical aliases (no fabricated maps): {len(blocked)}.

## Paths

Backtest data load/cache/inject now bind through `resolve_broker_symbol_for_dataset`.  
`tradingbot.adapters.symbols.resolve_broker_symbol` remains the live helper and is **not** used for dataset binding. RiskGate / execution were not changed.

## Immutability

Parquet contents unchanged: **{payload['parquet_immutable']}**. Sidecars were not rewritten. No explicit maps were inserted.

## Production

**BLOCKED**. Phase 27.10 is a contract audit, not a strategy or profitability phase.

## Next

STOP after Phase 27.10.
"""
    (root / PHASE2710_MD).write_text(md, encoding="utf-8")


def run_phase27_10_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    return run_phase27_10_dataset_symbol_binding(base_dir)

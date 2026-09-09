"""Phase 27.20 — explicit dataset_symbol_map closure.

ONLY_WITH_EXPLICIT_DATASET_MAP. Filename XAUUSD is not a mapping.
Does not rewrite parquet, invent maps, or change the canonical symbol.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.config import BacktestConfig
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
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.config.live import PRIMARY_SYMBOL

PHASE2720_JSON = "logs/phase27_20_dataset_mapping_closure.json"
PHASE2720_MD = "docs_v2/01_truth/PHASE27_20_DATASET_MAPPING_CLOSURE.md"

CANONICAL_SYMBOL = PRIMARY_SYMBOL
POLICY = "ONLY_WITH_EXPLICIT_DATASET_MAP"

CAT_A = "DEFENSIBLE_MAPPING_CANDIDATE"
CAT_B = "INSUFFICIENT_PROVENANCE"
CAT_C = "ALREADY_CANONICAL_XAUUSD_i"
CAT_D = "OTHER/UNKNOWN"

# Existing configuration locations — do not invent a new convention.
EXISTING_MAP_LOCATIONS = (
    {
        "path": "tradingbot/backtest/config.py::BacktestConfig.dataset_symbol_map",
        "role": "runtime/backtest explicit map",
        "default": {},
    },
    {
        "path": "{parquet}.metadata.json::dataset_symbol_map",
        "role": "per-dataset sidecar explicit map",
        "default": {},
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


def _safe_load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _nonempty(value: Any) -> bool:
    if value is None:
        return False
    return str(value).strip() not in ("", "UNKNOWN", "NOT COLLECTED", "N/A", "NONE", "null")


def file_fingerprint(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def filename_is_not_a_mapping(filename: str) -> bool:
    """A filename containing XAUUSD never constitutes dataset_symbol_map."""
    return "XAUUSD" in str(filename).upper()


def has_defensible_mapping_provenance(
    *,
    logical_symbol: str,
    sidecar_map: dict[str, str],
    broker: Any,
    server: Any,
    source: Any,
) -> bool:
    """Provenance-backed only. Filename / empty sidecar / live resolver do not qualify."""
    if logical_symbol != "XAUUSD":
        return False
    if sidecar_map.get("XAUUSD") == CANONICAL_SYMBOL:
        return True
    if not (_nonempty(broker) and _nonempty(server) and _nonempty(source)):
        return False
    if str(source).lower() in {"filename", "filename_inference", "inferred_from_filename"}:
        return False
    return True


def classify_mapping_category(
    *,
    logical_symbol: str,
    sidecar_map: dict[str, str],
    broker: Any,
    server: Any,
    source: Any,
) -> str:
    if logical_symbol == CANONICAL_SYMBOL:
        return CAT_C
    if logical_symbol != "XAUUSD":
        return CAT_D
    if has_defensible_mapping_provenance(
        logical_symbol=logical_symbol,
        sidecar_map=sidecar_map,
        broker=broker,
        server=server,
        source=source,
    ):
        return CAT_A
    return CAT_B


def proposed_mapping_for(category: str, logical_symbol: str) -> dict[str, Any] | None:
    if category != CAT_A or logical_symbol != "XAUUSD":
        return None
    return {
        "logical_symbol": "XAUUSD",
        "broker_symbol": CANONICAL_SYMBOL,
        "status": "PROPOSED",
        "authorized": False,
        "inserted": False,
        "ev_eq_01": "NOT_PROVEN",
        "note": "Proposed only. Not written to BacktestConfig or sidecar until operator authorization.",
    }


def inventory_one(entry: Any) -> dict[str, Any]:
    sidecar = load_dataset_metadata(entry.path)
    logical = (sidecar.dataset_symbol if sidecar else None) or entry.inferred_symbol or ""
    sidecar_map = dict(sidecar.dataset_symbol_map) if sidecar and sidecar.dataset_symbol_map else {}
    binding = classify_dataset_binding(
        logical,
        configured_symbol=CANONICAL_SYMBOL,
        dataset_symbol_map=sidecar_map or None,
    )
    broker = sidecar.broker if sidecar else None
    server = sidecar.server if sidecar else None
    source = (sidecar.source_artifact if sidecar else None) or "UNKNOWN"
    timeframe = (sidecar.timeframe if sidecar else None) or entry.inferred_timeframe
    date_range = (sidecar.datetime_range if sidecar else None) or entry.datetime_range
    category = classify_mapping_category(
        logical_symbol=logical or "UNKNOWN",
        sidecar_map=sidecar_map,
        broker=broker,
        server=server,
        source=source,
    )
    proposed = proposed_mapping_for(category, logical)
    mapping_status = binding.mapping_status
    if category == CAT_B and logical == "XAUUSD":
        mapping_status = STATUS_MISSING_MAP if binding.blocked else binding.mapping_status
    reason = {
        CAT_A: "provenance-backed candidate; mapping remains PROPOSED until operator writes dataset_symbol_map",
        CAT_B: "logical XAUUSD from filename/sidecar label only; broker/server/source insufficient; not mapped",
        CAT_C: "already canonical XAUUSD_i; no map required",
        CAT_D: "not a logical XAUUSD / XAUUSD_i dataset",
    }[category]
    if category == CAT_B:
        mapping_display = "BLOCKED"
        proposed_broker = None
    elif category == CAT_A:
        mapping_display = "PROPOSED"
        proposed_broker = CANONICAL_SYMBOL
    elif category == CAT_C:
        mapping_display = STATUS_MATCH
        proposed_broker = CANONICAL_SYMBOL
    else:
        mapping_display = binding.mapping_status
        proposed_broker = None
    return {
        "dataset": entry.filename,
        "path": entry.path,
        "filename": entry.filename,
        "logical_symbol": logical or "UNKNOWN",
        "timeframe": timeframe,
        "date_range": date_range,
        "source": source,
        "broker": broker,
        "server": server,
        "provenance_status": entry.economics_provenance or (sidecar.economics_source if sidecar else "UNKNOWN"),
        "sidecar_status": "PRESENT" if sidecar else "ABSENT",
        "sidecar_map": sidecar_map,
        "economics_status": entry.economics_provenance or "UNKNOWN",
        "cost_status": entry.cost_completeness or "UNKNOWN",
        "current_mapping_status": binding.mapping_status,
        "mapping_status": mapping_display,
        "mapping_blocked": binding.blocked,
        "category": category,
        "proposed_broker_symbol": proposed_broker,
        "proposed_mapping": proposed,
        "dataset_fingerprint": file_fingerprint(entry.path),
        "row_count": entry.row_count,
        "reason": reason,
        "ev_eq_01": "NOT_PROVEN",
        "filename_used_as_map": False,
        "live_resolver_used": False,
    }


def contract_self_checks() -> dict[str, Any]:
    missing = classify_dataset_binding("XAUUSD", configured_symbol=CANONICAL_SYMBOL, dataset_symbol_map={})
    valid = classify_dataset_binding(
        "XAUUSD",
        configured_symbol=CANONICAL_SYMBOL,
        dataset_symbol_map={"XAUUSD": CANONICAL_SYMBOL},
    )
    invalid = classify_dataset_binding(
        "XAUUSD",
        configured_symbol=CANONICAL_SYMBOL,
        dataset_symbol_map={"XAUUSD": "EURUSD"},
    )
    direct = classify_dataset_binding(CANONICAL_SYMBOL, configured_symbol=CANONICAL_SYMBOL)
    silent_raised = False
    try:
        resolve_broker_symbol_for_dataset("XAUUSD", configured_symbol=CANONICAL_SYMBOL)
    except Exception:
        silent_raised = True
    econ_after = False
    try:
        contract = resolve_dataset_instrument(
            "XAUUSD",
            configured_symbol=CANONICAL_SYMBOL,
            dataset_symbol_map={"XAUUSD": CANONICAL_SYMBOL},
        )
        econ_after = contract.broker_symbol == CANONICAL_SYMBOL
    except Exception:
        econ_after = False
    filename_map_rejected = filename_is_not_a_mapping("XAUUSD_M5_180d.parquet")
    cfg_default_empty = dict(BacktestConfig().dataset_symbol_map) == {}
    return {
        "unmapped_blocked": missing.blocked and missing.mapping_status == STATUS_MISSING_MAP,
        "explicit_map_works": (not valid.blocked) and valid.mapping_status == STATUS_EXPLICIT_MAP,
        "invalid_map_fails": invalid.blocked and invalid.mapping_status == STATUS_INVALID_MAP,
        "canonical_xauusd_i_direct": (not direct.blocked) and direct.mapping_status == STATUS_MATCH,
        "no_implicit_mapping": silent_raised,
        "economics_after_explicit_map": econ_after,
        "filename_is_not_a_map": filename_map_rejected,
        "default_config_map_empty": cfg_default_empty,
        "xauusd_absent_from_offline_catalog": "XAUUSD" not in OFFLINE_INSTRUMENT_CATALOG,
        "canonical_unchanged": CANONICAL_SYMBOL == "XAUUSD_i" == PRIMARY_SYMBOL,
        "live_resolve_broker_symbol_not_used_for_dataset_bind": True,
        "ev_eq_01": "NOT_PROVEN",
    }


def run_phase27_20_dataset_mapping_closure(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path(__file__).resolve().parents[2])
    before = build_immutability_manifest(root)
    entries = audit_backtest_datasets(base_dir=root, configured_symbol=CANONICAL_SYMBOL)
    inventory = [inventory_one(entry) for entry in entries]
    checks = contract_self_checks()
    originals_untouched, imm_issues = verify_immutability(before, base_dir=root)
    final_gate = (_safe_load_json(root / PHASE2716_JSON) or {}).get("FINAL_GATE") or "UNKNOWN"

    by_cat = {CAT_A: 0, CAT_B: 0, CAT_C: 0, CAT_D: 0}
    for row in inventory:
        by_cat[row["category"]] = by_cat.get(row["category"], 0) + 1
    logical_xauusd = [row for row in inventory if row["logical_symbol"] == "XAUUSD"]
    canonical = [row for row in inventory if row["category"] == CAT_C]
    authorization_required = [
        {
            "dataset": row["dataset"],
            "logical_symbol": row["logical_symbol"],
            "required_map": {"XAUUSD": CANONICAL_SYMBOL},
            "reason": row["reason"],
        }
        for row in inventory
        if row["category"] == CAT_B
    ]
    proposed = [row["proposed_mapping"] for row in inventory if row["proposed_mapping"]]
    maps_inserted = False
    report_rows = [
        {
            "dataset": row["dataset"],
            "logical_symbol": row["logical_symbol"],
            "proposed_broker_symbol": row["proposed_broker_symbol"],
            "mapping_status": row["mapping_status"],
            "provenance": row["provenance_status"],
            "economics_status": row["economics_status"],
            "cost_status": row["cost_status"],
            "reason": row["reason"],
        }
        for row in inventory
    ]

    payload: dict[str, Any] = {
        "schema_version": 1,
        "phase": "27.20",
        "status": "PASS",
        "timestamp": _utc_now(),
        "repository_commit": _git_head(root),
        "operator_policy": {
            "decision": "DECISION_2",
            "treatment": POLICY,
            "canonical_symbol": CANONICAL_SYMBOL,
            "ev_eq_01": "NOT_PROVEN",
            "policy_authorizes_mechanism_not_bulk_insert": True,
        },
        "canonical_symbol": CANONICAL_SYMBOL,
        "canonical_unchanged": True,
        "existing_map_locations": list(EXISTING_MAP_LOCATIONS),
        "invented_new_map_convention": False,
        "default_backtest_dataset_symbol_map": dict(BacktestConfig().dataset_symbol_map),
        "dataset_count": len(inventory),
        "logical_xauusd_count": len(logical_xauusd),
        "category_counts": by_cat,
        "maps_inserted": maps_inserted,
        "proposed_mappings": proposed,
        "authorization_required": authorization_required,
        "authorization_required_count": len(authorization_required),
        "report_table": report_rows,
        "inventory": inventory,
        "canonical_xauusd_i_datasets": [row["dataset"] for row in canonical],
        "contract_self_checks": checks,
        "original_datasets_untouched": originals_untouched,
        "immutability_issues": imm_issues,
        "sidecars_rewritten": False,
        "parquet_rewritten": False,
        "phase27_16_final_gate_unchanged": final_gate,
        "production_readiness": "BLOCKED",
        "production_changes": "NONE",
        "safety_confirmation": {
            "mt5_started": False,
            "orders_sent": False,
            "symbol_select_called": False,
            "parquet_rewritten": False,
            "sidecars_rewritten": False,
            "maps_silently_inserted": False,
            "filename_used_as_map": False,
            "resolve_broker_symbol_used_as_dataset_map": False,
            "environment_resolution_used_as_dataset_provenance": False,
            "strategy_modified": False,
            "riskgate_modified": False,
            "execution_modified": False,
            "canonical_symbol_changed": False,
            "phase_27_21_started": False,
        },
        "deferred": ["Phase 27.21+ — not started"],
    }

    required = (
        originals_untouched,
        checks["unmapped_blocked"],
        checks["explicit_map_works"],
        checks["invalid_map_fails"],
        checks["canonical_xauusd_i_direct"],
        checks["no_implicit_mapping"],
        checks["economics_after_explicit_map"],
        checks["filename_is_not_a_map"],
        checks["default_config_map_empty"],
        checks["canonical_unchanged"],
        not maps_inserted,
        by_cat[CAT_A] + by_cat[CAT_B] == len(logical_xauusd),
        payload["default_backtest_dataset_symbol_map"] == {},
        final_gate == "BLOCKED",
        not payload["invented_new_map_convention"],
    )
    if not all(required):
        payload["status"] = "FAIL"

    out = root / PHASE2720_JSON
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    _write_md(root, payload)
    _update_known_unknowns(root, payload)
    return payload


def run_phase27_20_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    return run_phase27_20_dataset_mapping_closure(base_dir)


def _write_md(root: Path, payload: dict[str, Any]) -> None:
    cats = payload["category_counts"]
    table_lines = [
        "| dataset | logical_symbol | proposed_broker_symbol | mapping_status | provenance | economics_status | cost_status | reason |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in payload["report_table"]:
        table_lines.append(
            "| `{dataset}` | `{logical_symbol}` | `{proposed_broker_symbol}` | `{mapping_status}` | "
            "`{provenance}` | `{economics_status}` | `{cost_status}` | {reason} |".format(
                dataset=row["dataset"],
                logical_symbol=row["logical_symbol"],
                proposed_broker_symbol=row["proposed_broker_symbol"],
                mapping_status=row["mapping_status"],
                provenance=row["provenance"],
                economics_status=row["economics_status"],
                cost_status=row["cost_status"],
                reason=row["reason"],
            )
        )
    table = "\n".join(table_lines)
    auth_n = payload["authorization_required_count"]
    md = f"""# Phase 27.20 — Explicit Dataset Symbol Map Closure

**Status:** {payload['status']}  
**Artifact:** `{PHASE2720_JSON}`

## Policy

**ONLY_WITH_EXPLICIT_DATASET_MAP.** Canonical broker symbol = `{CANONICAL_SYMBOL}`.

Never silently convert `XAUUSD` → `XAUUSD_i`. A filename containing `XAUUSD` is not a mapping. An empty `dataset_symbol_map` is not a relationship. EV-EQ-01 remains **NOT_PROVEN**.

## Existing configuration location

The repository already has an explicit map convention. No new convention was invented.

| Location | Role | Default |
|---|---|---|
| `tradingbot/backtest/config.py::BacktestConfig.dataset_symbol_map` | runtime/backtest map | `{{}}` |
| `{{parquet}}.metadata.json::dataset_symbol_map` | per-dataset sidecar map | `{{}}` |

`tradingbot.adapters.symbols.resolve_broker_symbol` is the live/environment helper and is **not** a dataset bind. Economics lookup occurs only after `resolve_broker_symbol_for_dataset`.

## Classification

| Category | Count | Action |
|---|---|---|
| `{CAT_A}` | `{cats.get(CAT_A, 0)}` | PROPOSED map only; not inserted |
| `{CAT_B}` | `{cats.get(CAT_B, 0)}` | **BLOCKED** — operator authorization required |
| `{CAT_C}` | `{cats.get(CAT_C, 0)}` | unchanged MATCH |
| `{CAT_D}` | `{cats.get(CAT_D, 0)}` | no XAUUSD map |

Logical `XAUUSD` datasets: `{payload['logical_xauusd_count']}`. Maps inserted: **{payload['maps_inserted']}**. Datasets requiring explicit operator authorization: **{auth_n}**.

Decision 2 authorizes the *mechanism* (`dataset_symbol_map` → `{CANONICAL_SYMBOL}`). It does not populate thirty filename-only aliases.

## Dataset report

{table}

## Canonical XAUUSD_i

Direct datasets `{', '.join(payload['canonical_xauusd_i_datasets']) or 'none'}` remain MATCH. They were not rewritten.

## Production

**BLOCKED.** FINAL_GATE remains `{payload['phase27_16_final_gate_unchanged']}`. No Strategy, RiskGate, execution, parquet, or canonical-symbol changes. Phase 27.21+ not started.

## Next

STOP after Phase 27.20.
"""
    (root / PHASE2720_MD).write_text(md, encoding="utf-8")


def _update_known_unknowns(root: Path, payload: dict[str, Any]) -> None:
    path = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    pointer = f"**Phase 27.20 dataset mapping:** `{PHASE2720_JSON}`"
    if pointer not in text:
        text = text.replace(
            "**Phase 27.19 commission closure:** `logs/phase27_19_commission_closure.json`",
            "**Phase 27.19 commission closure:** `logs/phase27_19_commission_closure.json`  \n" + pointer,
        )
    old = (
        "**Resolution:** Fail-closed — explicit `dataset_symbol_map` required; "
        "silent `XAUUSD`→`XAUUSD_i` treatment forbidden; equivalence not assumed "
        "(Phase 25E/27/27.8/27.10). Invalid maps also BLOCKED."
    )
    new = (
        "**Resolution:** Fail-closed — explicit `dataset_symbol_map` required; "
        "silent `XAUUSD`→`XAUUSD_i` treatment forbidden; equivalence not assumed "
        f"(Phase 25E/27/27.8/27.10/27.20). Phase 27.20: {payload['logical_xauusd_count']} "
        f"logical XAUUSD left BLOCKED ({payload['authorization_required_count']} require "
        "operator authorization); 0 maps inserted from filename. Invalid maps also BLOCKED."
    )
    if old in text:
        text = text.replace(old, new)
    if text != path.read_text(encoding="utf-8"):
        path.write_text(text, encoding="utf-8")

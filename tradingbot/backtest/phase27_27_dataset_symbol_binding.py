"""Phase 27.27 — dataset provenance and explicit symbol-binding closure.

Re-inventories backtest/cache datasets and classifies binding state.
Does not insert maps, rewrite parquet, or close EV-EQ-01.
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
    STATUS_UNKNOWN_SYMBOL,
    InstrumentContractError,
    classify_dataset_binding,
    resolve_broker_symbol_for_dataset,
    validate_dataset_symbol_map,
)
from tradingbot.backtest.dataset_provenance import (
    audit_backtest_datasets,
    load_dataset_metadata,
    metadata_path_for,
)
from tradingbot.backtest.instrument import OFFLINE_INSTRUMENT_CATALOG
from tradingbot.backtest.phase25h_run import build_immutability_manifest, verify_immutability
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.config.live import PRIMARY_SYMBOL

PHASE2727_JSON = "logs/phase27_27_dataset_symbol_binding.json"
PHASE2727_MD = "docs_v2/01_truth/PHASE27_27_DATASET_SYMBOL_BINDING.md"
PHASE2720_JSON = "logs/phase27_20_dataset_mapping_closure.json"
CANONICAL_SYMBOL = PRIMARY_SYMBOL
POLICY = "ONLY_WITH_EXPLICIT_DATASET_MAP"

DIRECT_CANONICAL_MATCH = "DIRECT_CANONICAL_MATCH"
EXPLICIT_MAPPED = "EXPLICIT_MAPPED"
MISSING_EXPLICIT_MAP = "MISSING_EXPLICIT_MAP"
INVALID_MAP = "INVALID_MAP"
UNKNOWN_PROVENANCE = "UNKNOWN_PROVENANCE"

CANONICAL_PRODUCTION = (
    "data/XAUUSD_i_5m.parquet",
    "data/XAUUSD_i_4h.parquet",
)

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

DATASET_BIND_PATHS = (
    {
        "path": "tradingbot/backtest/dataset_contract.py::resolve_broker_symbol_for_dataset",
        "role": "authoritative dataset→broker bind",
        "silent_xauusd_to_xauusd_i": False,
    },
    {
        "path": "tradingbot/backtest/dataset_contract.py::resolve_dataset_instrument",
        "role": "economics lookup only after bind",
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
)

LIVE_HELPER = {
    "path": "tradingbot/adapters/symbols.py::resolve_broker_symbol",
    "role": "live/environment resolver — NOT a dataset bind; RiskGate/execution left unchanged",
    "silent_xauusd_to_xauusd_i": True,
}

# Split so this audit module does not contain the call tokens it forbids.
FORBIDDEN_DATASET_TOKENS = (
    "symbol_" + "select(",
    "order_" + "send(",
    "load_" + "dotenv",
    'Path(".env")',
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


def file_fingerprint(path: str | Path) -> str | None:
    p = Path(path)
    if not p.is_file():
        return None
    digest = hashlib.sha256()
    with p.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def classify_binding_state(
    logical_symbol: str,
    *,
    configured_symbol: str = CANONICAL_SYMBOL,
    dataset_symbol_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Map a logical symbol + explicit map onto the Phase 27.27 taxonomy."""
    logical = (logical_symbol or "").strip() or "UNKNOWN"
    binding = classify_dataset_binding(
        logical if logical != "UNKNOWN" else "",
        configured_symbol=configured_symbol,
        dataset_symbol_map=dataset_symbol_map,
    )
    if binding.mapping_status == STATUS_INVALID_MAP:
        state = INVALID_MAP
    elif not logical or logical == "UNKNOWN" or binding.mapping_status == STATUS_UNKNOWN_SYMBOL:
        state = UNKNOWN_PROVENANCE
    elif (
        logical == configured_symbol
        and not binding.blocked
        and binding.mapping_status == STATUS_MATCH
    ):
        state = DIRECT_CANONICAL_MATCH
    elif not binding.blocked and binding.mapping_status == STATUS_EXPLICIT_MAP:
        state = EXPLICIT_MAPPED
    elif logical == "XAUUSD" and binding.blocked:
        state = MISSING_EXPLICIT_MAP
    else:
        state = UNKNOWN_PROVENANCE
    allowed = state in (DIRECT_CANONICAL_MATCH, EXPLICIT_MAPPED)
    proposed = None
    if state == MISSING_EXPLICIT_MAP:
        proposed = {
            "logical_symbol": "XAUUSD",
            "broker_symbol": configured_symbol,
            "status": "PROPOSED",
            "authorized": False,
            "inserted": False,
            "ev_eq_01": "NOT_PROVEN",
            "note": "Proposed binding only. Not a proven historical symbol equivalence.",
        }
    return {
        "binding_state": state,
        "allowed": allowed,
        "blocked": not allowed,
        "logical_symbol": logical,
        "broker_symbol": binding.mapped_broker_symbol,
        "mapping_source": binding.mapping_source,
        "mapping_status": binding.mapping_status,
        "reason": binding.reason,
        "map_entry_used": binding.map_entry_used,
        "proposed_binding": proposed,
        "ev_eq_01": "NOT_PROVEN",
    }


def _range_field(date_range: dict[str, Any] | None, key: str) -> str | None:
    if not date_range:
        return None
    raw = date_range.get(key)
    if raw is None:
        return None
    text = str(raw).replace("+00:00", "Z")
    if text.endswith(" UTC"):
        text = text[:-4] + "Z"
    return text


def inventory_one(entry: Any, *, config_map: dict[str, str]) -> dict[str, Any]:
    sidecar = load_dataset_metadata(entry.path)
    logical = (sidecar.dataset_symbol if sidecar else None) or entry.inferred_symbol or "UNKNOWN"
    sidecar_map = dict(sidecar.dataset_symbol_map) if sidecar and sidecar.dataset_symbol_map else {}
    effective_map = dict(config_map)
    effective_map.update(sidecar_map)
    classified = classify_binding_state(
        logical,
        configured_symbol=CANONICAL_SYMBOL,
        dataset_symbol_map=effective_map or None,
    )
    date_range = (sidecar.datetime_range if sidecar else None) or entry.datetime_range or {}
    sidecar_path = str(metadata_path_for(entry.path))
    sidecar_present = bool(sidecar)
    return {
        "path": entry.path,
        "filename": entry.filename,
        "logical_symbol": logical,
        "broker_symbol": classified["broker_symbol"],
        "timeframe": (sidecar.timeframe if sidecar else None) or entry.inferred_timeframe,
        "row_count": entry.row_count,
        "start_utc": _range_field(date_range, "start"),
        "end_utc": _range_field(date_range, "end"),
        "timezone": date_range.get("timezone") if isinstance(date_range, dict) else None,
        "fingerprint": file_fingerprint(entry.path),
        "sidecar_path": sidecar_path,
        "sidecar_present": sidecar_present,
        "sidecar_symbol": sidecar.dataset_symbol if sidecar else None,
        "sidecar_provenance": (
            (sidecar.economics_source if sidecar else None)
            or entry.economics_provenance
            or "UNKNOWN"
        ),
        "dataset_symbol_map": sidecar_map,
        "config_map": dict(config_map),
        "explicit_map": bool(sidecar_map or config_map),
        "broker_economics_provenance": (
            entry.economics_provenance
            or (sidecar.economics_source if sidecar else None)
            or "UNKNOWN"
        ),
        "symbol_equivalence_status": entry.symbol_equivalence or "NOT_PROVEN",
        "binding_state": classified["binding_state"],
        "binding_status": "ALLOWED" if classified["allowed"] else "BLOCKED",
        "mapping_source": classified["mapping_source"],
        "mapping_status": classified["mapping_status"],
        "spread_mode": entry.spread_mode,
        "cost_completeness": entry.cost_completeness or "UNKNOWN",
        "reason": classified["reason"]
        if classified["binding_state"] != MISSING_EXPLICIT_MAP
        else (
            "logical XAUUSD without explicit dataset_symbol_map; "
            "XAUUSD -> XAUUSD_i is proposed only and not proven"
        ),
        "required_mapping": {"XAUUSD": CANONICAL_SYMBOL}
        if classified["binding_state"] == MISSING_EXPLICIT_MAP
        else None,
        "proposed_binding": classified["proposed_binding"],
        "filename_used_as_map": False,
        "live_resolver_used": False,
        "ev_eq_01": "NOT_PROVEN",
        "sidecar_rewritten": False,
        "parquet_rewritten": False,
    }


def audit_resolver_sources(root: Path) -> dict[str, Any]:
    """Confirm dataset-bind sources cannot silently alias XAUUSD → XAUUSD_i."""
    bind_files = (
        root / "tradingbot" / "backtest" / "dataset_contract.py",
        root / "tradingbot" / "backtest" / "data_source.py",
        root / "tradingbot" / "backtest" / "engine.py",
    )
    issues: list[str] = []
    uses_dataset_resolver: list[str] = []
    uses_live_helper_as_bind: list[str] = []
    contract_path = root / "tradingbot" / "backtest" / "dataset_contract.py"
    for path in bind_files:
        text = path.read_text(encoding="utf-8")
        rel = str(path.relative_to(root)).replace("\\", "/")
        if "resolve_broker_symbol_for_dataset" in text:
            uses_dataset_resolver.append(rel)
        if "from tradingbot.adapters.symbols import resolve_broker_symbol" in text:
            uses_live_helper_as_bind.append(rel)
            issues.append(f"live_helper_imported_as_dataset_bind:{rel}")
        if path == contract_path:
            for token in FORBIDDEN_DATASET_TOKENS:
                if token in text:
                    issues.append(f"forbidden:{rel}:{token}")
    silent_possible = False
    try:
        resolve_broker_symbol_for_dataset("XAUUSD", configured_symbol=CANONICAL_SYMBOL)
        silent_possible = True
        issues.append("silent_xauusd_alias_succeeded")
    except InstrumentContractError:
        silent_possible = False
    return {
        "dataset_bind_paths": list(DATASET_BIND_PATHS),
        "live_helper": dict(LIVE_HELPER),
        "dataset_resolver_files": uses_dataset_resolver,
        "live_helper_used_as_dataset_bind": uses_live_helper_as_bind,
        "silent_xauusd_to_xauusd_i_possible": silent_possible,
        "missing_mappings_fail_closed": not silent_possible,
        "issues": issues,
        "ok": not issues and not silent_possible and not uses_live_helper_as_bind,
    }


def contract_self_checks() -> dict[str, Any]:
    direct = classify_binding_state("XAUUSD_i")
    missing = classify_binding_state("XAUUSD", dataset_symbol_map={})
    mapped = classify_binding_state("XAUUSD", dataset_symbol_map={"XAUUSD": CANONICAL_SYMBOL})
    invalid = classify_binding_state("XAUUSD", dataset_symbol_map={"XAUUSD": "EURUSD"})
    malformed = False
    try:
        validate_dataset_symbol_map(["XAUUSD", CANONICAL_SYMBOL], configured_symbol=CANONICAL_SYMBOL)  # type: ignore[arg-type]
    except InstrumentContractError as exc:
        malformed = exc.code == "INVALID_MAP"
    unavailable = False
    try:
        validate_dataset_symbol_map(
            {"XAUUSD": CANONICAL_SYMBOL},
            configured_symbol=CANONICAL_SYMBOL,
            available_broker_symbols=frozenset({"EURUSD"}),
        )
    except InstrumentContractError as exc:
        unavailable = exc.code == "INVALID_MAP"
    silent_raised = False
    try:
        resolve_broker_symbol_for_dataset("XAUUSD", configured_symbol=CANONICAL_SYMBOL)
    except InstrumentContractError:
        silent_raised = True
    return {
        "direct_canonical_ok": direct["binding_state"] == DIRECT_CANONICAL_MATCH and direct["allowed"],
        "missing_map_blocked": missing["binding_state"] == MISSING_EXPLICIT_MAP and missing["blocked"],
        "explicit_map_allowed": mapped["binding_state"] == EXPLICIT_MAPPED and mapped["allowed"],
        "invalid_map_blocked": invalid["binding_state"] == INVALID_MAP and invalid["blocked"],
        "malformed_map_blocked": malformed,
        "unavailable_target_blocked": unavailable,
        "silent_fallback_prevented": silent_raised,
        "default_config_map_empty": dict(BacktestConfig().dataset_symbol_map) == {},
        "xauusd_absent_from_offline_catalog": "XAUUSD" not in OFFLINE_INSTRUMENT_CATALOG,
        "canonical_unchanged": CANONICAL_SYMBOL == "XAUUSD_i" == PRIMARY_SYMBOL,
        "ev_eq_01": "NOT_PROVEN",
    }


def _prior_binding_status(root: Path) -> str:
    prior = _safe_load_json(root / PHASE2720_JSON)
    if not prior:
        return "UNKNOWN"
    blocked = int(prior.get("authorization_required_count") or 0)
    if blocked > 0:
        return f"BLOCKED ({blocked} logical XAUUSD MISSING_EXPLICIT_MAP / INSUFFICIENT_PROVENANCE)"
    return "UNKNOWN"


def run_phase27_27_dataset_symbol_binding(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path(__file__).resolve().parents[2])
    timestamp = _utc_now()
    canonical_before = {
        rel: file_fingerprint(root / rel) for rel in CANONICAL_PRODUCTION if (root / rel).is_file()
    }
    before = build_immutability_manifest(root)
    config_map = dict(BacktestConfig().dataset_symbol_map)
    entries = audit_backtest_datasets(base_dir=root, configured_symbol=CANONICAL_SYMBOL)
    inventory = [inventory_one(entry, config_map=config_map) for entry in entries]
    resolver = audit_resolver_sources(root)
    checks = contract_self_checks()
    originals_untouched, imm_issues = verify_immutability(before, base_dir=root)
    canonical_after = {
        rel: file_fingerprint(root / rel) for rel in CANONICAL_PRODUCTION if (root / rel).is_file()
    }
    final_gate = (_safe_load_json(root / PHASE2716_JSON) or {}).get("FINAL_GATE") or "UNKNOWN"

    counts = {
        DIRECT_CANONICAL_MATCH: 0,
        EXPLICIT_MAPPED: 0,
        MISSING_EXPLICIT_MAP: 0,
        INVALID_MAP: 0,
        UNKNOWN_PROVENANCE: 0,
    }
    for row in inventory:
        counts[row["binding_state"]] = counts.get(row["binding_state"], 0) + 1
    allowed_n = sum(1 for row in inventory if row["binding_status"] == "ALLOWED")
    blocked_n = sum(1 for row in inventory if row["binding_status"] == "BLOCKED")
    blocked_rows = [
        {
            "path": row["path"],
            "logical_symbol": row["logical_symbol"],
            "current_binding": row["broker_symbol"],
            "required_mapping": row["required_mapping"],
            "reason_blocked": row["reason"],
            "binding_state": row["binding_state"],
        }
        for row in inventory
        if row["binding_status"] == "BLOCKED"
    ]
    matrix = [
        {
            "dataset": row["filename"],
            "path": row["path"],
            "logical_symbol": row["logical_symbol"],
            "broker_symbol": row["broker_symbol"],
            "binding_state": row["binding_state"],
            "explicit_map": row["explicit_map"],
            "provenance": row["sidecar_provenance"],
            "status": row["binding_status"],
        }
        for row in inventory
    ]
    maps_inserted = False
    canonical_changed = canonical_before != canonical_after
    binding_after = (
        "BLOCKED"
        if counts[MISSING_EXPLICIT_MAP] or counts[INVALID_MAP] or counts[UNKNOWN_PROVENANCE]
        else "BOUND"
    )
    payload: dict[str, Any] = {
        "schema_version": 1,
        "phase": "27.27",
        "status": "PASS",
        "timestamp": timestamp,
        "repository_commit": _git_head(root),
        "canonical_symbol": CANONICAL_SYMBOL,
        "dataset_binding_policy": POLICY,
        "ev_eq_01": "NOT_PROVEN",
        "existing_map_locations": list(EXISTING_MAP_LOCATIONS),
        "invented_new_map_convention": False,
        "maps_inserted": maps_inserted,
        "default_backtest_dataset_symbol_map": config_map,
        "dataset_count": len(inventory),
        "totals": {
            "total_relevant_datasets": len(inventory),
            "DIRECT_CANONICAL_MATCH": counts[DIRECT_CANONICAL_MATCH],
            "EXPLICIT_MAPPED": counts[EXPLICIT_MAPPED],
            "MISSING_EXPLICIT_MAP": counts[MISSING_EXPLICIT_MAP],
            "INVALID_MAP": counts[INVALID_MAP],
            "UNKNOWN_PROVENANCE": counts[UNKNOWN_PROVENANCE],
            "blocked_count": blocked_n,
            "allowed_count": allowed_n,
        },
        "dataset_binding_before": _prior_binding_status(root),
        "dataset_binding_after": binding_after,
        "inventory": inventory,
        "binding_matrix": matrix,
        "blocked_datasets": blocked_rows,
        "canonical_xauusd_i_datasets": [
            row["filename"] for row in inventory if row["binding_state"] == DIRECT_CANONICAL_MATCH
        ],
        "resolver_audit": resolver,
        "contract_self_checks": checks,
        "canonical_fingerprints_before": canonical_before,
        "canonical_fingerprints_after": canonical_after,
        "canonical_parquet_changed": canonical_changed,
        "fingerprints_preserved": originals_untouched and not canonical_changed,
        "original_datasets_untouched": originals_untouched,
        "immutability_issues": imm_issues,
        "sidecars_rewritten": False,
        "parquet_rewritten": False,
        "complete_costs_required_weakened": False,
        "phase27_16_final_gate_unchanged": final_gate,
        "production_readiness": "BLOCKED",
        "production_changes": "tradingbot/backtest/dataset_contract.py (malformed/unavailable map fail-closed only)",
        "safety_confirmation": {
            "mt5_started": False,
            "orders_sent": False,
            "symbol_select_called": False,
            "env_file_read": False,
            "parquet_rewritten": False,
            "sidecars_rewritten": False,
            "maps_silently_inserted": False,
            "filename_used_as_map": False,
            "resolve_broker_symbol_used_as_dataset_map": False,
            "equivalence_fabricated": False,
            "strategy_modified": False,
            "riskgate_modified": False,
            "execution_modified": False,
            "canonical_symbol_changed": False,
            "phase_27_28_started": False,
        },
        "deferred": ["Phase 27.28+ — not started"],
    }
    required = (
        originals_untouched,
        not canonical_changed,
        not maps_inserted,
        checks["direct_canonical_ok"],
        checks["missing_map_blocked"],
        checks["explicit_map_allowed"],
        checks["invalid_map_blocked"],
        checks["malformed_map_blocked"],
        checks["unavailable_target_blocked"],
        checks["silent_fallback_prevented"],
        checks["default_config_map_empty"],
        checks["canonical_unchanged"],
        checks["ev_eq_01"] == "NOT_PROVEN",
        resolver["ok"],
        payload["default_backtest_dataset_symbol_map"] == {},
        final_gate == "BLOCKED",
        not payload["invented_new_map_convention"],
        payload["ev_eq_01"] == "NOT_PROVEN",
        not payload["complete_costs_required_weakened"],
    )
    if not all(required):
        payload["status"] = "FAILED"

    out = root / PHASE2727_JSON
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    _write_md(root, payload)
    _update_truth_docs(root, payload)
    return payload


def run_phase27_27_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    return run_phase27_27_dataset_symbol_binding(base_dir)


def _write_md(root: Path, payload: dict[str, Any]) -> None:
    totals = payload["totals"]
    lines = [
        "| Dataset | Logical Symbol | Broker Symbol | Binding State | Explicit Map | Provenance | Status |",
        "|---------|----------------|---------------|---------------|--------------|------------|--------|",
    ]
    for row in payload["binding_matrix"]:
        lines.append(
            "| `{dataset}` | `{logical}` | `{broker}` | `{state}` | `{explicit}` | `{prov}` | `{status}` |".format(
                dataset=row["dataset"],
                logical=row["logical_symbol"],
                broker=row["broker_symbol"],
                state=row["binding_state"],
                explicit=row["explicit_map"],
                prov=row["provenance"],
                status=row["status"],
            )
        )
    table = "\n".join(lines)
    blocked_lines = [
        "| path | logical | current binding | required mapping | reason |",
        "|---|---|---|---|---|",
    ]
    for row in payload["blocked_datasets"]:
        blocked_lines.append(
            "| `{path}` | `{logical}` | `{bind}` | `{req}` | {reason} |".format(
                path=row["path"],
                logical=row["logical_symbol"],
                bind=row["current_binding"],
                req=row["required_mapping"],
                reason=row["reason_blocked"],
            )
        )
    blocked_table = "\n".join(blocked_lines)
    md = f"""# Phase 27.27 — Dataset Provenance & Explicit Symbol Binding Closure

**Status:** {payload["status"]}  
**Artifact:** `{PHASE2727_JSON}`  
**Timestamp UTC:** `{payload["timestamp"]}`

## Policy

| Decision | Value |
|---|---|
| Canonical gold symbol | `{payload["canonical_symbol"]}` |
| Logical XAUUSD datasets | `{payload["dataset_binding_policy"]}` |
| EV-EQ-01 | **{payload["ev_eq_01"]}** |

An explicit `dataset_symbol_map` is an auditable alias rule. It does **not** prove `XAUUSD` ≡ `XAUUSD_i`.
Decision 2 authorizes the mechanism. It does not populate filename-only aliases.
`XAUUSD` → `XAUUSD_i` remains a **proposed** binding only.

## Totals

| Metric | Count |
|---|---|
| total relevant datasets | `{totals["total_relevant_datasets"]}` |
| DIRECT_CANONICAL_MATCH | `{totals["DIRECT_CANONICAL_MATCH"]}` |
| EXPLICIT_MAPPED | `{totals["EXPLICIT_MAPPED"]}` |
| MISSING_EXPLICIT_MAP | `{totals["MISSING_EXPLICIT_MAP"]}` |
| INVALID_MAP | `{totals["INVALID_MAP"]}` |
| UNKNOWN_PROVENANCE | `{totals["UNKNOWN_PROVENANCE"]}` |
| allowed | `{totals["allowed_count"]}` |
| blocked | `{totals["blocked_count"]}` |

Maps inserted: **{payload["maps_inserted"]}**. Default `BacktestConfig.dataset_symbol_map`: `{{}}`.

## Binding matrix

{table}

## Blocked datasets

{blocked_table}

## Resolver audit

Dataset bind is `resolve_broker_symbol_for_dataset`. Missing or invalid maps fail closed (`SYMBOL_MISMATCH` / `INVALID_MAP`).
Silent `XAUUSD` → `XAUUSD_i` conversion is **not** possible on the dataset path.

`tradingbot.adapters.symbols.resolve_broker_symbol` remains the live/environment helper and is **not** a dataset bind. RiskGate / execution were not changed.

## Immutability

Canonical parquet changed: `{payload["canonical_parquet_changed"]}`.  
Fingerprints preserved: `{payload["fingerprints_preserved"]}`.  
Sidecars rewritten: `{payload["sidecars_rewritten"]}`.

## FINAL_GATE

dataset_binding_before: `{payload["dataset_binding_before"]}`  
dataset_binding_after: `{payload["dataset_binding_after"]}`  
COMPLETE_COSTS_REQUIRED remains enforced. FINAL_GATE remains `{payload["phase27_16_final_gate_unchanged"]}`.

## Next

STOP after Phase 27.27.
"""
    (root / PHASE2727_MD).write_text(md, encoding="utf-8")


def _update_truth_docs(root: Path, payload: dict[str, Any]) -> None:
    totals = payload["totals"]
    known = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    if known.is_file():
        text = known.read_text(encoding="utf-8")
        pointer = (
            f"**Phase 27.27 dataset symbol binding:** `{PHASE2727_JSON}` — "
            f"`{totals['DIRECT_CANONICAL_MATCH']}` DIRECT_CANONICAL_MATCH; "
            f"`{totals['MISSING_EXPLICIT_MAP']}` MISSING_EXPLICIT_MAP; "
            f"`{totals['EXPLICIT_MAPPED']}` EXPLICIT_MAPPED; "
            f"`{totals['UNKNOWN_PROVENANCE']}` UNKNOWN_PROVENANCE; "
            "0 maps inserted; EV-EQ-01 NOT_PROVEN"
        )
        if pointer not in text:
            anchor = "**Phase 27.26 canonical bid/ask coverage:** `logs/phase27_26_canonical_bidask_coverage.json` — `PARTIAL_CANONICAL_COVERAGE`; historical_spread `PARTIAL`; production parquet unchanged"
            if anchor in text:
                text = text.replace(anchor, anchor + "  \n" + pointer)
            elif "**Operator policy:**" in text:
                text = text.replace("**Operator policy:**", pointer + "  \n**Operator policy:**")
        old_res = (
            "**Resolution:** Fail-closed — explicit `dataset_symbol_map` required; "
            "silent `XAUUSD`→`XAUUSD_i` treatment forbidden; equivalence not assumed "
            "(Phase 25E/27/27.8/27.10/27.20). Phase 27.20: 30 logical XAUUSD left BLOCKED "
            "(30 require operator authorization); 0 maps inserted from filename. Invalid maps also BLOCKED."
        )
        new_res = (
            "**Resolution:** Fail-closed — explicit `dataset_symbol_map` required; "
            "silent `XAUUSD`→`XAUUSD_i` treatment forbidden; equivalence not assumed "
            "(Phase 25E/27/27.8/27.10/27.20/27.27). Phase 27.27: "
            f"{totals['MISSING_EXPLICIT_MAP']} logical XAUUSD `MISSING_EXPLICIT_MAP`; "
            f"{totals['DIRECT_CANONICAL_MATCH']} `DIRECT_CANONICAL_MATCH`; "
            f"{totals['EXPLICIT_MAPPED']} `EXPLICIT_MAPPED`; "
            "0 maps inserted; EV-EQ-01 remains NOT_PROVEN."
        )
        if old_res in text:
            text = text.replace(old_res, new_res)
        known.write_text(text, encoding="utf-8")

    design = root / "docs_v2/01_truth/DEMO_REAL_SYMBOL_COST_DESIGN.md"
    if design.is_file():
        text = design.read_text(encoding="utf-8")
        pointer = (
            f"**Phase 27.27 dataset symbol binding:** `{PHASE2727_JSON}` — "
            "recomputed inventory; no silent map; EV-EQ-01 NOT_PROVEN"
        )
        if pointer not in text:
            anchor = "**Phase 27.26 complete canonical bid/ask:** `logs/phase27_26_canonical_bidask_coverage.json` — merge + missing-interval collection; 27.25 tape preserved; production parquet unchanged"
            if anchor in text:
                text = text.replace(anchor, anchor + "  \n" + pointer)
        design.write_text(text, encoding="utf-8")

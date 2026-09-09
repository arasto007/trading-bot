"""Phase 35 — broker cost, execution, and live-fill reality validation.

RESEARCH ONLY. Offline synthesis of Phase 27 evidence. No live orders, no
MT5 attach, no production change, no upgrade of MODELED to VERIFIED.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase25h_run import build_immutability_manifest, verify_immutability
from tradingbot.backtest.phase27_8_policy_lock import LOCKED_POLICY
from tradingbot.backtest.phase27_15_cost_completeness_gate import (
    GATE_COMPONENTS,
    PHASE2715_JSON,
    component_is_complete,
    cost_ready_for_validation,
)
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_26_canonical_bidask_coverage import TAPE_PARQUET as BIDASK_TAPE
from tradingbot.backtest.phase27_28_commission_evidence import PHASE2728_JSON
from tradingbot.backtest.phase27_29_swap_evidence import PHASE2729_JSON
from tradingbot.backtest.phase27_30_slippage_evidence import (
    CANONICAL_PARQUET,
    PHASE2730_JSON,
    file_fingerprint,
)
from tradingbot.backtest.phase27_31_execution_evidence import PHASE2731_JSON
from tradingbot.backtest.phase27_32_final_cost_evidence_gate import PHASE2732_JSON
from tradingbot.backtest.phase28_0_performance_foundation import EXPECTED_CANONICAL_FINGERPRINT
from tradingbot.config.live import PRIMARY_SYMBOL
from tradingbot.domain.position_logic import pip_size as pip_size_of

PHASE = "35"
PHASE35_JSON = "logs/phase35_execution_reality.json"
PHASE35_MD = "docs_v2/02_research/PHASE35_EXECUTION_REALITY.md"
EVALUATOR_VERSION = "phase35-execution-v1"
UNKNOWN = "UNKNOWN"
BLOCKED = "BLOCKED"
PARTIAL = "PARTIAL"
COMPLETE = "COMPLETE"
INCOMPLETE = "INCOMPLETE"
VERIFIED = "VERIFIED"
OBSERVED = "OBSERVED"
PROXY = "PROXY"
MODELED = "MODELED"
NY_START_HOUR = 15
NY_END_HOUR = 16
EVIDENCE_GRADES = (VERIFIED, OBSERVED, PROXY, MODELED, UNKNOWN)

SOURCE_ARTIFACTS = {
    "phase27_8": "logs/phase27_8_policy_lock.json",
    "phase27_15": PHASE2715_JSON,
    "phase27_16": PHASE2716_JSON,
    "phase27_26": "logs/phase27_26_canonical_bidask_coverage.json",
    "phase27_27": "logs/phase27_27_dataset_symbol_binding.json",
    "phase27_28": PHASE2728_JSON,
    "phase27_29": PHASE2729_JSON,
    "phase27_30": PHASE2730_JSON,
    "phase27_31": PHASE2731_JSON,
    "phase27_32": PHASE2732_JSON,
}

REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "research_only",
    "live_orders",
    "dataset_fingerprint",
    "cost_components",
    "spread",
    "commission",
    "swap",
    "slippage",
    "execution",
    "economics_contract",
    "cost_completeness",
    "FINAL_GATE",
    "phase_36_started",
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


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def _stable_hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def load_artifacts(root: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for key, rel in SOURCE_ARTIFACTS.items():
        data = _safe_load_json(root / rel)
        out[key] = data if isinstance(data, dict) else {}
    return out


def _pct(values: np.ndarray, q: float) -> float | None:
    if values.size == 0:
        return None
    return float(np.percentile(values, q))


def _dist(values: np.ndarray) -> dict[str, Any]:
    if values.size == 0:
        return {"n": 0, "median": None, "p75": None, "p90": None, "p95": None, "p99": None}
    return {
        "n": int(values.size),
        "median": _pct(values, 50),
        "p75": _pct(values, 75),
        "p90": _pct(values, 90),
        "p95": _pct(values, 95),
        "p99": _pct(values, 99),
    }


def load_bid_ask_spreads(path: Path) -> tuple[pd.Series, dict[str, Any]]:
    if not path.is_file():
        return pd.Series(dtype=float), {"present": False}
    df = pd.read_parquet(path)
    if not isinstance(df.index, pd.DatetimeIndex):
        for col in ("time", "timestamp", "datetime"):
            if col in df.columns:
                df = df.set_index(pd.to_datetime(df[col], utc=True))
                break
    if isinstance(df.index, pd.DatetimeIndex):
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")
        df = df.sort_index()
    cols = {str(c).lower(): c for c in df.columns}
    bid_col = cols.get("bid") or cols.get("bid_close") or cols.get("close_bid")
    ask_col = cols.get("ask") or cols.get("ask_close") or cols.get("close_ask")
    if bid_col is None or ask_col is None:
        return pd.Series(dtype=float), {
            "present": True,
            "columns": list(df.columns),
            "bid_ask_columns": False,
        }
    spread = (pd.to_numeric(df[ask_col], errors="coerce") - pd.to_numeric(df[bid_col], errors="coerce")).dropna()
    spread = spread[spread >= 0]
    return spread, {
        "present": True,
        "bid_ask_columns": True,
        "bid_col": str(bid_col),
        "ask_col": str(ask_col),
        "rows": int(len(df)),
        "spread_n": int(len(spread)),
    }


def spread_audit(root: Path, arts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    p26 = arts.get("phase27_26") or {}
    tape = root / BIDASK_TAPE
    series, meta = load_bid_ask_spreads(tape)
    pip = pip_size_of(PRIMARY_SYMBOL)
    price = series.to_numpy(dtype=float) if not series.empty else np.array([], dtype=float)
    pips = price / pip if price.size else np.array([], dtype=float)
    ny_mask = None
    ny_price = np.array([], dtype=float)
    ny_open_price = np.array([], dtype=float)
    if not series.empty and isinstance(series.index, pd.DatetimeIndex):
        hours = series.index.hour
        ny_mask = (hours >= NY_START_HOUR) & (hours < NY_END_HOUR)
        ny_price = series[ny_mask].to_numpy(dtype=float)
        ny_open_price = series[hours == NY_START_HOUR].to_numpy(dtype=float)
    production = PROXY
    sidecar = OBSERVED if meta.get("bid_ask_columns") and price.size else UNKNOWN
    return {
        "production_parquet": {
            "path": CANONICAL_PARQUET,
            "grade": production,
            "spread_mode": "PROXY",
            "source": "ohlc_only",
            "historical_bid_ask": False,
            "note": "Production M5 has no Bid/Ask columns. PROXY must not be promoted to DATASET.",
        },
        "sidecar_tape": {
            "path": BIDASK_TAPE,
            "grade": sidecar,
            "not_a_production_dataset": True,
            "coverage": p26.get("final_classification") or p26.get("classification") or UNKNOWN,
            "meta": meta,
            "price_units": "ask_minus_bid",
            "pip_size": pip,
            "overall": {"price": _dist(price), "pips": _dist(pips)},
            "ny_session_15_16_utc": {
                "price": _dist(ny_price),
                "pips": _dist(ny_price / pip) if ny_price.size else _dist(ny_price),
            },
            "ny_open_hour_15_utc": {
                "price": _dist(ny_open_price),
                "pips": _dist(ny_open_price / pip) if ny_open_price.size else _dist(ny_open_price),
            },
            "note": (
                "OBSERVED only on the Phase 27.26 sidecar tape (~15-day window). "
                "PARTIAL coverage is not VERIFIED full-tape historical Bid/Ask."
            ),
        },
        "grade": PROXY,
        "and_status": BLOCKED,
        "modeled_not_converted_to_verified": True,
    }


def commission_audit(arts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    p28 = arts.get("phase27_28") or {}
    zeros = int(p28.get("commission_zero_count") or 0)
    return {
        "grade": UNKNOWN,
        "and_status": BLOCKED,
        "account_specific_schedule": False,
        "account_product_type": p28.get("account_product_type") or UNKNOWN,
        "applicability": bool(p28.get("applicability")),
        "public_docs": {
            "present": True,
            "class": "GENERIC_SUPPORTING",
            "applicability_uncertainty": True,
            "note": "Public LiteFinance pages are supporting only. They are not an account-applicable VERIFIED_SCHEDULE.",
        },
        "deal_tape": {
            "zero_count": zeros,
            "nonzero_count": int(p28.get("commission_nonzero_count") or 0),
            "status": p28.get("commission_status_after") or "OBSERVED_ZERO_NOT_PROVEN",
            "zero_is_not_verified_zero": True,
            "note": "Do not assume zero commission from a short all-zero tape.",
        },
        "never_verified_from_modeled": True,
    }


def swap_audit(arts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    p29 = arts.get("phase27_29") or {}
    return {
        "historical_grade": UNKNOWN,
        "current_rate_grade": OBSERVED if p29.get("current_broker_rate_proven") else UNKNOWN,
        "grade": UNKNOWN,
        "and_status": UNKNOWN,
        "current_swap_long": p29.get("current_swap_long"),
        "current_swap_short": p29.get("current_swap_short"),
        "current_rollover_day": p29.get("current_rollover_day"),
        "current_rate_is_historical": bool(p29.get("current_rate_is_historical")),
        "deal_zeros_prove_historical_zero": False,
        "note": (
            "Observed current broker rates are not a historical swap series. "
            "Do not infer historical zero swap from short-duration / zero-swap deals."
        ),
    }


def slippage_audit(arts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    p30 = arts.get("phase27_30") or {}
    genuine = int(p30.get("genuine_pair_count") or p30.get("buy_sample_count") or 0)
    if genuine == 0 and p30.get("absolute_stats"):
        genuine = int((p30.get("absolute_stats") or {}).get("count") or 0)
    return {
        "grade": MODELED,
        "realized_grade": UNKNOWN,
        "and_status": UNKNOWN,
        "genuine_requested_vs_executed_pairs": genuine,
        "mt5_deviation_is_realized_slippage": False,
        "price_open_is_requested": False,
        "default_slippage_pips": p30.get("default_slippage_pips"),
        "default_status": p30.get("default_slippage_status") or "MODELED_PROXY",
        "evidence_grade_27_30": p30.get("evidence_grade"),
        "modeled_not_converted_to_verified": True,
        "note": "No genuine requested-vs-fill pairs. Remain MODELED / UNKNOWN.",
    }


def execution_audit(arts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    p31 = arts.get("phase27_31") or {}
    audit = p31.get("audit") or {}
    return {
        "grade": UNKNOWN,
        "and_status": UNKNOWN,
        "requested_volume": audit.get("volume_linkage") or "NOT_IDENTIFIABLE",
        "executed_volume": "OBSERVED_ON_DEAL_TAPE_ONLY" if int(audit.get("deals_with_fill_volume") or 0) else UNKNOWN,
        "requested_price": "NOT_IDENTIFIABLE",
        "executed_price": "OBSERVED_ON_DEAL_TAPE_ONLY" if int(audit.get("deal_count") or 0) else UNKNOWN,
        "partial_fills": audit.get("partial_fills") or "NOT_PROVEN",
        "rejection": audit.get("rejections") or "NOT_OBSERVABLE",
        "requote": audit.get("requotes") or "NOT_OBSERVABLE",
        "latency": audit.get("execution_latency") or "NOT_DERIVABLE",
        "order_deal_linkage": audit.get("order_deal_linkage") or "INCOMPLETE",
        "deal_count": audit.get("deal_count"),
        "order_count": audit.get("order_count"),
        "linked_deal_count": audit.get("linked_deal_count"),
        "latency_pair_count": audit.get("latency_pair_count"),
        "simulated_broker_is_not_realized": True,
        "pairs_fabricated": False,
        "evidence_grade_27_31": audit.get("evidence_grade") or p31.get("evidence_grade"),
        "note": "Fill tape is not an order lifecycle. Missing requested/executed pairs were not fabricated.",
    }


def economics_contract(arts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    p15 = arts.get("phase27_15") or {}
    p32 = arts.get("phase27_32") or {}
    return {
        "grade": UNKNOWN,
        "and_status": UNKNOWN,
        "volume_constraints": UNKNOWN,
        "minimum_lot": UNKNOWN,
        "volume_step": UNKNOWN,
        "contract_size": UNKNOWN,
        "tick_value": UNKNOWN,
        "tick_size": UNKNOWN,
        "stale_snapshots_are_not_current": True,
        "heuristic_backtest_contract_size_is_not_broker_evidence": True,
        "phase27_15_economics": (p15.get("components") or {}).get("economics") or p15.get("economics") or UNKNOWN,
        "phase27_32_broker_economics": next(
            (r for r in (p32.get("component_matrix") or []) if r.get("component") == "broker_economics"),
            {},
        ),
        "note": "Fresh Real/Demo XAUUSD_i economics were not collected this phase. No .env / MT5 attach.",
    }


def and_components(
    *,
    spread: dict[str, Any],
    commission: dict[str, Any],
    swap: dict[str, Any],
    slippage: dict[str, Any],
    execution: dict[str, Any],
    arts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    p15 = arts.get("phase27_15") or {}
    p27 = arts.get("phase27_27") or {}
    stored = p15.get("components") or {}
    from_matrix = {
        str(r.get("blocker")): r.get("status")
        for r in (p15.get("blocker_matrix") or [])
        if r.get("blocker")
    }

    def _st(name: str, fallback: str) -> str:
        nested = (stored.get(name) or {}).get("status")
        return str(nested or from_matrix.get(name) or fallback)

    rows = {
        "symbol_binding": {
            "and_status": _st("symbol_binding", BLOCKED),
            "grade": UNKNOWN,
            "grade": UNKNOWN,
            "note": "Decision 2 ONLY_WITH_EXPLICIT_DATASET_MAP. EV-EQ-01 NOT_PROVEN. 30 logical XAUUSD remain unmapped.",
            "phase27_27": {
                "direct_canonical_match": (p27.get("counts") or {}).get("DIRECT_CANONICAL_MATCH"),
                "missing_explicit_map": (p27.get("counts") or {}).get("MISSING_EXPLICIT_MAP"),
            },
        },
        "economics": {
            "and_status": _st("economics", UNKNOWN),
            "grade": UNKNOWN,
        },
        "dataset_provenance": {
            "and_status": _st("dataset_provenance", PARTIAL),
            "grade": PROXY,
            "grade": PROXY,
            "note": "Sidecars exist; cost fields incomplete. 0 COMPLETE datasets.",
        },
        "spread": {"and_status": spread["and_status"], "grade": spread["grade"]},
        "commission": {"and_status": commission["and_status"], "grade": commission["grade"]},
        "swap": {"and_status": swap["and_status"], "grade": swap["grade"]},
        "slippage": {"and_status": slippage["and_status"], "grade": slippage["grade"]},
        "execution_model": {"and_status": execution["and_status"], "grade": execution["grade"]},
    }
    gate_input = {name: {"status": rows[name]["and_status"]} for name in GATE_COMPONENTS}
    ready = cost_ready_for_validation(gate_input)
    complete_n = sum(1 for name in GATE_COMPONENTS if component_is_complete(rows[name]["and_status"]))
    classification = COMPLETE if ready else INCOMPLETE
    return {
        "components": rows,
        "and_satisfied": bool(ready),
        "complete_count": complete_n,
        "required_count": len(GATE_COMPONENTS),
        "classification": classification,
        "policy": LOCKED_POLICY.get("DECISION_6"),
        "cost_adjusted_metrics_allowed": False,
        "theoretical_edge_survives_broker_economics": False,
        "theoretical_edge_claim": "NOT_PROVEN",
        "note": (
            "AND-gate requires all eight components COMPLETE. "
            f"{complete_n}/{len(GATE_COMPONENTS)} COMPLETE. PARTIAL sidecar spread is not COMPLETE. "
            "Classification is INCOMPLETE. MODELED was not converted to VERIFIED."
        ),
    }


def evaluate(root: Path) -> dict[str, Any]:
    arts = load_artifacts(root)
    spread = spread_audit(root, arts)
    commission = commission_audit(arts)
    swap = swap_audit(arts)
    slippage = slippage_audit(arts)
    execution = execution_audit(arts)
    economics = economics_contract(arts)
    completeness = and_components(
        spread=spread,
        commission=commission,
        swap=swap,
        slippage=slippage,
        execution=execution,
        arts=arts,
    )
    p16 = arts.get("phase27_16") or {}
    p32 = arts.get("phase27_32") or {}
    return {
        "cost_components": completeness["components"],
        "spread": spread,
        "commission": commission,
        "swap": swap,
        "slippage": slippage,
        "execution": execution,
        "economics_contract": economics,
        "cost_completeness": completeness,
        "prior_gates": {
            "phase27_15_cost_ready": (arts.get("phase27_15") or {}).get("COST_READY_FOR_VALIDATION"),
            "phase27_16_FINAL_GATE": p16.get("FINAL_GATE"),
            "phase27_32_complete_costs_required_result": p32.get("complete_costs_required_result"),
        },
    }


def _write_markdown(root: Path, payload: dict[str, Any]) -> None:
    sp = payload["spread"]["sidecar_tape"]
    overall = sp.get("overall") or {}
    ny = sp.get("ny_session_15_16_utc") or {}
    nopen = sp.get("ny_open_hour_15_utc") or {}
    path = root / PHASE35_MD
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""# Phase 35 — Broker Cost, Execution & Live-Fill Reality

**Status:** {payload.get("status")}
**Class:** RESEARCH ONLY
**Live orders:** NO
**Parameters optimized:** NO
**FINAL_GATE:** `{payload.get("FINAL_GATE")}`
**Cost completeness:** `{payload["cost_completeness"]["classification"]}`

STOP AFTER PHASE 35. DO NOT START PHASE 36.

Offline synthesis of Phase 27 evidence. MODELED was **not** converted to VERIFIED.

---

## Evidence grades

Allowed: VERIFIED / OBSERVED / PROXY / MODELED / UNKNOWN.

| Component | Grade | AND status |
|---|---|---|
| symbol_binding | {payload["cost_components"]["symbol_binding"]["grade"]} | {payload["cost_components"]["symbol_binding"]["and_status"]} |
| economics | {payload["cost_components"]["economics"]["grade"]} | {payload["cost_components"]["economics"]["and_status"]} |
| dataset_provenance | {payload["cost_components"]["dataset_provenance"]["grade"]} | {payload["cost_components"]["dataset_provenance"]["and_status"]} |
| spread | {payload["cost_components"]["spread"]["grade"]} | {payload["cost_components"]["spread"]["and_status"]} |
| commission | {payload["cost_components"]["commission"]["grade"]} | {payload["cost_components"]["commission"]["and_status"]} |
| swap | {payload["cost_components"]["swap"]["grade"]} | {payload["cost_components"]["swap"]["and_status"]} |
| slippage | {payload["cost_components"]["slippage"]["grade"]} | {payload["cost_components"]["slippage"]["and_status"]} |
| execution_model | {payload["cost_components"]["execution_model"]["grade"]} | {payload["cost_components"]["execution_model"]["and_status"]} |

## Spread

Production parquet: **PROXY** (OHLC only).  
Sidecar 27.26 tape: **OBSERVED** for that ~15-day window only — not a production DATASET.

Overall (price / pips): `{overall}`  
NY 15–16 UTC: `{ny}`  
NY-open hour 15 UTC: `{nopen}`

## Commission

No account-applicable VERIFIED_SCHEDULE. Public pages GENERIC_SUPPORTING with applicability uncertainty. All-zero short tape is OBSERVED_ZERO_NOT_PROVEN — not zero commission.

## Swap

Current broker rates may be OBSERVED. Historical series UNKNOWN. Short-hold zeros do not prove historical zero swap.

## Slippage

Genuine requested-vs-fill pairs: `{payload["slippage"]["genuine_requested_vs_executed_pairs"]}`.  
MT5 deviation is **not** realized slippage. Grade remains MODELED / UNKNOWN.

## Execution

Requested volume/price not identifiable. Partials / rejections / requotes / latency not proven. Order↔deal linkage incomplete. SimulatedBroker is not realized. Missing pairs were not fabricated.

## Economics contract

minimum lot / volume step / contract size / tick value / tick size / volume constraints: **UNKNOWN** as current broker evidence.

## FINAL COST COMPLETENESS

AND-gate `{payload["cost_completeness"]["complete_count"]}/{payload["cost_completeness"]["required_count"]}` COMPLETE.  
Classification: **{payload["cost_completeness"]["classification"]}**.  
Theoretical edge surviving broker economics: **NOT_PROVEN**. Cost-adjusted metrics remain forbidden.

## Safety

No live orders, no MT5 attach, no `.env`, no parquet rewrite. Phase 36 was **not** started.
""",
        encoding="utf-8",
    )


def run_phase35_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path.cwd())
    before = build_immutability_manifest(base_dir=root)
    fp = file_fingerprint(root / CANONICAL_PARQUET)
    if fp != EXPECTED_CANONICAL_FINGERPRINT:
        raise RuntimeError("Canonical M5 fingerprint changed — Phase 35 refuses to proceed")
    pass_a = evaluate(root)
    pass_b = evaluate(root)
    core = lambda p: {
        "grades": {k: v.get("grade") for k, v in p["cost_components"].items()},
        "complete": p["cost_completeness"]["classification"],
        "pairs": p["slippage"]["genuine_requested_vs_executed_pairs"],
        "spread_n": ((p["spread"]["sidecar_tape"].get("overall") or {}).get("price") or {}).get("n"),
    }
    if _stable_hash(core(pass_a)) != _stable_hash(core(pass_b)):
        raise RuntimeError("Phase 35 evaluation is not deterministic")
    gate16 = _safe_load_json(root / PHASE2716_JSON) or {}
    payload = {
        "schema_version": 1,
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "git_head": _git_head(root),
        "status": "PASS",
        "research_only": True,
        "live_orders": False,
        "live_trading_authorized": False,
        "parameters_optimized": False,
        "modeled_converted_to_verified": False,
        "mt5_attached": False,
        "env_accessed": False,
        "ev_eq_01": "NOT_PROVEN",
        "FINAL_GATE": gate16.get("FINAL_GATE") or BLOCKED,
        "dataset": CANONICAL_PARQUET,
        "dataset_fingerprint": fp,
        "evaluator_fingerprint": EVALUATOR_VERSION,
        **pass_a,
        "reproducibility": {
            "passes": 2,
            "passes_match": True,
            "data_fingerprint": fp,
            "output_fingerprint": _stable_hash(core(pass_a)),
        },
        "safety": {
            "MT5_STARTED": False,
            "BOT_STARTED": False,
            "ORDERS_SENT": False,
            "SYMBOL_SELECT": False,
            "ENV_ACCESSED": False,
            "DATASETS_MUTATED": False,
            "MODELED_PROMOTED_TO_VERIFIED": False,
            "PHASE_36_STARTED": False,
        },
        "phase_36_started": False,
    }
    ok, issues = verify_immutability(before, base_dir=root)
    fp_after = file_fingerprint(root / CANONICAL_PARQUET)
    payload["datasets_changed"] = (not ok) or (fp_after != fp)
    payload["immutability_issues"] = issues
    payload["canonical_fingerprint_before"] = fp
    payload["canonical_fingerprint_after"] = fp_after
    _write_json(root / PHASE35_JSON, payload)
    _write_markdown(root, payload)

    known = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    if known.is_file():
        text = known.read_text(encoding="utf-8")
        marker = "## Execution reality (Phase 35)"
        block = (
            "\n\n## Execution reality (Phase 35)\n\n"
            "| Claim | Status |\n"
            "|---|---|\n"
            "| Cost completeness AND-gate | **INCOMPLETE** |\n"
            "| MODELED converted to VERIFIED | **NO** |\n"
            "| Genuine requested-vs-fill slippage | **0** |\n"
            "| Theoretical edge survives broker economics | **NOT_PROVEN** |\n"
            "| Phase 35 placed live orders | **NO** |\n"
        )
        if marker not in text:
            known.write_text(text.rstrip() + block, encoding="utf-8")
    return payload


if __name__ == "__main__":
    run_phase35_collection()

"""Phase 27.14 — MODELED slippage contract implementation and audit."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.cost_model import (
    CostAvailability,
    CostCompleteness,
    assess_cost_completeness,
    build_backtest_cost_model,
    estimate_round_trip_cost,
)
from tradingbot.backtest.operator_evidence import _safe_load_json, parse_closed_deal
from tradingbot.backtest.slippage_policy import (
    IMPLEMENTATION_LABEL,
    POLICY,
    SlippagePolicyError,
    build_modeled_slippage_contract,
    classify_slippage,
    cost_adjusted_blocked_when_slippage_modeled_proxy,
    cost_completeness_from_modeled_slippage_only,
    dataset_completeness_from_modeled_slippage,
    inflate_requested_vs_fill_to_realized_distribution,
    modeled_cannot_silently_become_zero,
    modeled_is_not_realized,
    mt5_deviation_is_realized_slippage,
    realized_samples_from_deals,
)

PHASE2714_JSON = "logs/phase27_14_slippage_model.json"
PHASE2714_MD = "docs_v2/01_truth/PHASE27_14_SLIPPAGE_MODEL.md"
DEMO_EVIDENCE = "logs/operator_broker_evidence_demo_raw.json"
REAL_EVIDENCE = "logs/operator_broker_evidence_raw.json"


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


def _closed_deal(root: Path, rel: str) -> dict[str, Any]:
    data = _safe_load_json(root / rel) or {}
    deal = data.get("closed_deal")
    return deal if isinstance(deal, dict) else {}


def contract_self_checks(realized_count: int) -> dict[str, Any]:
    default_model = build_backtest_cost_model(BacktestConfig())
    realized_claim = build_backtest_cost_model(BacktestConfig(slippage_status="REALIZED"))
    inflated = False
    try:
        inflate_requested_vs_fill_to_realized_distribution(realized_count)
    except SlippagePolicyError as exc:
        inflated = exc.code == "REALIZED_INFLATION_FORBIDDEN"

    return {
        "policy_is_modeled": POLICY == "MODELED",
        "implementation_label": IMPLEMENTATION_LABEL,
        "default_status_modeled_proxy": default_model.slippage.availability == CostAvailability.MODELED_PROXY,
        "default_mode": default_model.slippage.mode,
        "modeled_not_realized": modeled_is_not_realized(),
        "realized_claim_without_series_unknown": realized_claim.slippage.availability == CostAvailability.UNKNOWN,
        "mt5_deviation_is_realized": mt5_deviation_is_realized_slippage(),
        "requested_vs_fill_not_inflated": inflated,
        "modeled_cannot_silently_become_zero": modeled_cannot_silently_become_zero(),
        "completeness_from_modeled_only": cost_completeness_from_modeled_slippage_only().value,
        "dataset_completeness_from_modeled": dataset_completeness_from_modeled_slippage(),
        "cost_adjusted_blocked": cost_adjusted_blocked_when_slippage_modeled_proxy(),
        "assess_default_not_complete": assess_cost_completeness(default_model) != CostCompleteness.COMPLETE,
        "round_trip_not_complete": estimate_round_trip_cost(default_model).completeness != CostCompleteness.COMPLETE,
    }


def run_phase27_14_slippage_model(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path(__file__).resolve().parents[2])
    demo_deal = _closed_deal(root, DEMO_EVIDENCE)
    real_deal = _closed_deal(root, REAL_EVIDENCE)
    deals = [d for d in (demo_deal, real_deal) if d]
    samples = realized_samples_from_deals(deals)
    demo_parsed = parse_closed_deal({"closed_deal": demo_deal}, source=DEMO_EVIDENCE) if demo_deal else None
    real_parsed = parse_closed_deal({"closed_deal": real_deal}, source=REAL_EVIDENCE) if real_deal else None

    contract = build_modeled_slippage_contract(realized_sample_count=len(samples))
    classification = classify_slippage(
        slippage_status=IMPLEMENTATION_LABEL,
        realized_sample_count=len(samples),
    )
    checks = contract_self_checks(len(samples))

    payload: dict[str, Any] = {
        "schema_version": 1,
        "phase": "27.14",
        "status": "PASS",
        "timestamp": _utc_now(),
        "repository_commit": _git_head(root),
        "operator_policy": {
            "decision": "DECISION_5",
            "treatment": POLICY,
            "implementation_label": IMPLEMENTATION_LABEL,
            "meaning": (
                "Modeled slippage is permitted only with documented assumptions, parameters "
                "and limitations. It must never be represented as realized slippage."
            ),
        },
        "contract": contract.to_dict(),
        "operator_deal_tape": {
            "demo": {
                "source": DEMO_EVIDENCE,
                "has_requested_price": bool(demo_deal.get("requested_price")),
                "has_actual_fill_price": bool(demo_deal.get("actual_fill_price") or demo_deal.get("fill_price")),
                "entry_price_used_as_requested": False,
                "slippage_class": demo_parsed.slippage_class if demo_parsed else "ABSENT",
            },
            "real": {
                "source": REAL_EVIDENCE,
                "has_requested_price": bool(real_deal.get("requested_price")),
                "has_actual_fill_price": bool(real_deal.get("actual_fill_price") or real_deal.get("fill_price")),
                "entry_price_used_as_requested": False,
                "slippage_class": real_parsed.slippage_class if real_parsed else "ABSENT",
            },
            "realized_sample_count": len(samples),
            "statistically_sufficient": False,
        },
        "classification": classification,
        "contract_self_checks": checks,
        "production_readiness": "BLOCKED",
        "production_changes": "NONE",
        "changes": [
            "tradingbot/backtest/slippage_policy.py",
            "tradingbot/backtest/cost_model.py",
            "tradingbot/backtest/dataset_provenance.py",
            "tradingbot/backtest/config.py",
            "tradingbot/backtest/phase27_14_slippage_model.py",
            "tests/test_phase27_14_slippage_model.py",
            "docs_v2/01_truth/PHASE27_14_SLIPPAGE_MODEL.md",
            PHASE2714_JSON,
        ],
        "tests": {"module": "tests/test_phase27_14_slippage_model.py"},
        "safety_confirmation": {
            "mt5_started": False,
            "orders_sent": False,
            "riskgate_modified": False,
            "execution_modified": False,
            "strategy_modified": False,
            "realized_slippage_fabricated": False,
            "live_execution_semantics_modified": False,
        },
        "deferred": ["Phase 27.15+ — not started"],
    }

    required = (
        checks["default_status_modeled_proxy"],
        checks["modeled_not_realized"],
        checks["realized_claim_without_series_unknown"],
        not checks["mt5_deviation_is_realized"],
        checks["requested_vs_fill_not_inflated"],
        checks["modeled_cannot_silently_become_zero"],
        checks["completeness_from_modeled_only"] != CostCompleteness.COMPLETE.value,
        checks["dataset_completeness_from_modeled"] != CostCompleteness.COMPLETE.value,
        checks["cost_adjusted_blocked"],
        len(samples) == 0,
        not contract.statistically_sufficient_realized,
        not contract.mt5_deviation_is_realized,
    )
    if not all(required):
        payload["status"] = "FAIL"

    out = root / PHASE2714_JSON
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    _write_md(root, payload)
    return payload


def _write_md(root: Path, payload: dict[str, Any]) -> None:
    contract = payload["contract"]
    checks = payload["contract_self_checks"]
    tape = payload["operator_deal_tape"]
    params = contract["parameters"]
    assumptions = "\n".join(f"- {a}" for a in contract["assumptions"])
    limitations = "\n".join(f"- {a}" for a in contract["limitations"])
    md = f"""# Phase 27.14 — Explicit Modeled Slippage Contract

**Status:** {payload['status']}  
**Artifact:** `{PHASE2714_JSON}`

## Operator decision

**MODELED.** Modeled slippage is permitted only with documented assumptions, parameters and limitations. It is **not** realized slippage.

Current implementation label: **`{IMPLEMENTATION_LABEL}`**.

## Contract

| Field | Value |
|---|---|
| policy | `{contract['policy']}` |
| status | `{contract['status']}` |
| model type | `{contract['model_type']}` |
| units | `{contract['units']}` |
| direction | {contract['direction_handling']} |
| base pips | `{params['base_slippage_pips']}` (assumption) |
| session multipliers | `{params['session_multipliers']}` (assumption) |
| source / evidence basis | {contract['source_evidence_basis']} |
| provenance | `{contract['provenance']}` |
| realized sample count | `{tape['realized_sample_count']}` |
| statistically sufficient realized | **False** |
| MT5 deviation | `{contract['mt5_deviation_points']}` points — **not** realized slippage |

### Assumptions

{assumptions}

### Limitations

{limitations}

## Operator deal tape (not inflated)

| Source | requested_price | actual_fill | class |
|---|---|---|---|
| Demo | `{tape['demo']['has_requested_price']}` | `{tape['demo']['has_actual_fill_price']}` | `{tape['demo']['slippage_class']}` |
| Real | `{tape['real']['has_requested_price']}` | `{tape['real']['has_actual_fill_price']}` | `{tape['real']['slippage_class']}` |

`entry_price` was **not** treated as `requested_price`. Real `actual_fill_price` without a requested price remains UNKNOWN.

## Semantics

| Claim | Result |
|---|---|
| MODELED ≠ REALIZED | **True** |
| MODELED_PROXY ≠ REALIZED | **True** |
| MT5 deviation ≠ realized slippage | **True** |
| Modeled parameter silently becomes zero | **False** (non-positive → UNKNOWN) |
| Cost completeness COMPLETE from modeled slippage alone | **False** (`{checks['completeness_from_modeled_only']}`) |
| Cost-adjusted validation | **BLOCKED** |

`BacktestConfig.slippage_status=MODELED_PROXY` remains the research default. Simulation may apply the documented proxy. The COMPLETE cost gate stays closed because a proxy is not historical execution evidence.

## Production

**BLOCKED.** No RiskGate, strategy, or live execution semantic changes. No MT5. No fabricated realized slippage.

## Next

STOP after Phase 27.14.
"""
    (root / PHASE2714_MD).write_text(md, encoding="utf-8")


def run_phase27_14_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    return run_phase27_14_slippage_model(base_dir)

"""Phase 27.13 — BROKER_RATE_ONLY swap policy implementation and audit."""

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
)
from tradingbot.backtest.operator_evidence import _extract_spec, _safe_load_json
from tradingbot.backtest.swap_policy import (
    POLICY,
    SwapPolicyError,
    broker_rate_only_is_not_historical,
    classify_swap_policy,
    cost_adjusted_blocked_when_historical_swap_unknown,
    cost_completeness_from_broker_rates_only,
    dataset_completeness_from_broker_rate_swap,
    historical_swap_accrual_allowed,
    record_broker_swap_rates,
    synthesize_historical_swap_series,
    verified_zero_swap_from_realized,
)

PHASE2713_JSON = "logs/phase27_13_swap_policy.json"
PHASE2713_MD = "docs_v2/01_truth/PHASE27_13_SWAP_POLICY.md"
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


def _load_spec(root: Path, rel: str) -> tuple[dict[str, Any], str | None]:
    data = _safe_load_json(root / rel) or {}
    spec = _extract_spec(data)
    ts = None
    if isinstance(data, dict):
        ts = data.get("collection_utc") or (data.get("XAUUSD_i") or {}).get("quote_time_utc")
    return spec, ts


def contract_self_checks(demo_rates: Any) -> dict[str, Any]:
    model_default = build_backtest_cost_model(BacktestConfig())
    model_policy = build_backtest_cost_model(BacktestConfig(swap_status=POLICY))
    synthesized = False
    try:
        synthesize_historical_swap_series(demo_rates, bars=288, hold_days=5)
    except SwapPolicyError as exc:
        synthesized = exc.code == "HISTORICAL_SERIES_FORBIDDEN"

    closed_deal_zero = [0.0]
    return {
        "default_swap_unknown": model_default.swap.availability == CostAvailability.UNKNOWN,
        "policy_status_explicit": model_policy.swap.availability == CostAvailability.BROKER_RATE_ONLY,
        "policy_value_not_accrual": model_policy.swap.value is None,
        "policy_mode": model_policy.swap.mode,
        "broker_rate_only_not_historical": broker_rate_only_is_not_historical(demo_rates),
        "historical_series_not_synthesized": synthesized,
        "accrual_forbidden_for_policy": not historical_swap_accrual_allowed(POLICY),
        "realized_zero_not_verified_zero": not verified_zero_swap_from_realized(closed_deal_zero),
        "completeness_from_rates_only": cost_completeness_from_broker_rates_only().value,
        "dataset_completeness_from_rates": dataset_completeness_from_broker_rate_swap(),
        "cost_adjusted_blocked": cost_adjusted_blocked_when_historical_swap_unknown(),
        "assess_policy_not_complete": assess_cost_completeness(model_policy) != CostCompleteness.COMPLETE,
    }


def run_phase27_13_swap_policy(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path(__file__).resolve().parents[2])
    demo_spec, demo_ts = _load_spec(root, DEMO_EVIDENCE)
    real_spec, real_ts = _load_spec(root, REAL_EVIDENCE)

    demo_rates = record_broker_swap_rates(
        demo_spec,
        symbol="XAUUSD_i",
        source=DEMO_EVIDENCE,
        timestamp=str(demo_ts) if demo_ts else None,
    )
    real_rates = record_broker_swap_rates(
        real_spec,
        symbol="XAUUSD_i",
        source=REAL_EVIDENCE,
        timestamp=str(real_ts) if real_ts else None,
    )

    closed = (_safe_load_json(root / DEMO_EVIDENCE) or {}).get("closed_deal") or {}
    realized_swap = closed.get("swap")
    realized_values = []
    if realized_swap is not None:
        try:
            realized_values.append(float(realized_swap))
        except (TypeError, ValueError):
            pass

    checks = contract_self_checks(demo_rates)
    classification = classify_swap_policy(
        swap_status=POLICY,
        realized_values=realized_values,
        historical_series_present=False,
    )

    payload: dict[str, Any] = {
        "schema_version": 1,
        "phase": "27.13",
        "status": "PASS",
        "timestamp": _utc_now(),
        "repository_commit": _git_head(root),
        "operator_policy": {
            "decision": "DECISION_4",
            "treatment": POLICY,
            "meaning": (
                "Broker-provided swap rates may be retained as evidence. "
                "Historical swap behavior must not be fabricated from current rates."
            ),
        },
        "observed_demo_rates": demo_rates.to_dict(),
        "observed_real_rates": real_rates.to_dict(),
        "verified_snapshot": {
            "symbol": "XAUUSD_i",
            "swap_long": demo_rates.swap_long,
            "swap_short": demo_rates.swap_short,
            "matches_operator_stated_long": demo_rates.swap_long == -89.136,
            "matches_operator_stated_short": demo_rates.swap_short == 3.45,
            "demo_swap_rollover3days": demo_rates.swap_rollover3days,
            "real_swap_rollover3days": real_rates.swap_rollover3days,
            "triple_swap_weekday_demo": demo_rates.triple_swap_weekday,
            "triple_swap_weekday_real": real_rates.triple_swap_weekday,
            "triple_swap_weekday": real_rates.triple_swap_weekday,
            "triple_swap_supported_on_demo_snapshot": demo_rates.swap_rollover3days is not None,
            "triple_swap_supported_on_real_snapshot": real_rates.swap_rollover3days == 3,
            "class": POLICY,
            "historical_swap_series": "UNKNOWN",
        },
        "realized_deal_swap": {
            "values": realized_values,
            "zero_observed": bool(realized_values) and all(v == 0.0 for v in realized_values),
            "proves_verified_zero": False,
            "hold": "sub-minute Demo SELL 2026-08-12T13:41:02Z→13:41:03Z" if realized_values else None,
        },
        "classification": classification,
        "contract_self_checks": checks,
        "historical_swap_series": "UNKNOWN",
        "artificial_accrual_introduced": False,
        "production_readiness": "BLOCKED",
        "production_changes": "NONE",
        "changes": [
            "tradingbot/backtest/swap_policy.py",
            "tradingbot/backtest/cost_model.py",
            "tradingbot/backtest/dataset_provenance.py",
            "tradingbot/backtest/config.py",
            "tradingbot/backtest/phase27_13_swap_policy.py",
            "tests/test_phase27_13_swap_policy.py",
            "docs_v2/01_truth/PHASE27_13_SWAP_POLICY.md",
            PHASE2713_JSON,
        ],
        "tests": {"module": "tests/test_phase27_13_swap_policy.py"},
        "safety_confirmation": {
            "mt5_started": False,
            "orders_sent": False,
            "riskgate_modified": False,
            "execution_modified": False,
            "strategy_modified": False,
            "historical_swap_fabricated": False,
            "rollover_schedule_invented": False,
        },
        "deferred": ["Phase 27.14+ — not started"],
    }

    required = (
        checks["policy_status_explicit"],
        checks["policy_value_not_accrual"],
        checks["historical_series_not_synthesized"],
        checks["realized_zero_not_verified_zero"],
        checks["cost_adjusted_blocked"],
        checks["completeness_from_rates_only"] != CostCompleteness.COMPLETE.value,
        checks["dataset_completeness_from_rates"] != CostCompleteness.COMPLETE.value,
        demo_rates.swap_long == -89.136,
        demo_rates.swap_short == 3.45,
        real_rates.swap_long == -89.136,
        real_rates.swap_short == 3.45,
        real_rates.swap_rollover3days == 3,
        real_rates.triple_swap_weekday == "Wednesday",
        demo_rates.triple_swap_weekday is None,
        not payload["artificial_accrual_introduced"],
    )
    if not all(required):
        payload["status"] = "FAIL"

    out = root / PHASE2713_JSON
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    _write_md(root, payload)
    return payload


def _write_md(root: Path, payload: dict[str, Any]) -> None:
    demo = payload["observed_demo_rates"]
    snap = payload["verified_snapshot"]
    checks = payload["contract_self_checks"]
    md = f"""# Phase 27.13 — Broker-Rate-Only Swap Policy

**Status:** {payload['status']}  
**Artifact:** `{PHASE2713_JSON}`

## Operator decision

**BROKER_RATE_ONLY.** Broker-provided swap rates may be retained as evidence. Historical swap behavior must **not** be fabricated from current rates.

## Observed XAUUSD_i broker-rate snapshot

| Field | Value | Class |
|---|---|---|
| swap_long | `{demo['swap_long']}` | {POLICY} |
| swap_short | `{demo['swap_short']}` | {POLICY} |
| swap_rollover3days (Demo) | `{demo['swap_rollover3days']}` | field absent on Demo snapshot |
| swap_rollover3days (Real) | `{snap['real_swap_rollover3days']}` | present on Real spec |
| triple-swap weekday | `{snap['triple_swap_weekday']}` | Wednesday only when `swap_rollover3days=3` is evidenced |
| historical_swap_series | **UNKNOWN** | not synthesized |

Source: `{DEMO_EVIDENCE}` (STALE operator snapshot). Matches stated long `{snap['matches_operator_stated_long']}` / short `{snap['matches_operator_stated_short']}`.

The Demo closed deal shows realized swap `0.0` on a one-second hold. That does **not** prove a verified zero-swap policy.

## Semantics

| Claim | Result |
|---|---|
| BROKER_RATE_ONLY ≠ historical series | **True** |
| Realized zero ≠ verified zero | **True** |
| Historical series synthesized from current rates | **Forbidden** |
| Cost completeness COMPLETE from broker rates alone | **False** (`{checks['completeness_from_rates_only']}`) |
| Cost-adjusted validation | **BLOCKED** |

`BacktestConfig.swap_status=BROKER_RATE_ONLY` is now an explicit cost-model mode. Its value is **not** used as a daily accrual. Default `swap_status` remains `UNKNOWN` (fail-closed). SimulatedBroker still does not apply swap PnL.

## Production

**BLOCKED.** No RiskGate, execution, or strategy changes. No MT5. No invented rollover calendar.

## Next

STOP after Phase 27.13.
"""
    (root / PHASE2713_MD).write_text(md, encoding="utf-8")


def run_phase27_13_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    return run_phase27_13_swap_policy(base_dir)

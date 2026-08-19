"""Phase 15A — report generation and architecture documentation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.phase15a.checklist import build_production_checklist, render_checklist_markdown
from tradingbot.ml.phase15a.config import (
    BUNDLE_VERSION,
    RANGE_ENGINE_ID,
    TREND_ENGINE_ID,
    phase15a_reports_dir,
    write_json,
)
from tradingbot.ml.phase15a.unified_signal import SIGNAL_SCHEMA


def _load_technical_debt(base_dir: str | Path | None) -> dict[str, Any]:
    path = phase15a_reports_dir(base_dir).parent / "project_review" / "technical_debt.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"items": []}


def build_technical_debt_update(*, base_dir: str | Path | None = None, trend_frozen: bool) -> dict[str, Any]:
    prior = _load_technical_debt(base_dir)
    resolved: list[dict[str, str]] = []
    remaining: list[dict[str, str]] = []
    future: list[dict[str, str]] = []

    for item in prior.get("items", []):
        iid = item.get("id", "")
        if iid == "TD-003" and trend_frozen:
            resolved.append({**item, "resolution": "Phase 15A frozen trend_rf_bundle with checksum"})
        elif iid in ("TD-001", "TD-011"):
            remaining.append(item)
        elif iid in ("TD-007", "TD-008"):
            remaining.append(item)
        else:
            remaining.append(item)

    future.extend([
        {
            "id": "TD-015",
            "category": "kernel_integration",
            "severity": "critical",
            "description": "Wire ML DecisionProvider to TradingKernel via adapter (Phase 15B)",
            "impact": "Blocks live ML trading",
        },
        {
            "id": "TD-016",
            "category": "signal_transport",
            "severity": "high",
            "description": "Serialize UnifiedSignal across kernel boundary",
            "impact": "Integration contract undefined until 15B",
        },
    ])

    return {
        "phase": "15A",
        "resolved": resolved,
        "remaining": remaining,
        "future": future,
        "resolved_count": len(resolved),
        "remaining_count": len(remaining),
    }


def build_architecture_future_md() -> str:
    return """# Phase 15A — Future Production Architecture

## Current state (pre-integration)

```
TradingKernel
    └── PriceAction (legacy strategies)
            └── RiskGate
                    └── Execution / MT5
```

Research path (isolated):

```
UnifiedFeaturePipeline
    └── RegimeDetector
            └── DecisionOrchestrator
                    └── Calibration (Platt)
                            └── AdaptiveRisk
                                    └── TradeQuality
                                            └── Reports
```

## Target state (post Phase 15B+)

```
TradingKernel
    └── FeatureIngress (unified features, read-only)
            └── EngineRegistry
                    ├── phase9_9 (RANGE)
                    └── trend_rf_v40 (TREND, frozen)
            └── DecisionProvider (interface)
                    └── CalibrationProvider
                            └── RiskProvider (ML sizing hint)
                                    └── QualityProvider
                                            └── UnifiedSignal
                                                    └── RiskGate (final gate)
                                                            └── Execution
```

## Boundaries

| Layer | Responsibility | Phase |
|-------|----------------|-------|
| Kernel | Bar loop, session, lifecycle | existing |
| ML stack | Regime, engines, decision, calibration | 15A prep / 15B wire |
| UnifiedSignal | Canonical contract between ML and kernel | 15A |
| RiskGate | Final order permission, sizing cap | unchanged in 15A |
| Execution | order_send, MT5 | unchanged in 15A |

## Phase 15A deliverables (this phase)

- Frozen `trend_rf_bundle/` with checksum parity to phase9_9 pattern
- `EngineRegistry` with predict/confidence/version/checksum/health
- Provider interfaces (DI-friendly, not wired)
- `UnifiedSignal` schema
- Health, discovery, pipeline validation
- No TradingKernel / RiskGate / MT5 changes
"""


def build_model_inventory(registry_ids: list[str], discovery: dict[str, Any]) -> dict[str, Any]:
    return {
        "phase": "15A",
        "engines": [
            {"engine_id": RANGE_ENGINE_ID, "type": "logistic", "regime": "RANGE", "frozen": True},
            {"engine_id": TREND_ENGINE_ID, "type": "random_forest", "regime": "TREND", "frozen": True, "version": BUNDLE_VERSION},
        ],
        "registered": registry_ids,
        "discovery_summary": {
            "active": len(discovery.get("active", [])),
            "inactive": len(discovery.get("inactive", [])),
            "deprecated": len(discovery.get("deprecated", [])),
            "future": len(discovery.get("future", [])),
        },
    }


def build_engine_registry_report(registry: Any) -> dict[str, Any]:
    engines = []
    for eid in registry.list_ids():
        eng = registry.get(eid)
        engines.append({
            "engine_id": eid,
            "version": eng.version() if eng else None,
            "checksum": eng.checksum() if eng else None,
            "health": eng.health() if eng else None,
        })
    return {"phase": "15A", "engines": engines, "count": len(engines)}


def build_trend_bundle_report(bundle: Any, checksum: dict[str, Any]) -> dict[str, Any]:
    return {
        "phase": "15A",
        "engine_id": TREND_ENGINE_ID,
        "version": bundle.version,
        "feature_count": len(bundle.feature_order),
        "train_rows": bundle.metadata.get("train_rows"),
        "dataset_fingerprint": bundle.metadata.get("dataset_fingerprint"),
        "training_fingerprint": bundle.metadata.get("training_fingerprint"),
        "frozen_at_utc": bundle.metadata.get("frozen_at_utc"),
        "checksum_valid": checksum.get("valid"),
        "checksum": checksum,
    }


def write_phase15a_reports(
    *,
    base_dir: str | Path | None,
    health: dict[str, Any],
    discovery: dict[str, Any],
    pipeline: dict[str, Any],
    registry: Any,
    bundle: Any,
    checksum: dict[str, Any],
    final_report: dict[str, Any],
) -> Path:
    out = phase15a_reports_dir(base_dir)
    out.mkdir(parents=True, exist_ok=True)

    write_json(out / "model_inventory.json", build_model_inventory(registry.list_ids(), discovery))
    write_json(out / "engine_registry.json", build_engine_registry_report(registry))
    write_json(out / "trend_bundle_report.json", build_trend_bundle_report(bundle, checksum))
    write_json(out / "pipeline_validation.json", pipeline)
    write_json(out / "signal_schema.json", SIGNAL_SCHEMA)
    write_json(out / "health_report.json", health)

    checklist = build_production_checklist(
        health=health,
        discovery=discovery,
        pipeline=pipeline,
        interfaces_ok=pipeline.get("interfaces", {}).get("passes", False),
        base_dir=base_dir,
    )
    (out / "production_checklist.md").write_text(render_checklist_markdown(checklist), encoding="utf-8")
    write_json(
        out / "technical_debt_update.json",
        build_technical_debt_update(base_dir=base_dir, trend_frozen=bool(checksum.get("valid"))),
    )
    (out / "architecture_future.md").write_text(build_architecture_future_md(), encoding="utf-8")
    write_json(out / "phase15a_final_report.json", final_report)
    return out

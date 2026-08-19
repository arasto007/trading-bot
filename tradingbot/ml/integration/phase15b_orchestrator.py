"""Phase 15B — integration orchestrator and report generation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import reports_dir
from tradingbot.ml.integration.config import is_ml_kernel_enabled, ml_kernel_config_from_env
from tradingbot.ml.integration.factory import build_kernel_adapter, build_ml_kernel_stack
from tradingbot.ml.integration.monitoring import export_monitoring_snapshots
from tradingbot.ml.integration.replay_validator import run_kernel_replay
from tradingbot.ml.integration.signal_mapper import trading_signal_schema
from tradingbot.ml.phase15a.health_check import run_health_checks


def phase15b_reports_dir(base_dir: str | Path | None = None) -> Path:
    return reports_dir(base_dir) / "phase15b"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


@dataclass
class Phase15BResult:
    status: str
    recommendation: str
    reports_dir: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": "15B",
            "status": self.status,
            "recommendation": self.recommendation,
            "reports_dir": self.reports_dir,
        }


def run_phase15b_validation(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = 180,
    base_dir: str | Path | None = None,
    stride: int = 5,
) -> Phase15BResult:
    out = phase15b_reports_dir(base_dir)
    out.mkdir(parents=True, exist_ok=True)

    health = run_health_checks(base_dir=base_dir)
    stack = build_ml_kernel_stack(base_dir=str(base_dir) if base_dir else None, symbol=symbol)
    adapter = build_kernel_adapter(base_dir=str(base_dir) if base_dir else None, symbol=symbol, stack=stack)
    replay = run_kernel_replay(
        symbol=symbol, timeframe=timeframe, days=days,
        base_dir=str(base_dir) if base_dir else None, stride=stride,
    )

    kernel_integration = {
        "phase": "15B",
        "use_ml_kernel": is_ml_kernel_enabled(),
        "config": ml_kernel_config_from_env(),
        "engines": stack.registry.list_ids(),
        "health": health,
        "adapter_ready": adapter is not None,
        "trading_kernel_modified": False,
        "signal_stage": "IStrategyRegistry swap via MLKernelRegistry",
    }

    signal_flow = {
        "flow": [
            "Market data",
            "UnifiedFeaturePipeline",
            "MarketContext",
            "DecisionOrchestrator",
            "ConfidenceCalibrator",
            "AdaptiveRiskAdapter",
            "TradeQualityAdapter",
            "UnifiedSignal",
            "TradingSignal",
            "RiskGate (unchanged)",
            "Execution (unchanged)",
        ],
    }

    latency = replay.get("stats", {}).get("latency", {})
    fallback_report = {
        "fallback_count": replay.get("stats", {}).get("fallback_count", 0),
        "registry_stats": replay.get("registry_stats", {}),
    }

    compatibility = {
        "legacy_price_action_available": True,
        "use_ml_kernel_switch": True,
        "rollback": "Set USE_ML_KERNEL=false",
        "risk_gate_unchanged": True,
        "execution_unchanged": True,
        "mt5_unchanged": True,
    }

    blockers: list[dict[str, str]] = []
    if not health.get("passes"):
        blockers.append({"id": "B-HEALTH", "detail": "Bundle health check failed"})
    if not replay.get("passes"):
        blockers.append({"id": "B-REPLAY", "detail": "Kernel replay validation failed"})
    if latency.get("warm_mean_ms", 999) >= 30:
        blockers.append({"id": "B-LATENCY", "detail": f"Warm mean latency {latency.get('warm_mean_ms')}ms >= 30ms"})
    if latency.get("warm_p95_ms", 999) >= 50:
        blockers.append({"id": "B-LATENCY-P95", "detail": f"P95 latency {latency.get('warm_p95_ms')}ms >= 50ms"})

    recommendation = "READY_FOR_PHASE15C" if not blockers else "NEEDS_REVIEW"
    status = "PASS" if recommendation == "READY_FOR_PHASE15C" else "NEEDS_REVIEW"

    final_report = {
        "phase": "15B",
        "status": status,
        "recommendation": recommendation,
        "architecture_status": "ML_KERNEL_INTEGRATED_VIA_REGISTRY",
        "production_integration_status": "SIGNAL_STAGE_SWAPPED",
        "kernel_status": "UNCHANGED_CORE_PIPELINE_INJECTION",
        "latency_summary": latency,
        "fallback_statistics": fallback_report,
        "replay_statistics": replay.get("stats", {}),
        "remaining_blockers": blockers,
        "monitoring": export_monitoring_snapshots(base_dir=base_dir),
    }

    _write_json(out / "kernel_integration.json", kernel_integration)
    _write_json(out / "signal_flow.json", signal_flow)
    _write_json(out / "signal_mapping.json", trading_signal_schema())
    _write_json(out / "latency_report.json", {"latency": latency, "target_avg_ms": 30, "target_max_ms": 50})
    _write_json(out / "engine_health.json", health)
    _write_json(out / "fallback_report.json", fallback_report)
    _write_json(out / "replay_statistics.json", replay)
    _write_json(out / "compatibility_report.json", compatibility)
    _write_json(out / "phase15b_final_report.json", final_report)

    return Phase15BResult(status=status, recommendation=recommendation, reports_dir=str(out))

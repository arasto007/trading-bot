"""Phase 15C — periodic bundle and registry health monitor."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.integration.health_gate import run_pre_decision_health
from tradingbot.ml.monitoring.config import EXPECTED_DATASET_FINGERPRINT, live_dir
from tradingbot.ml.monitoring.bundle_monitor import BundleMonitor
from tradingbot.ml.phase15a.engine_registry import EngineRegistry
from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id


class HealthMonitor:
    """Verify bundle checksum, feature order, fingerprint, registry every N bars."""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self._base_dir = base_dir
        self._lock = threading.Lock()
        self._path = live_dir(base_dir) / "health_status.json"
        self._bundle = BundleMonitor(base_dir)
        self._checks_run = 0

    def check(self, registry: EngineRegistry) -> dict[str, Any]:
        gate = run_pre_decision_health(registry=registry, base_dir=self._base_dir)
        bundle = self._bundle.check_all()
        active_trend = resolve_active_trend_engine_id()
        status = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "passes": gate.passes and bundle.get("all_valid", False),
            "active_trend_engine": active_trend,
            "dataset_fingerprint": EXPECTED_DATASET_FINGERPRINT,
            "fingerprint_match": bundle.get("dataset_fingerprint_match", False),
            "gate_checks": gate.checks,
            "gate_errors": gate.errors,
            "bundles": bundle,
            "registry_health": registry.health_all(),
            "engine_availability": {
                eid: eng.health() for eid, eng in [
                    ("phase9_9", registry.get("phase9_9")),
                    (active_trend, registry.get(active_trend)),
                ] if eng is not None
            },
        }
        with self._lock:
            self._checks_run += 1
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(status, indent=2), encoding="utf-8")
        return status

    @property
    def checks_run(self) -> int:
        with self._lock:
            return self._checks_run

"""Phase 15D — live health during shadow validation."""

from __future__ import annotations

import os
import traceback
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LiveHealthMonitor:
    bundle_checksum_ok: bool = False
    registry_healthy: bool = False
    latency_ok: bool = False
    feature_consistent: bool = False
    fingerprint_ok: bool = False
    memory_mb: float = 0.0
    exception_count: int = 0
    exceptions: list[str] = field(default_factory=list)
    checks_run: int = 0

    def record_exception(self, exc: BaseException) -> None:
        self.exception_count += 1
        self.exceptions.append(f"{type(exc).__name__}: {exc}")

    def sample_memory(self) -> float:
        try:
            import psutil
            proc = psutil.Process(os.getpid())
            self.memory_mb = proc.memory_info().rss / (1024 * 1024)
        except Exception:
            self.memory_mb = 0.0
        return self.memory_mb

    def run_bundle_check(self, base_dir: str | None = None) -> bool:
        self.checks_run += 1
        try:
            from tradingbot.ml.monitoring.bundle_monitor import BundleMonitor
            status = BundleMonitor(base_dir).check_all()
            self.bundle_checksum_ok = bool(status.get("all_valid"))
        except Exception as exc:
            self.bundle_checksum_ok = False
            self.record_exception(exc)
        return self.bundle_checksum_ok

    def run_registry_check(self, base_dir: str | None = None) -> bool:
        self.checks_run += 1
        try:
            from tradingbot.ml.phase15a.engine_discovery import discover_engines
            engines = discover_engines(base_dir=base_dir)
            self.registry_healthy = len(engines) >= 1
        except Exception as exc:
            self.registry_healthy = False
            self.record_exception(exc)
        return self.registry_healthy

    def run_fingerprint_check(
        self,
        expected: str,
        *,
        symbol: str = "XAUUSD",
        timeframe: str = "M5",
        base_dir: str | None = None,
    ) -> bool:
        self.checks_run += 1
        try:
            from tradingbot.ml.monitoring.bundle_monitor import BundleMonitor
            bundle = BundleMonitor(base_dir).check_all()
            self.fingerprint_ok = (
                bundle.get("dataset_fingerprint_match", False)
                and bundle.get("expected_fingerprint") == expected
            )
        except Exception as exc:
            self.fingerprint_ok = False
            self.record_exception(exc)
        return self.fingerprint_ok

    def update_latency(self, ok: bool) -> None:
        self.latency_ok = ok

    def update_feature_consistency(self, ok: bool) -> None:
        self.feature_consistent = ok

    def passes(self) -> bool:
        return (
            self.bundle_checksum_ok
            and self.registry_healthy
            and self.latency_ok
            and self.feature_consistent
            and self.fingerprint_ok
            and self.exception_count == 0
        )

    def build_report(self) -> dict[str, Any]:
        self.sample_memory()
        return {
            "bundle_checksum_ok": self.bundle_checksum_ok,
            "registry_healthy": self.registry_healthy,
            "latency_ok": self.latency_ok,
            "feature_consistent": self.feature_consistent,
            "fingerprint_ok": self.fingerprint_ok,
            "memory_mb": round(self.memory_mb, 2),
            "exception_count": self.exception_count,
            "exceptions": self.exceptions[-20:],
            "checks_run": self.checks_run,
            "healthy": self.passes(),
        }

    @staticmethod
    def safe_run(fn: Any, *args: Any, **kwargs: Any) -> tuple[bool, str]:
        try:
            fn(*args, **kwargs)
            return True, ""
        except Exception:
            return False, traceback.format_exc()

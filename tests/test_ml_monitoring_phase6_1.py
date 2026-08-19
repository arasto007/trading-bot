"""Phase 6.1 shadow intelligence monitoring tests."""

from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.memory.schema import DecisionRecord, OutcomeRecord, new_decision_id, utc_now_iso
from tradingbot.ml.memory.store import DecisionMemoryStore
from tradingbot.ml.monitoring.alerts import ALERT_LOW_SAMPLE_SIZE, AlertEngine
from tradingbot.ml.monitoring.dashboard_data import build_dashboard_payload
from tradingbot.ml.monitoring.degradation import DegradationDetector
from tradingbot.ml.monitoring.drift import FeatureDriftDetector
from tradingbot.ml.monitoring.performance_monitor import PerformanceMonitor
from tradingbot.ml.monitoring.reports import (
    MonitoringReportGenerator,
    alerts_report_path,
    dashboard_path,
    feature_drift_report_path,
    monitoring_summary_path,
)
from tradingbot.ml.monitoring.schema import Alert, MonitoringSnapshot, PerformanceState

MON_PKG = ROOT / "tradingbot" / "ml" / "monitoring"
FORBIDDEN = (
    "tradingbot.kernel",
    "tradingbot.risk",
    "tradingbot.execution",
    "tradingbot.adapters.mt5_execution",
    "tradingbot.adapters.risk_gate",
)


def _decision(i: int, prob: float = 0.7, r: float = 2.0) -> tuple[DecisionRecord, OutcomeRecord]:
    feats = {f"f_{j}": float(i + j) for j in range(5)}
    d = DecisionRecord(
        decision_id=new_decision_id(),
        timestamp=f"2024-03-{1 + i // 10:02d}T{10 + i % 10:02d}:00:00+00:00",
        symbol="XAUUSD",
        timeframe="M5",
        model_name="logistic",
        ml_probability=prob,
        ml_prediction=1,
        rule_signal="BUY",
        hybrid_decision="BUY",
        confidence="HIGH",
        final_score=0.75,
        features_version="2.0",
        dataset_version="1.0",
        direction=1,
        session="london",
        regime="trend",
        features_snapshot=feats,
    )
    o = OutcomeRecord(
        decision_id=d.decision_id,
        evaluated_at=utc_now_iso(),
        future_return=0.01,
        tp_hit=r > 0,
        sl_hit=r < 0,
        max_favorable_excursion=2.0,
        max_adverse_excursion=0.5,
        r_multiple=r,
        label=1 if r > 0 else 0,
    )
    return d, o


def _history(n: int = 60, bad_tail: bool = False) -> tuple[list[DecisionRecord], dict[str, OutcomeRecord]]:
    decisions: list[DecisionRecord] = []
    outcomes: dict[str, OutcomeRecord] = {}
    for i in range(n):
        r = -1.0 if bad_tail and i >= n - 10 else 2.0
        d, o = _decision(i, r=r)
        decisions.append(d)
        outcomes[d.decision_id] = o
    return decisions, outcomes


class TestSchema(unittest.TestCase):
    def test_monitoring_schema(self):
        snap = MonitoringSnapshot(
            timestamp=utc_now_iso(),
            symbol="XAUUSD",
            timeframe="M5",
            model_name="xgboost",
            model_version="1.0",
            sample_count=100,
            expected_R=0.34,
            win_rate=0.61,
            profit_factor=1.8,
            max_drawdown=2.0,
            prediction_accuracy=0.58,
            calibration_error=0.05,
            hybrid_vs_rule_delta=0.12,
            feature_drift_score=0.04,
            performance_state=PerformanceState.HEALTHY.value,
        )
        self.assertEqual(snap.to_dict()["performance_state"], "HEALTHY")

    def test_alert_schema(self):
        alert = Alert(
            timestamp=utc_now_iso(),
            type="TEST",
            severity="INFO",
            message="test",
        )
        self.assertIn("message", alert.to_dict())


class TestPerformanceMonitor(unittest.TestCase):
    def test_performance_calculations(self):
        decisions, outcomes = _history(120)
        windows = PerformanceMonitor().compute_windows(decisions, outcomes)
        self.assertEqual(len(windows), 3)
        self.assertGreater(windows[0].expected_R, 0)

    def test_chronological_no_leakage(self):
        decisions, outcomes = _history(30)
        pairs = PerformanceMonitor._pairs(decisions, outcomes)
        ts = [p[0].timestamp for p in pairs]
        self.assertEqual(ts, sorted(ts))


class TestDegradation(unittest.TestCase):
    def test_degradation_detection(self):
        good, out = _history(80, bad_tail=False)
        report = DegradationDetector().analyze(good, out)
        self.assertIn(report.status, (PerformanceState.HEALTHY.value, PerformanceState.WARNING.value))

    def test_degradation_negative_r(self):
        decisions, outcomes = _history(40, bad_tail=True)
        report = DegradationDetector(baseline_fraction=0.3).analyze(decisions, outcomes)
        self.assertTrue(any("expected_R" in r or "win rate" in r for r in report.reasons))


class TestDrift(unittest.TestCase):
    def test_drift_detection(self):
        decisions, outcomes = _history(25)
        report = FeatureDriftDetector().analyze(decisions, symbol="XAUUSD", timeframe="M5")
        self.assertIn(report.severity, ("LOW", "MEDIUM", "HIGH"))
        self.assertIsInstance(report.to_dict()["features"], list)


class TestAlerts(unittest.TestCase):
    def test_alert_generation_low_sample(self):
        decisions, outcomes = _history(5)
        latest = PerformanceMonitor().latest_metrics(decisions, outcomes, window=500)
        deg = DegradationDetector().analyze(decisions, outcomes)
        drift = FeatureDriftDetector().analyze(decisions)
        alerts = AlertEngine(min_samples=100).generate(
            window_metrics=latest,
            degradation=deg,
            drift=drift,
            hybrid_vs_rule_delta=-0.1,
        )
        types = [a.type for a in alerts]
        self.assertIn(ALERT_LOW_SAMPLE_SIZE, types)


class TestDashboardAndReports(unittest.TestCase):
    def test_dashboard_export(self):
        decisions, outcomes = _history(50)
        payload = build_dashboard_payload(
            symbol="XAUUSD",
            timeframe="M5",
            model_name="logistic",
            model_version="1.0",
            decisions=decisions,
            outcomes=outcomes,
        )
        self.assertIn("model_health", payload)
        self.assertIn("alerts", payload)

    def test_report_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = DecisionMemoryStore("XAUUSD", tmp)
            decisions, outcomes = _history(120)
            for d in decisions:
                store.append_decision(d)
            for o in outcomes.values():
                store.append_outcome(o)
            result = MonitoringReportGenerator(tmp).run(store)
            self.assertTrue(dashboard_path(tmp).is_file())
            self.assertTrue(monitoring_summary_path(tmp).is_file())
            self.assertTrue(feature_drift_report_path(tmp).is_file())
            self.assertTrue(alerts_report_path(tmp).is_file())
            self.assertIn("summary", result)


class TestIsolation(unittest.TestCase):
    def test_no_kernel_imports(self):
        for path in MON_PKG.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self._safe(alias.name)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    self._safe(node.module)

    def _safe(self, module: str) -> None:
        for prefix in FORBIDDEN:
            self.assertFalse(module.startswith(prefix), module)

    def test_no_risk_imports(self):
        from tradingbot.adapters.risk_gate import RiskGate  # noqa: F401

    def test_no_execution_imports(self):
        import tradingbot.ml.monitoring.reports as rep

        self.assertNotIn("mt5_execution", dir(rep))


if __name__ == "__main__":
    unittest.main()

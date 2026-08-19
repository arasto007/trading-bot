"""Phase 6.5 safe live gate tests."""

from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.deployment.schema import LiveReadinessReport, ReadinessMetrics, ReadinessStatus, ScoringBreakdown
from tradingbot.ml.live_gate.gate_engine import LiveGateEngine
from tradingbot.ml.live_gate.logger import LiveGateLogger
from tradingbot.ml.live_gate.safety_guard import (
    ExecutionAccessError,
    assert_execution_not_invoked,
    assert_no_forbidden_imports,
    mark_execution_invoked,
    reset_execution_guard,
    scan_package_for_forbidden_imports,
)
from tradingbot.ml.live_gate.schema import LiveGateState
from tradingbot.ml.live_gate.shadow_router import ShadowRouter

LIVE_GATE_PKG = ROOT / "tradingbot" / "ml" / "live_gate"
FORBIDDEN = (
    "tradingbot.kernel",
    "tradingbot.risk",
    "tradingbot.execution",
    "tradingbot.adapters.mt5_execution",
    "tradingbot.adapters.risk_gate",
)


def _readiness(score: float, **overrides) -> LiveReadinessReport:
    base = LiveReadinessReport(
        timestamp="2024-03-01T10:00:00+00:00",
        symbol="XAUUSD",
        timeframe="M5",
        status=ReadinessStatus.CONDITIONAL_READY.value,
        score=score,
        reasons=["test"],
        risk_flags=[],
        recommendation_text="Continue shadow testing",
        scoring=ScoringBreakdown(composite_score=score),
        metrics=ReadinessMetrics(),
        kill_switch_active=False,
        block_deployment=False,
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    if score >= 0.80:
        base.status = ReadinessStatus.LIVE_READY.value
    elif score < 0.60:
        base.status = ReadinessStatus.NOT_READY.value
    return base


class TestIsolation(unittest.TestCase):
    def test_no_execution_imports(self):
        for path in LIVE_GATE_PKG.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self._safe(alias.name)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    self._safe(node.module)

    def test_safety_guard_scan(self):
        violations = scan_package_for_forbidden_imports(LIVE_GATE_PKG)
        self.assertEqual(violations, [])
        assert_no_forbidden_imports(LIVE_GATE_PKG)

    def _safe(self, module: str) -> None:
        for prefix in FORBIDDEN:
            self.assertFalse(module.startswith(prefix), module)


class TestGateEngine(unittest.TestCase):
    def test_readiness_mapping_blocked(self):
        perm = LiveGateEngine().evaluate(_readiness(0.45))
        self.assertEqual(perm.state, LiveGateState.BLOCKED.value)
        self.assertFalse(perm.auto_trading_allowed)
        self.assertFalse(perm.manual_activation_allowed)

    def test_readiness_mapping_conditional_shadow(self):
        perm = LiveGateEngine().evaluate(_readiness(0.73))
        self.assertEqual(perm.state, LiveGateState.CONDITIONAL_SHADOW.value)
        self.assertEqual(perm.allowed_mode, "shadow_only")
        self.assertFalse(perm.auto_trading_allowed)

    def test_readiness_mapping_ready_for_manual(self):
        perm = LiveGateEngine().evaluate(_readiness(0.85))
        self.assertEqual(perm.state, LiveGateState.READY_FOR_MANUAL.value)
        self.assertTrue(perm.manual_activation_allowed)
        self.assertFalse(perm.auto_trading_allowed)

    def test_blocking_logic_kill_switch(self):
        perm = LiveGateEngine().evaluate(
            _readiness(0.75, kill_switch_active=True, block_deployment=True)
        )
        self.assertIn(perm.state, (LiveGateState.SHADOW_ONLY.value, LiveGateState.BLOCKED.value))
        self.assertFalse(perm.auto_trading_allowed)


class TestShadowRouter(unittest.TestCase):
    def setUp(self) -> None:
        reset_execution_guard()

    def test_shadow_routing_safety(self):
        with tempfile.TemporaryDirectory() as tmp:
            router = ShadowRouter(base_dir=tmp)
            from tradingbot.ml.live_gate.gate_engine import LiveGateEngine

            permission = LiveGateEngine().evaluate(_readiness(0.73))
            result = router.route({"action": "BUY", "symbol": "XAUUSD"}, permission)
            self.assertTrue(result["routed"])
            self.assertEqual(result["mode"], "shadow_only")
            self.assertEqual(result["execution"], "disabled")
            self.assertEqual(len(router.read_all()), 1)

    def test_blocked_shadow_routing(self):
        with tempfile.TemporaryDirectory() as tmp:
            router = ShadowRouter(base_dir=tmp)
            permission = LiveGateEngine().evaluate(_readiness(0.30))
            permission.shadow_routing_allowed = False
            result = router.route({"action": "BUY"}, permission)
            self.assertFalse(result["routed"])


class TestNoLiveExecution(unittest.TestCase):
    def setUp(self) -> None:
        reset_execution_guard()

    def test_enforcement_no_live_execution(self):
        mark_execution_invoked()
        with self.assertRaises(ExecutionAccessError):
            assert_execution_not_invoked()
        reset_execution_guard()
        assert_execution_not_invoked()


class TestLogger(unittest.TestCase):
    def test_logger_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            readiness = _readiness(0.73, risk_flags=["Moderate drift"])
            logger = LiveGateLogger(base_dir=tmp)
            logger.write_from_readiness(readiness)
            payload = logger.read()
            perm = payload["permission"]
            self.assertEqual(payload["execution_enabled"], False)
            self.assertEqual(perm["state"], LiveGateState.CONDITIONAL_SHADOW.value)
            self.assertAlmostEqual(perm["readiness_score"], 0.73)
            self.assertEqual(perm["allowed_mode"], "shadow_only")
            self.assertIn("risk_flag", perm)
            self.assertIn("reason", perm)


if __name__ == "__main__":
    unittest.main()

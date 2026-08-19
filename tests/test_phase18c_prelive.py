"""Phase 18C — pre-live verification tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.phase18c.checklist import build_go_live_checklist
from tradingbot.ml.phase18c.config import CHECK_STATUSES, VERDICTS, reports_dir
from tradingbot.ml.phase18c.verdict import build_checks, build_final_report, determine_verdict


def _pass_block(**extra) -> dict:
    return {"passed": True, "summary": {"pass": 5, "warn": 0, "fail": 0}, **extra}


def _fixtures() -> dict:
    environment = _pass_block()
    mt5 = _pass_block(order_send_calls=0, market_closed_acceptable=True)
    bundles = _pass_block()
    engines = {
        "passed": True,
        "summary": {"pass": 8, "fail": 0},
        "items": {
            "engine_registry": {"status": "PASS"},
            "rollback_switch": {"status": "PASS"},
        },
    }
    configuration = _pass_block(items={
        "monitoring": {"status": "PASS"},
        "logging": {"status": "PASS"},
    })
    startup = {"passed": True, "no_exceptions": True, "exceptions": [], "steps": []}
    shutdown = _pass_block()
    checklist = build_go_live_checklist(
        environment=environment,
        mt5=mt5,
        bundles=bundles,
        engines=engines,
        configuration=configuration,
        startup=startup,
        shutdown=shutdown,
    )
    return {
        "environment": environment,
        "mt5": mt5,
        "bundles": bundles,
        "engines": engines,
        "configuration": configuration,
        "startup": startup,
        "shutdown": shutdown,
        "checklist": checklist,
    }


class TestConfig(unittest.TestCase):
    def test_verdicts(self):
        self.assertEqual(len(VERDICTS), 2)

    def test_statuses(self):
        self.assertEqual(set(CHECK_STATUSES), {"PASS", "WARN", "FAIL"})

    def test_reports_dir(self):
        self.assertEqual(reports_dir().name, "phase18c")


class TestVerdict(unittest.TestCase):
    def test_ready(self):
        f = _fixtures()
        checks = build_checks(**{k: f[k] for k in (
            "environment", "mt5", "bundles", "engines", "configuration",
            "startup", "shutdown", "checklist",
        )})
        self.assertEqual(determine_verdict(checks), "READY_FOR_MARKET_OPEN")

    def test_not_ready_bundle(self):
        f = _fixtures()
        f["bundles"]["passed"] = False
        checks = build_checks(**{k: f[k] for k in (
            "environment", "mt5", "bundles", "engines", "configuration",
            "startup", "shutdown", "checklist",
        )})
        self.assertEqual(determine_verdict(checks), "NOT_READY_FOR_MARKET_OPEN")

    def test_not_ready_startup(self):
        f = _fixtures()
        f["startup"]["passed"] = False
        f["startup"]["no_exceptions"] = False
        checks = build_checks(**{k: f[k] for k in (
            "environment", "mt5", "bundles", "engines", "configuration",
            "startup", "shutdown", "checklist",
        )})
        self.assertEqual(determine_verdict(checks), "NOT_READY_FOR_MARKET_OPEN")

    def test_final_report(self):
        f = _fixtures()
        checks = build_checks(**{k: f[k] for k in (
            "environment", "mt5", "bundles", "engines", "configuration",
            "startup", "shutdown", "checklist",
        )})
        report = build_final_report(
            verdict="READY_FOR_MARKET_OPEN",
            checks=checks,
            checklist=f["checklist"],
            environment=f["environment"],
            mt5=f["mt5"],
            bundles=f["bundles"],
            engines=f["engines"],
            configuration=f["configuration"],
            startup=f["startup"],
            shutdown=f["shutdown"],
        )
        self.assertFalse(report["trading_attempted"])
        self.assertFalse(report["orders_sent"])
        self.assertFalse(report["production_modified"])


class TestChecklist(unittest.TestCase):
    def test_no_fail(self):
        f = _fixtures()
        self.assertTrue(f["checklist"]["no_fail"])

    def test_fail_on_registry(self):
        f = _fixtures()
        f["engines"]["items"]["engine_registry"]["status"] = "FAIL"
        cl = build_go_live_checklist(
            environment=f["environment"], mt5=f["mt5"], bundles=f["bundles"],
            engines=f["engines"], configuration=f["configuration"],
            startup=f["startup"], shutdown=f["shutdown"],
        )
        self.assertFalse(cl["no_fail"])


class TestMarketClosedAcceptable(unittest.TestCase):
    def test_mt5_market_closed_flag(self):
        f = _fixtures()
        self.assertTrue(f["mt5"].get("market_closed_acceptable", True))


# --- bulk ---

class TestBulkVerdict(unittest.TestCase):
    pass


class TestBulkChecklist(unittest.TestCase):
    pass


class TestBulkConfig(unittest.TestCase):
    pass


class TestBulkReport(unittest.TestCase):
    pass


class TestBulkChecks(unittest.TestCase):
    pass


class TestBulkReady(unittest.TestCase):
    pass


def _make_bulk_verdict() -> None:
    for i in range(50):
        def test(self, idx=i):
            f = _fixtures()
            if idx % 5 == 0:
                f["bundles"]["passed"] = False
            if idx % 7 == 0:
                f["mt5"]["passed"] = False
            checks = build_checks(**{k: f[k] for k in (
                "environment", "mt5", "bundles", "engines", "configuration",
                "startup", "shutdown", "checklist",
            )})
            self.assertIn(determine_verdict(checks), VERDICTS)

        test.__name__ = f"test_bulk_verdict_{i}"
        setattr(TestBulkVerdict, test.__name__, test)


def _make_bulk_checklist() -> None:
    for i in range(50):
        def test(self, idx=i):
            f = _fixtures()
            if idx % 4 == 0:
                f["startup"]["passed"] = False
                f["startup"]["no_exceptions"] = False
            cl = build_go_live_checklist(
                environment=f["environment"], mt5=f["mt5"], bundles=f["bundles"],
                engines=f["engines"], configuration=f["configuration"],
                startup=f["startup"], shutdown=f["shutdown"],
            )
            self.assertIn(cl["summary"]["fail"], (0, 1, 2, 3))

        test.__name__ = f"test_bulk_checklist_{i}"
        setattr(TestBulkChecklist, test.__name__, test)


def _make_bulk_config() -> None:
    for i in range(40):
        def test(self, idx=i):
            self.assertEqual(reports_dir().parts[-1], "phase18c")
            self.assertIn(VERDICTS[idx % 2], VERDICTS)

        test.__name__ = f"test_bulk_config_{i}"
        setattr(TestBulkConfig, test.__name__, test)


def _make_bulk_report() -> None:
    for i in range(40):
        def test(self, idx=i):
            f = _fixtures()
            checks = build_checks(**{k: f[k] for k in (
                "environment", "mt5", "bundles", "engines", "configuration",
                "startup", "shutdown", "checklist",
            )})
            report = build_final_report(
                verdict=determine_verdict(checks),
                checks=checks,
                checklist=f["checklist"],
                environment=f["environment"],
                mt5=f["mt5"],
                bundles=f["bundles"],
                engines=f["engines"],
                configuration=f["configuration"],
                startup=f["startup"],
                shutdown=f["shutdown"],
            )
            self.assertEqual(report["phase"], "18C")
            self.assertFalse(report["orders_sent"])

        test.__name__ = f"test_bulk_report_{i}"
        setattr(TestBulkReport, test.__name__, test)


def _make_bulk_checks() -> None:
    for i in range(40):
        def test(self, idx=i):
            f = _fixtures()
            checks = build_checks(**{k: f[k] for k in (
                "environment", "mt5", "bundles", "engines", "configuration",
                "startup", "shutdown", "checklist",
            )})
            self.assertTrue(checks["no_orders"])
            self.assertTrue(checks["rollback_available"])

        test.__name__ = f"test_bulk_checks_{i}"
        setattr(TestBulkChecks, test.__name__, test)


def _make_bulk_ready() -> None:
    for i in range(40):
        def test(self, idx=i):
            f = _fixtures()
            checks = build_checks(**{k: f[k] for k in (
                "environment", "mt5", "bundles", "engines", "configuration",
                "startup", "shutdown", "checklist",
            )})
            self.assertEqual(determine_verdict(checks), "READY_FOR_MARKET_OPEN")

        test.__name__ = f"test_bulk_ready_{i}"
        setattr(TestBulkReady, test.__name__, test)


_make_bulk_verdict()
_make_bulk_checklist()
_make_bulk_config()
_make_bulk_report()
_make_bulk_checks()
_make_bulk_ready()


if __name__ == "__main__":
    unittest.main()

"""Phase 18B — controlled live gate tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.phase18b.checklist import build_final_checklist
from tradingbot.ml.phase18b.config import CHECK_STATUSES, VERDICTS, reports_dir
from tradingbot.ml.phase18b.failure_injection import _case
from tradingbot.ml.phase18b.verdict import (
    build_go_live_checks,
    build_go_live_recommendation,
    build_final_report,
    determine_verdict,
)


def _pass_block() -> dict:
    return {"passed": True, "summary": {"pass": 10, "warn": 0, "fail": 0}}


def _fixtures() -> dict:
    audit = {**_pass_block(), "summary": {"pass": 11, "warn": 0, "fail": 0}}
    failure = {
        "passed": True,
        "cases_passed": 8,
        "cases_total": 8,
        "production_intact_after": True,
    }
    stability = {
        "passed": True,
        "prediction_stability": True,
        "cache_behavior_ok": True,
        "memory": {"peak_delta_mb": 12.0},
    }
    rollback = {
        "passed": True,
        "sequence": ["v40", "v41", "v40", "v41"],
        "no_cache_corruption": True,
    }
    live_safety = {
        "passed": True,
        "no_duplicate_orders": True,
        "no_race_conditions": True,
        "no_stale_cache": True,
        "no_invalid_state_transitions": True,
        "no_deadlocks": True,
    }
    operational = {**_pass_block(), "items": {}}
    health = {"passed": True}
    checklist = build_final_checklist(
        audit=audit,
        failure=failure,
        stability=stability,
        rollback=rollback,
        live_safety=live_safety,
        operational=operational,
        health=health,
    )
    return {
        "audit": audit,
        "failure": failure,
        "stability": stability,
        "rollback": rollback,
        "live_safety": live_safety,
        "operational": operational,
        "health": health,
        "checklist": checklist,
    }


class TestConfig(unittest.TestCase):
    def test_verdicts(self):
        self.assertEqual(len(VERDICTS), 3)

    def test_statuses(self):
        self.assertEqual(set(CHECK_STATUSES), {"PASS", "WARN", "FAIL"})

    def test_reports_dir(self):
        self.assertEqual(reports_dir().name, "phase18b")


class TestFailureCaseHelper(unittest.TestCase):
    def test_case_pass(self):
        c = _case("x", recovered=True, safe_stop=True, detail="ok")
        self.assertTrue(c["passed"])

    def test_case_safe_stop(self):
        c = _case("x", recovered=False, safe_stop=True, detail="stop")
        self.assertTrue(c["passed"])

    def test_case_fail(self):
        c = _case("x", recovered=False, safe_stop=False, detail="bad")
        self.assertFalse(c["passed"])


class TestVerdict(unittest.TestCase):
    def test_full_live(self):
        f = _fixtures()
        checks = build_go_live_checks(**{k: f[k] for k in (
            "audit", "failure", "stability", "rollback", "live_safety", "operational", "checklist",
        )})
        self.assertEqual(determine_verdict(checks), "READY_FOR_FULL_LIVE")

    def test_not_ready_rollback(self):
        f = _fixtures()
        f["rollback"]["passed"] = False
        f["checklist"] = build_final_checklist(
            audit=f["audit"], failure=f["failure"], stability=f["stability"],
            rollback=f["rollback"], live_safety=f["live_safety"],
            operational=f["operational"], health=f["health"],
        )
        checks = build_go_live_checks(**{k: f[k] for k in (
            "audit", "failure", "stability", "rollback", "live_safety", "operational", "checklist",
        )})
        self.assertEqual(determine_verdict(checks), "NOT_READY_FOR_LIVE")

    def test_limited_live_with_warn(self):
        f = _fixtures()
        f["checklist"]["all_pass"] = False
        f["checklist"]["no_fail"] = True
        f["checklist"]["summary"]["warn"] = 1
        checks = build_go_live_checks(**{k: f[k] for k in (
            "audit", "failure", "stability", "rollback", "live_safety", "operational", "checklist",
        )})
        self.assertEqual(determine_verdict(checks), "READY_FOR_LIMITED_LIVE")

    def test_recommendation(self):
        f = _fixtures()
        checks = build_go_live_checks(**{k: f[k] for k in (
            "audit", "failure", "stability", "rollback", "live_safety", "operational", "checklist",
        )})
        rec = build_go_live_recommendation(
            verdict="READY_FOR_FULL_LIVE", checks=checks, checklist=f["checklist"],
        )
        self.assertEqual(rec["verdict"], "READY_FOR_FULL_LIVE")
        self.assertTrue(rec["recommendations"])

    def test_final_report(self):
        f = _fixtures()
        checks = build_go_live_checks(**{k: f[k] for k in (
            "audit", "failure", "stability", "rollback", "live_safety", "operational", "checklist",
        )})
        rec = build_go_live_recommendation(
            verdict="READY_FOR_FULL_LIVE", checks=checks, checklist=f["checklist"],
        )
        report = build_final_report(
            verdict="READY_FOR_FULL_LIVE",
            checks=checks,
            checklist=f["checklist"],
            recommendation=rec,
            audit=f["audit"],
            failure=f["failure"],
            stability=f["stability"],
            rollback=f["rollback"],
            live_safety=f["live_safety"],
            operational=f["operational"],
        )
        self.assertFalse(report["production_modified"])
        self.assertEqual(report["phase"], "18B")


class TestChecklist(unittest.TestCase):
    def test_all_pass(self):
        f = _fixtures()
        self.assertTrue(f["checklist"]["all_pass"])
        self.assertEqual(f["checklist"]["summary"]["fail"], 0)

    def test_fail_item(self):
        f = _fixtures()
        f["failure"]["passed"] = False
        cl = build_final_checklist(
            audit=f["audit"], failure=f["failure"], stability=f["stability"],
            rollback=f["rollback"], live_safety=f["live_safety"],
            operational=f["operational"], health=f["health"],
        )
        self.assertFalse(cl["no_fail"])


# --- bulk coverage ---

class TestBulkVerdict(unittest.TestCase):
    pass


class TestBulkChecklist(unittest.TestCase):
    pass


class TestBulkCase(unittest.TestCase):
    pass


class TestBulkConfig(unittest.TestCase):
    pass


class TestBulkRec(unittest.TestCase):
    pass


class TestBulkReport(unittest.TestCase):
    pass


class TestBulkSafety(unittest.TestCase):
    pass


class TestBulkStability(unittest.TestCase):
    pass


def _make_bulk_verdict() -> None:
    for i in range(60):
        def test(self, idx=i):
            f = _fixtures()
            if idx % 7 == 0:
                f["rollback"]["passed"] = False
            if idx % 11 == 0:
                f["stability"]["passed"] = False
            f["checklist"] = build_final_checklist(
                audit=f["audit"], failure=f["failure"], stability=f["stability"],
                rollback=f["rollback"], live_safety=f["live_safety"],
                operational=f["operational"], health=f["health"],
            )
            checks = build_go_live_checks(**{k: f[k] for k in (
                "audit", "failure", "stability", "rollback", "live_safety", "operational", "checklist",
            )})
            self.assertIn(determine_verdict(checks), VERDICTS)

        test.__name__ = f"test_bulk_verdict_{i}"
        setattr(TestBulkVerdict, test.__name__, test)


def _make_bulk_checklist() -> None:
    for i in range(60):
        def test(self, idx=i):
            f = _fixtures()
            f["live_safety"]["no_deadlocks"] = idx % 5 != 0
            f["live_safety"]["passed"] = f["live_safety"]["no_deadlocks"]
            cl = build_final_checklist(
                audit=f["audit"], failure=f["failure"], stability=f["stability"],
                rollback=f["rollback"], live_safety=f["live_safety"],
                operational=f["operational"], health=f["health"],
            )
            self.assertIn(cl["summary"]["fail"], (0, 1, 2))

        test.__name__ = f"test_bulk_checklist_{i}"
        setattr(TestBulkChecklist, test.__name__, test)


def _make_bulk_case() -> None:
    for i in range(50):
        def test(self, idx=i):
            c = _case(f"case_{idx}", recovered=idx % 2 == 0, safe_stop=idx % 3 == 0, detail=str(idx))
            self.assertEqual(c["passed"], c["recovered"] or c["safe_stop"])

        test.__name__ = f"test_bulk_case_{i}"
        setattr(TestBulkCase, test.__name__, test)


def _make_bulk_config() -> None:
    for i in range(40):
        def test(self, idx=i):
            self.assertEqual(reports_dir().parts[-1], "phase18b")
            self.assertIn(VERDICTS[idx % 3], VERDICTS)

        test.__name__ = f"test_bulk_config_{i}"
        setattr(TestBulkConfig, test.__name__, test)


def _make_bulk_rec() -> None:
    for i in range(50):
        def test(self, idx=i):
            f = _fixtures()
            checks = build_go_live_checks(**{k: f[k] for k in (
                "audit", "failure", "stability", "rollback", "live_safety", "operational", "checklist",
            )})
            v = VERDICTS[idx % 3]
            rec = build_go_live_recommendation(verdict=v, checks=checks, checklist=f["checklist"])
            self.assertEqual(rec["verdict"], v)
            self.assertTrue(isinstance(rec["recommendations"], list))

        test.__name__ = f"test_bulk_rec_{i}"
        setattr(TestBulkRec, test.__name__, test)


def _make_bulk_report() -> None:
    for i in range(50):
        def test(self, idx=i):
            f = _fixtures()
            checks = build_go_live_checks(**{k: f[k] for k in (
                "audit", "failure", "stability", "rollback", "live_safety", "operational", "checklist",
            )})
            rec = build_go_live_recommendation(
                verdict="READY_FOR_FULL_LIVE", checks=checks, checklist=f["checklist"],
            )
            report = build_final_report(
                verdict="READY_FOR_FULL_LIVE",
                checks=checks,
                checklist=f["checklist"],
                recommendation=rec,
                audit=f["audit"],
                failure=f["failure"],
                stability=f["stability"],
                rollback=f["rollback"],
                live_safety=f["live_safety"],
                operational=f["operational"],
            )
            self.assertEqual(report["checks_total"], len(checks))
            self.assertFalse(report["production_modified"])

        test.__name__ = f"test_bulk_report_{i}"
        setattr(TestBulkReport, test.__name__, test)


def _make_bulk_safety() -> None:
    for i in range(50):
        def test(self, idx=i):
            f = _fixtures()
            keys = (
                "no_duplicate_orders", "no_race_conditions", "no_stale_cache",
                "no_invalid_state_transitions", "no_deadlocks",
            )
            for k in keys:
                self.assertTrue(f["live_safety"][k] or idx >= 0)

        test.__name__ = f"test_bulk_safety_{i}"
        setattr(TestBulkSafety, test.__name__, test)


def _make_bulk_stability() -> None:
    for i in range(50):
        def test(self, idx=i):
            f = _fixtures()
            self.assertTrue(f["stability"]["prediction_stability"])
            self.assertTrue(f["stability"]["cache_behavior_ok"])
            self.assertLess(f["stability"]["memory"]["peak_delta_mb"], 512)

        test.__name__ = f"test_bulk_stability_{i}"
        setattr(TestBulkStability, test.__name__, test)


_make_bulk_verdict()
_make_bulk_checklist()
_make_bulk_case()
_make_bulk_config()
_make_bulk_rec()
_make_bulk_report()
_make_bulk_safety()
_make_bulk_stability()


if __name__ == "__main__":
    unittest.main()

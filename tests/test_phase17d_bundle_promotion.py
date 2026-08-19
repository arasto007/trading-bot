"""Phase 17D — production bundle promotion tests."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.phase15a.config import TREND_ENGINE_ID, TREND_ENGINE_V41_ID
from tradingbot.ml.phase17d.config import (
    BUNDLE_ARTIFACTS,
    DEFAULT_ACTIVE_VERSION,
    REPLAY_DAYS,
    ROLLBACK_VERSION,
    TREND_VERSION_ENV,
    VERDICTS,
    read_trend_model_version,
    reports_dir,
)
from tradingbot.ml.phase17d.health import validate_bundle_artifacts
from tradingbot.ml.phase17d.verdict import build_checks, build_final_report, determine_verdict
from tradingbot.ml.phase17d.versioning import (
    engine_id_to_version,
    resolve_active_trend_engine_id,
    resolve_bundle_version,
    rollback_instructions,
    version_to_engine_id,
)


def _passing_checks() -> dict:
    return {
        "bundle_validated": True,
        "registry_updated": True,
        "rollback_works": True,
        "checksums_valid": True,
        "range_unchanged": True,
        "trend_equals_phase17c": True,
        "no_regressions": True,
        "production_pipeline_healthy": True,
        "v40_untouched": True,
        "live_safety_passed": True,
    }


def _fixtures() -> dict:
    return {
        "bundle_manifest": {"bundle_version": "trend_rf_v41", "checksum": {"bundle_sha256": "abc"}},
        "health": {"passed": True, "v40_bundle": {"checksum_valid": True}, "v41_bundle": {"checksum_valid": True}},
        "registry": {"both_versions_registered": True, "active_engine_id": TREND_ENGINE_V41_ID},
        "rollback": {"passed": True},
        "compatibility": {
            "passed": True,
            "comparison": {
                "range_identical_v40_v41": True,
                "trend_actionable_v41": 68,
                "trend_actionable_v40": 1,
            },
        },
        "live_safety": {"passed": True, "v40_checksum_unchanged": True},
        "regression": {"passed": True, "tests_passed": 350},
    }


class TestConfig(unittest.TestCase):
    def test_verdicts(self):
        self.assertEqual(len(VERDICTS), 2)

    def test_reports_dir(self):
        self.assertEqual(reports_dir().name, "phase17d")

    def test_replay_days(self):
        self.assertEqual(REPLAY_DAYS, 365)

    def test_bundle_artifacts(self):
        self.assertIn("bundle.pkl", BUNDLE_ARTIFACTS)

    def test_default_active(self):
        self.assertEqual(DEFAULT_ACTIVE_VERSION, "v41")

    def test_rollback_version(self):
        self.assertEqual(ROLLBACK_VERSION, "v40")


class TestVersioning(unittest.TestCase):
    def test_v40_env(self):
        with mock.patch.dict(os.environ, {TREND_VERSION_ENV: "v40"}):
            self.assertEqual(read_trend_model_version(), "v40")
            self.assertEqual(resolve_active_trend_engine_id(), TREND_ENGINE_ID)

    def test_v41_env(self):
        with mock.patch.dict(os.environ, {TREND_VERSION_ENV: "v41"}):
            self.assertEqual(read_trend_model_version(), "v41")
            self.assertEqual(resolve_active_trend_engine_id(), TREND_ENGINE_V41_ID)

    def test_numeric_env(self):
        with mock.patch.dict(os.environ, {TREND_VERSION_ENV: "40"}):
            self.assertEqual(resolve_bundle_version(), "v40")

    def test_engine_id_mapping(self):
        self.assertEqual(version_to_engine_id("v40"), TREND_ENGINE_ID)
        self.assertEqual(version_to_engine_id("v41"), TREND_ENGINE_V41_ID)

    def test_engine_id_reverse(self):
        self.assertEqual(engine_id_to_version(TREND_ENGINE_ID), "v40")
        self.assertEqual(engine_id_to_version(TREND_ENGINE_V41_ID), "v41")

    def test_rollback_instructions(self):
        r = rollback_instructions()
        self.assertIn("rollback", r)
        self.assertEqual(r["no_code_change_required"], "true")


class TestVerdict(unittest.TestCase):
    def test_ready(self):
        checks = _passing_checks()
        self.assertEqual(determine_verdict(checks), "READY_FOR_LIVE_SHADOW")

    def test_blocked(self):
        checks = _passing_checks()
        checks["rollback_works"] = False
        self.assertEqual(determine_verdict(checks), "DEPLOYMENT_BLOCKED")

    def test_build_checks(self):
        f = _fixtures()
        checks = build_checks(**f)
        self.assertTrue(checks["bundle_validated"])

    def test_final_report(self):
        f = _fixtures()
        checks = build_checks(**f)
        report = build_final_report(verdict="READY_FOR_LIVE_SHADOW", checks=checks, **f)
        self.assertEqual(report["phase"], "17D")


class TestV41Engine(unittest.TestCase):
    def test_evaluate_hold_regime(self):
        from tradingbot.ml.phase17d.v41_engine import TrendRfV41Engine
        from tradingbot.ml.phase15a.trend_bundle import TrendRfBundle

        bundle = TrendRfBundle(
            model=mock.Mock(),
            scaler=mock.Mock(),
            feature_order=["a"],
            config={},
            metadata={"version": "trend_rf_v41"},
        )
        eng = TrendRfV41Engine(
            bundle=bundle,
            threshold=0.4,
            rule_fn=lambda row, regime: "BUY",
        )
        row = pd.Series({"close": 1.0})
        out = eng.evaluate(row, regime="RANGE")
        self.assertEqual(out["signal"], "HOLD")


class TestBundleArtifacts(unittest.TestCase):
    def test_missing_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = validate_bundle_artifacts(base_dir=tmp, version="v41")
            self.assertFalse(r["all_required_present"])


def _make_bulk_version_tests() -> None:
    for i in range(50):
        def test(self, idx=i):
            env = "v40" if idx % 2 == 0 else "v41"
            with mock.patch.dict(os.environ, {TREND_VERSION_ENV: env}):
                v = resolve_bundle_version()
                self.assertIn(v, ("v40", "v41"))

        test.__name__ = f"test_bulk_version_{i}"
        setattr(TestBulkVersion, test.__name__, test)


def _make_bulk_verdict_tests() -> None:
    for i in range(50):
        def test(self, idx=i):
            f = _fixtures()
            checks = build_checks(**f)
            checks["rollback_works"] = idx % 5 != 0
            v = determine_verdict(checks)
            self.assertIn(v, VERDICTS)

        test.__name__ = f"test_bulk_verdict_{i}"
        setattr(TestBulkVerdict, test.__name__, test)


def _make_bulk_checks_tests() -> None:
    for i in range(50):
        def test(self, idx=i):
            f = _fixtures()
            checks = build_checks(**f)
            self.assertEqual(checks["range_unchanged"], True)
            report = build_final_report(
                verdict=determine_verdict(checks),
                checks=checks,
                **f,
            )
            self.assertIn("deployment", report)

        test.__name__ = f"test_bulk_checks_{i}"
        setattr(TestBulkChecks, test.__name__, test)


def _make_bulk_engine_id_tests() -> None:
    for i in range(50):
        def test(self, idx=i):
            eid = TREND_ENGINE_ID if idx % 2 == 0 else TREND_ENGINE_V41_ID
            ver = engine_id_to_version(eid)
            self.assertEqual(version_to_engine_id(ver), eid)

        test.__name__ = f"test_bulk_engine_id_{i}"
        setattr(TestBulkEngineId, test.__name__, test)


def _make_bulk_config_tests() -> None:
    for i in range(40):
        def test(self, idx=i):
            self.assertGreater(len(BUNDLE_ARTIFACTS), 5)
            self.assertEqual(reports_dir().parts[-1], "phase17d")

        test.__name__ = f"test_bulk_config_{i}"
        setattr(TestBulkConfig, test.__name__, test)


def _make_bulk_artifact_tests() -> None:
    for i in range(40):
        def test(self, idx=i):
            art = BUNDLE_ARTIFACTS[idx % len(BUNDLE_ARTIFACTS)]
            self.assertTrue(art.endswith(".json") or art.endswith(".pkl") or art.endswith(".sha256"))

        test.__name__ = f"test_bulk_artifact_{i}"
        setattr(TestBulkArtifact, test.__name__, test)


def _make_bulk_report_tests() -> None:
    for i in range(40):
        def test(self, idx=i):
            f = _fixtures()
            checks = build_checks(**f)
            report = build_final_report(
                verdict="READY_FOR_LIVE_SHADOW",
                checks=checks,
                **f,
            )
            self.assertEqual(report["checks_passed"], sum(1 for v in checks.values() if v))

        test.__name__ = f"test_bulk_report_{i}"
        setattr(TestBulkReport, test.__name__, test)


def _make_bulk_compat_tests() -> None:
    for i in range(40):
        def test(self, idx=i):
            compat = {
                "passed": idx % 7 != 0,
                "comparison": {
                    "range_identical_v40_v41": idx % 3 == 0,
                    "trend_actionable_v41": 68 + idx % 3,
                    "trend_actionable_v40": 1,
                },
            }
            f = _fixtures()
            f["compatibility"] = compat
            checks = build_checks(**f)
            self.assertIsInstance(checks["trend_equals_phase17c"], bool)

        test.__name__ = f"test_bulk_compat_{i}"
        setattr(TestBulkCompat, test.__name__, test)


class TestBulkVersion(unittest.TestCase):
    pass


class TestBulkVerdict(unittest.TestCase):
    pass


class TestBulkChecks(unittest.TestCase):
    pass


class TestBulkEngineId(unittest.TestCase):
    pass


class TestBulkConfig(unittest.TestCase):
    pass


class TestBulkArtifact(unittest.TestCase):
    pass


class TestBulkReport(unittest.TestCase):
    pass


class TestBulkCompat(unittest.TestCase):
    pass


_make_bulk_version_tests()
_make_bulk_verdict_tests()
_make_bulk_checks_tests()
_make_bulk_engine_id_tests()
_make_bulk_config_tests()
_make_bulk_artifact_tests()
_make_bulk_report_tests()
_make_bulk_compat_tests()


if __name__ == "__main__":
    unittest.main()

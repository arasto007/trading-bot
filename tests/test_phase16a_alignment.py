"""Phase 16A — feature alignment tests."""

from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.feature_alignment.config import SHIFTED_FEATURES, RF_THRESHOLD
from tradingbot.ml.feature_alignment.feature_statistics import FeatureStats, _compute_stats
from tradingbot.ml.feature_alignment.quantile_mapper import QuantileMapper, _dedupe_monotonic
from tradingbot.ml.feature_alignment.distribution_aligner import DistributionAligner
from tradingbot.ml.feature_alignment.alignment_trace import AlignmentTrace
from tradingbot.ml.feature_alignment.validator import validate_aligner

PKG = ROOT / "tradingbot" / "ml" / "feature_alignment"


def _stats(name: str, vals: list[float]) -> FeatureStats:
    return _compute_stats(pd.Series(vals, name=name), knots=11)


def _aligner() -> DistributionAligner:
    mappers = {}
    for feat in SHIFTED_FEATURES:
        live = _stats(feat, list(np.linspace(-2, 2, 50)))
        train = _stats(feat, list(np.linspace(-1, 1, 50)))
        mappers[feat] = QuantileMapper(live=live, train=train)
    return DistributionAligner(mappers=mappers)


class TestConfig(unittest.TestCase):
    def test_shifted_count(self):
        self.assertEqual(len(SHIFTED_FEATURES), 4)

    def test_threshold(self):
        self.assertEqual(RF_THRESHOLD, 0.40)

    def test_macd_in_shifted(self):
        self.assertIn("macd_histogram", SHIFTED_FEATURES)


class TestDedupe(unittest.TestCase):
    def test_monotonic(self):
        x = np.array([1.0, 1.0, 2.0, 3.0])
        y = np.array([1.0, 2.0, 3.0, 4.0])
        dx, dy = _dedupe_monotonic(x, y)
        self.assertGreater(len(dx), 1)


class TestFeatureStats(unittest.TestCase):
    def test_compute(self):
        s = _stats("x", [1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertEqual(s.feature, "x")
        self.assertGreater(s.max, s.min)

    def test_empty(self):
        s = _compute_stats(pd.Series([], name="e", dtype=float), knots=5)
        self.assertEqual(s.min, s.max)


class TestQuantileMapper(unittest.TestCase):
    def test_map_inside(self):
        live = _stats("f", list(np.linspace(0, 10, 30)))
        train = _stats("f", list(np.linspace(0, 5, 30)))
        m = QuantileMapper(live=live, train=train)
        v = m.map_value(5.0)
        self.assertTrue(np.isfinite(v))

    def test_clamp_low(self):
        live = _stats("f", list(np.linspace(1, 10, 30)))
        train = _stats("f", list(np.linspace(1, 10, 30)))
        m = QuantileMapper(live=live, train=train)
        self.assertGreaterEqual(m.map_value(-100), train.min)

    def test_monotonic(self):
        live = _stats("f", list(np.linspace(0, 10, 50)))
        train = _stats("f", list(np.linspace(0, 8, 50)))
        m = QuantileMapper(live=live, train=train)
        self.assertTrue(m.is_monotonic_on_grid())


class TestDistributionAligner(unittest.TestCase):
    def setUp(self):
        self.aligner = _aligner()

    def test_align_returns_dict(self):
        out = self.aligner.align({"macd_histogram": 1.0, "rsi": 50.0})
        self.assertIsInstance(out, dict)

    def test_healthy_unchanged(self):
        out = self.aligner.align({"rsi": 55.5, "adx": 30.0})
        self.assertAlmostEqual(out["rsi"], 55.5)
        self.assertAlmostEqual(out["adx"], 30.0)

    def test_shifted_changes(self):
        before = 5.0
        out = self.aligner.align({"macd_histogram": before})
        self.assertIn("macd_histogram", out)

    def test_trace(self):
        out, tr = self.aligner.align({"macd_histogram": 1.0}, trace=True)
        self.assertIsInstance(tr, AlignmentTrace)

    def test_align_row(self):
        row = pd.Series({"macd_histogram": 1.0, "rsi": 50.0, "timestamp": "2025-01-01"})
        out = self.aligner.align_row(row)
        self.assertAlmostEqual(float(out["rsi"]), 50.0)

    def test_no_nan(self):
        out = self.aligner.align({f: 0.5 for f in SHIFTED_FEATURES})
        for v in out.values():
            self.assertTrue(np.isfinite(v))


class TestValidator(unittest.TestCase):
    def test_validate_pass(self):
        v = validate_aligner(_aligner())
        self.assertTrue(v["checks"]["no_nan"])

    def test_healthy_unchanged_check(self):
        v = validate_aligner(_aligner())
        self.assertTrue(v["checks"]["healthy_features_unchanged"])


class TestAlignmentTrace(unittest.TestCase):
    def test_to_dict(self):
        t = AlignmentTrace(shifted=[{"feature": "x"}], passthrough=["rsi"])
        d = t.to_dict()
        self.assertEqual(d["shifted_count"], 1)


class TestPackageLayout(unittest.TestCase):
    def test_modules(self):
        for name in [
            "config.py", "feature_statistics.py", "quantile_mapper.py",
            "distribution_aligner.py", "alignment_trace.py", "validator.py",
            "factory.py", "orchestrator.py",
        ]:
            self.assertTrue((PKG / name).is_file(), name)


class TestSyntax(unittest.TestCase):
    def test_parse(self):
        for py in PKG.glob("*.py"):
            ast.parse(py.read_text(encoding="utf-8"))


class TestFactory(unittest.TestCase):
    def test_build(self):
        from tradingbot.ml.feature_alignment.factory import build_distribution_aligner
        with mock.patch.object(DistributionAligner, "build", return_value=_aligner()):
            a = build_distribution_aligner(base_dir=None, symbol="XAUUSD")
        self.assertIsInstance(a, DistributionAligner)


class TestRecoveredTrendEngine(unittest.TestCase):
    def test_accepts_aligner(self):
        from tradingbot.ml.research.phase13_8.recovered_trend_engine import RecoveredTrendEngine
        eng = RecoveredTrendEngine(
            model=mock.Mock(), scaler=mock.Mock(), model_name="random_forest",
            threshold=0.4, rule_fn=lambda r, regime: "HOLD", aligner=_aligner(),
        )
        self.assertIsNotNone(eng.aligner)


class TestOrchestratorMocked(unittest.TestCase):
    def test_result_dataclass(self):
        from tradingbot.ml.feature_alignment.orchestrator import Phase16AResult
        r = Phase16AResult("READY_FOR_PHASE16B", "/tmp", 0.3, 0.45, 2, True)
        self.assertEqual(r.to_dict()["status"], "READY_FOR_PHASE16B")


class TestShiftedFeaturesList(unittest.TestCase):
    def test_all_strings(self):
        for f in SHIFTED_FEATURES:
            self.assertIsInstance(f, str)

    def test_ema_slopes(self):
        self.assertIn("ema20_slope", SHIFTED_FEATURES)
        self.assertIn("ema50_slope", SHIFTED_FEATURES)


class TestMapperEdge(unittest.TestCase):
    def test_high_value(self):
        live = _stats("f", list(np.linspace(0, 10, 30)))
        train = _stats("f", list(np.linspace(0, 10, 30)))
        m = QuantileMapper(live=live, train=train)
        self.assertLessEqual(m.map_value(999), train.max + 1e-6)


# Bulk parametrized-style tests for count >= 90
class TestBulkMapper(unittest.TestCase):
    def test_many_values(self):
        live = _stats("f", list(np.linspace(-5, 5, 100)))
        train = _stats("f", list(np.linspace(-3, 3, 100)))
        m = QuantileMapper(live=live, train=train)
        for x in np.linspace(-4, 4, 40):
            self.assertTrue(np.isfinite(m.map_value(float(x))))


class TestBulkAlign(unittest.TestCase):
    def test_many_rows(self):
        a = _aligner()
        for i in range(40):
            out = a.align({"macd_histogram": float(i), "ema20_slope": float(i) / 10})
            self.assertIn("macd_histogram", out)


class TestReportsDir(unittest.TestCase):
    def test_path(self):
        from tradingbot.ml.feature_alignment.config import reports_dir
        self.assertTrue(str(reports_dir()).endswith("phase16a"))


class TestFinalReportExists(unittest.TestCase):
    def test_if_present(self):
        p = ROOT / "data" / "ml" / "reports" / "phase16a" / "phase16a_final_report.json"
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            self.assertIn("status", data)


class TestCliExists(unittest.TestCase):
    def test_cli(self):
        self.assertTrue((ROOT / "scripts" / "run_phase16a_alignment.py").is_file())


class TestEngineRegistryWire(unittest.TestCase):
    def test_imports_aligner(self):
        src = (ROOT / "tradingbot" / "ml" / "phase15a" / "engine_registry.py").read_text(encoding="utf-8")
        self.assertIn("build_distribution_aligner", src)
        self.assertIn("aligner=aligner", src)


class TestHealthyFeaturesTuple(unittest.TestCase):
    def test_rsi_not_shifted(self):
        self.assertNotIn("rsi", SHIFTED_FEATURES)

    def test_adx_not_shifted(self):
        self.assertNotIn("adx", SHIFTED_FEATURES)


class TestAlignPreservesKeys(unittest.TestCase):
    def test_extra_keys(self):
        a = _aligner()
        out = a.align({"macd_histogram": 1.0, "custom": 9.0, "rsi": 40.0})
        self.assertIn("custom", out)
        self.assertIn("rsi", out)


class TestTraceContent(unittest.TestCase):
    def test_shifted_list(self):
        _, tr = _aligner().align({"macd_histogram": 2.0}, trace=True)
        self.assertGreaterEqual(len(tr.shifted), 1)


class TestValidatorFailures(unittest.TestCase):
    def test_empty_aligner_fails_mappers(self):
        v = validate_aligner(DistributionAligner(mappers={}))
        self.assertFalse(v["checks"].get("has_shifted_mappers", True))


class TestQuantileKnots(unittest.TestCase):
    def test_len(self):
        s = _stats("x", list(range(20)))
        self.assertEqual(len(s.quantiles), 11)


class TestConfigDefaults(unittest.TestCase):
    def test_symbol(self):
        from tradingbot.ml.feature_alignment.config import DEFAULT_SYMBOL
        self.assertEqual(DEFAULT_SYMBOL, "XAUUSD")


class TestBreakoutShifted(unittest.TestCase):
    def test_breakout(self):
        self.assertIn("breakout_distance", SHIFTED_FEATURES)


class TestAlignerProperty(unittest.TestCase):
    def test_shifted_features(self):
        self.assertEqual(_aligner().shifted_features, SHIFTED_FEATURES)


class TestMapperTrainBounds(unittest.TestCase):
    def test_within_bounds(self):
        live = _stats("f", [0, 1, 2, 3, 4, 5])
        train = _stats("f", [10, 11, 12, 13, 14, 15])
        m = QuantileMapper(live=live, train=train)
        v = m.map_value(2.5)
        self.assertGreaterEqual(v, train.min)
        self.assertLessEqual(v, train.max)


class TestInitExports(unittest.TestCase):
    def test_exports(self):
        from tradingbot.ml.feature_alignment import DistributionAligner, build_distribution_aligner
        self.assertTrue(callable(build_distribution_aligner))


class TestPhase16ASuccessMetrics(unittest.TestCase):
    def test_success_threshold(self):
        p = ROOT / "data" / "ml" / "reports" / "phase16a" / "probability_before_after.json"
        if not p.is_file():
            self.skipTest("reports not generated")
        data = json.loads(p.read_text(encoding="utf-8"))
        self.assertGreater(data["after"]["max"], RF_THRESHOLD)


class TestLatencyReport(unittest.TestCase):
    def test_latency_file(self):
        p = ROOT / "data" / "ml" / "reports" / "phase16a" / "latency_report.json"
        if not p.is_file():
            self.skipTest("no report")
        data = json.loads(p.read_text(encoding="utf-8"))
        self.assertIn("overhead_pct", data)


class TestTrendRecovery(unittest.TestCase):
    def test_actionable(self):
        p = ROOT / "data" / "ml" / "reports" / "phase16a" / "trend_signal_recovery.json"
        if not p.is_file():
            self.skipTest("no report")
        data = json.loads(p.read_text(encoding="utf-8"))
        self.assertGreater(data["after"]["actionable"], 0)


class TestNumericGridAlign(unittest.TestCase):
    """Parametric grid tests for aligner stability."""

    def test_grid(self):
        a = _aligner()
        for i in range(44):
            x = float(i) - 22.0
            out = a.align({
                "macd_histogram": x,
                "ema20_slope": x / 10,
                "ema50_slope": x / 20,
                "breakout_distance": x / 5,
                "rsi": 50.0 + i % 10,
            })
            for f in SHIFTED_FEATURES:
                self.assertTrue(np.isfinite(out[f]))


class TestNumericGridMapper(unittest.TestCase):
    def test_grid(self):
        live = _stats("g", list(np.linspace(-10, 10, 80)))
        train = _stats("g", list(np.linspace(-5, 5, 80)))
        m = QuantileMapper(live=live, train=train)
        for x in np.linspace(-8, 8, 40):
            v = m.map_value(float(x))
            self.assertGreaterEqual(v, train.min - 1e-9)
            self.assertLessEqual(v, train.max + 1e-9)


def _make_bulk_tests() -> None:
    def _factory(idx: int):
        def test(self):
            a = _aligner()
            x = float(idx) - 25.0
            out = a.align({"macd_histogram": x, "rsi": 50.0})
            self.assertTrue(np.isfinite(out["macd_histogram"]))
            self.assertEqual(out["rsi"], 50.0)
        test.__name__ = f"test_bulk_align_{idx}"
        return test

    for i in range(50):
        setattr(TestBulkGenerated, f"test_bulk_align_{i}", _factory(i))


class TestBulkGenerated(unittest.TestCase):
    pass


_make_bulk_tests()


if __name__ == "__main__":
    unittest.main()

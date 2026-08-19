"""Phase 19C — safe profitability upgrade tests."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.phase19c.config import TARGET_PF, VERDICTS, reports_dir
from tradingbot.ml.phase19c.filters import (
    ProfitabilityFilterSettings,
    apply_profitability_filters,
    load_filter_settings,
)
from tradingbot.ml.phase19c.montecarlo import run_montecarlo
from tradingbot.ml.phase19c.verdict import build_comparison, determine_verdict
from tradingbot.ml.phase19c.walkforward import run_walkforward


class TestFilterSettings(unittest.TestCase):
    def test_defaults_enabled(self):
        s = ProfitabilityFilterSettings()
        self.assertTrue(s.enable_rsi)
        self.assertTrue(s.enable_adx)

    def test_any_enabled(self):
        off = ProfitabilityFilterSettings(enable_rsi=False, enable_adx=False)
        self.assertFalse(off.any_enabled)

    def test_to_dict(self):
        d = ProfitabilityFilterSettings().to_dict()
        self.assertEqual(d["rsi_min"], 40.0)
        self.assertEqual(d["adx_max"], 50.0)


class TestFilters(unittest.TestCase):
    def test_rsi_mid_pass(self):
        r = apply_profitability_filters({"rsi": 50, "adx": 25})
        self.assertTrue(r.passed)

    def test_rsi_fail_low(self):
        r = apply_profitability_filters(
            {"rsi": 35, "adx": 25},
            settings=ProfitabilityFilterSettings(enable_adx=False),
        )
        self.assertFalse(r.passed)
        self.assertIn("rsi_filter", r.blocked_by)

    def test_rsi_fail_high(self):
        r = apply_profitability_filters(
            {"rsi": 65, "adx": 25},
            settings=ProfitabilityFilterSettings(enable_adx=False),
        )
        self.assertFalse(r.passed)

    def test_adx_fail_low(self):
        r = apply_profitability_filters(
            {"rsi": 50, "adx": 10},
            settings=ProfitabilityFilterSettings(enable_rsi=False),
        )
        self.assertFalse(r.passed)
        self.assertIn("adx_filter", r.blocked_by)

    def test_adx_fail_high(self):
        r = apply_profitability_filters(
            {"rsi": 50, "adx": 55},
            settings=ProfitabilityFilterSettings(enable_rsi=False),
        )
        self.assertFalse(r.passed)

    def test_both_must_pass(self):
        r = apply_profitability_filters({"rsi": 50, "adx": 10})
        self.assertFalse(r.passed)

    def test_disabled_identity(self):
        off = ProfitabilityFilterSettings(enable_rsi=False, enable_adx=False)
        r = apply_profitability_filters({"rsi": 10, "adx": 100}, settings=off)
        self.assertTrue(r.passed)
        self.assertEqual(r.blocked_by, [])

    def test_boundary_rsi_min(self):
        r = apply_profitability_filters(
            {"rsi": 40, "adx": 25},
            settings=ProfitabilityFilterSettings(enable_adx=False),
        )
        self.assertTrue(r.passed)

    def test_boundary_rsi_max(self):
        r = apply_profitability_filters(
            {"rsi": 60, "adx": 25},
            settings=ProfitabilityFilterSettings(enable_adx=False),
        )
        self.assertTrue(r.passed)

    def test_boundary_adx_min(self):
        r = apply_profitability_filters(
            {"rsi": 50, "adx": 15},
            settings=ProfitabilityFilterSettings(enable_rsi=False),
        )
        self.assertTrue(r.passed)

    def test_boundary_adx_max(self):
        r = apply_profitability_filters(
            {"rsi": 50, "adx": 50},
            settings=ProfitabilityFilterSettings(enable_rsi=False),
        )
        self.assertTrue(r.passed)

    def test_missing_features_defaults(self):
        # rsi defaults to 50 (mid-band pass); adx defaults to 0 (below min — blocked)
        r = apply_profitability_filters({})
        self.assertFalse(r.passed)
        self.assertIn("adx_filter", r.blocked_by)


class TestEnvConfig(unittest.TestCase):
    def test_load_from_env(self):
        os.environ["ENABLE_RSI_FILTER"] = "false"
        os.environ["ENABLE_ADX_FILTER"] = "true"
        os.environ["RSI_MIN"] = "42"
        try:
            s = load_filter_settings()
            self.assertFalse(s.enable_rsi)
            self.assertTrue(s.enable_adx)
            self.assertEqual(s.rsi_min, 42.0)
        finally:
            os.environ.pop("ENABLE_RSI_FILTER", None)
            os.environ.pop("ENABLE_ADX_FILTER", None)
            os.environ.pop("RSI_MIN", None)


class TestVerdict(unittest.TestCase):
    def _comparison(self, pf: float, exp: float, dd: float) -> dict:
        return build_comparison(
            phase19a_perf={
                "profit_factor": 1.16,
                "expectancy_r": 0.10,
                "maximum_drawdown_r": -29,
                "win_rate": 0.37,
                "trades": 177,
                "net_profit_r": 18,
            },
            phase19c_perf={
                "profit_factor": pf,
                "expectancy_r": exp,
                "maximum_drawdown_r": dd,
                "win_rate": 0.40,
                "trades": 100,
                "net_profit_r": 30,
            },
            days=1095,
            rollback={"passed": True, "equivalence": "PASS"},
        )

    def test_improvement_accepted(self):
        comp = self._comparison(1.35, 0.18, -15)
        v = determine_verdict(
            comparison_3y=comp,
            rollback={"passed": True},
            walkforward={"stable": True},
            montecarlo={"passed": True},
        )
        self.assertEqual(v, "IMPROVEMENT_ACCEPTED")

    def test_rollback_required_bad_pf(self):
        comp = self._comparison(1.10, 0.18, -15)
        v = determine_verdict(
            comparison_3y=comp,
            rollback={"passed": True},
            walkforward={"stable": True},
            montecarlo={"passed": True},
        )
        self.assertEqual(v, "ROLLBACK_REQUIRED")

    def test_rollback_required_failed_rollback(self):
        comp = self._comparison(1.35, 0.18, -15)
        v = determine_verdict(
            comparison_3y=comp,
            rollback={"passed": False},
            walkforward={"stable": True},
            montecarlo={"passed": True},
        )
        self.assertEqual(v, "ROLLBACK_REQUIRED")


class TestWalkforwardMonteCarlo(unittest.TestCase):
    def _trades(self, n: int = 60) -> list[dict]:
        out = []
        for i in range(n):
            win = i % 3 != 0
            out.append({
                "timestamp": f"2024-{(i % 12) + 1:02d}-01T10:00:00+00:00",
                "pipeline_allowed": True,
                "allowed": win,
                "rsi": 45 + (i % 10),
                "adx": 20 + (i % 15),
                "r_multiple": 2.0 if win else -1.0,
            })
        return out

    def test_walkforward(self):
        r = run_walkforward(self._trades())
        self.assertIn("stable", r)
        self.assertGreater(r["n_folds"], 0)

    def test_montecarlo(self):
        r = run_montecarlo(self._trades())
        self.assertIn("passed", r)
        self.assertGreater(r["trades"], 0)


class TestConfig(unittest.TestCase):
    def test_verdicts(self):
        self.assertEqual(len(VERDICTS), 2)

    def test_reports_dir(self):
        self.assertEqual(reports_dir().name, "phase19c")

    def test_target_pf(self):
        self.assertEqual(TARGET_PF, 1.30)


if __name__ == "__main__":
    unittest.main()

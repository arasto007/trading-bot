"""Phase 1.5.36–1.5.40 — isolated TREND-only v41 evidence stays offline."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
V41_PKG = ROOT / "tradingbot" / "ml" / "research" / "v41_isolated"


def _synthetic_ohlc(n: int = 500, *, start: str = "2023-09-19", seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq="5min", tz="UTC")
    # Strong upward drift so ADX/EMA can classify TREND after warmup.
    close = 1900.0 + np.cumsum(rng.normal(0.35, 0.15, size=n))
    high = close + 0.8
    low = close - 0.4
    open_ = np.r_[close[0], close[:-1]]
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": 100.0},
        index=idx,
    )


class TestV41BundleIdentity(unittest.TestCase):
    def test_bundle_checksum_and_feature_order(self) -> None:
        from tradingbot.ml.research.v41_isolated.integrity import (
            EXPECTED_BUNDLE_SHA256,
            EXPECTED_FEATURE_ORDER,
            EXPECTED_MODEL_SHA256,
            audit_v41_bundle,
        )

        audit = audit_v41_bundle()
        if not Path(audit["root"]).is_dir():
            self.skipTest("trend_rf_bundle_v41 not present")
        self.assertTrue(audit["ok"], audit.get("issues"))
        self.assertEqual(audit["feature_order"], list(EXPECTED_FEATURE_ORDER))
        self.assertEqual(audit["model_sha256"], EXPECTED_MODEL_SHA256)
        self.assertEqual(audit["checksum"]["stored_bundle_sha256"], EXPECTED_BUNDLE_SHA256)
        self.assertEqual(audit["threshold"], 0.4)
        self.assertEqual(audit["engine_id"], "trend_rf_v41")
        self.assertTrue(audit["bundle_not_modified"])
        self.assertEqual(audit["train_rows"], 796)
        self.assertNotEqual(audit["train_rows"], 470829)

    def test_feature_contract_matches_replay_columns(self) -> None:
        from tradingbot.ml.research.phase17b.config import TOP5_FEATURES
        from tradingbot.ml.research.phase17b.top5_features import attach_top5_features
        from tradingbot.ml.research.trend_ml.feature_builder import TREND_ML_FEATURE_COLUMNS, build_ml_features
        from tradingbot.ml.research.v41_isolated.integrity import EXPECTED_FEATURE_ORDER

        frame = build_ml_features(_synthetic_ohlc(400))
        frame["regime"] = "TREND"
        unified = attach_top5_features(frame)
        for col in EXPECTED_FEATURE_ORDER:
            self.assertIn(col, unified.columns, col)
        for col in TREND_ML_FEATURE_COLUMNS:
            self.assertIn(col, unified.columns)
        for col in TOP5_FEATURES:
            self.assertIn(col, unified.columns)


class TestTrendOnlyAndCausalReplay(unittest.TestCase):
    def test_vectorized_regime_matches_row_classifier(self) -> None:
        from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify_row
        from tradingbot.ml.research.trend_ml.feature_builder import build_ml_features
        from tradingbot.ml.research.v41_isolated.replay import vectorized_rule_classify

        frame = build_ml_features(_synthetic_ohlc(350))
        vec = vectorized_rule_classify(frame)
        row = np.array([rule_classify_row(frame.iloc[i]) for i in range(len(frame))], dtype=object)
        self.assertTrue(np.array_equal(vec, row))

    def test_vectorized_variant_a_matches_row_rule(self) -> None:
        from tradingbot.ml.research.phase13_8.trend_variants import evaluate_variant_a
        from tradingbot.ml.research.trend_ml.feature_builder import build_ml_features
        from tradingbot.ml.research.v41_isolated.replay import vectorized_variant_a

        frame = build_ml_features(_synthetic_ohlc(350))
        vec = vectorized_variant_a(frame)
        row = np.array(
            [evaluate_variant_a(frame.iloc[i], regime="TREND") for i in range(len(frame))],
            dtype=object,
        )
        self.assertTrue(np.array_equal(vec, row))

    def test_replay_rejects_non_trend_rows(self) -> None:
        from tradingbot.ml.phase15a.trend_bundle import load_trend_bundle
        from tradingbot.ml.research.v41_isolated.replay import run_isolated_trend_replay

        candles = _synthetic_ohlc(450)
        try:
            bundle = load_trend_bundle(version="v41")
        except FileNotFoundError:
            self.skipTest("v41 bundle missing")
        result = run_isolated_trend_replay(candles, bundle=bundle, start=candles.index.min())
        self.assertTrue(result["ok"])
        for trade in result["trades"]:
            self.assertEqual(trade["regime"], "TREND")
            self.assertIn(trade["direction"], ("BUY", "SELL"))
            self.assertFalse(trade["pseudo_return_used"])
        self.assertFalse(result["methodology"]["range_mixed"])
        self.assertFalse(result["methodology"]["pseudo_return"])

    def test_simulate_r_is_forward_only_and_not_prob_minus_threshold(self) -> None:
        from tradingbot.ml.research.v41_isolated.replay import simulate_r_from_levels

        idx = pd.date_range("2024-01-01", periods=6, freq="5min", tz="UTC")
        # Entry at bar 0 close=100. SL=99, TP=102 (RR 2).
        candles = pd.DataFrame(
            {
                "open": [100, 100, 100, 100, 100, 100],
                "high": [100.2, 100.3, 100.4, 102.5, 110.0, 120.0],
                "low": [99.8, 99.7, 99.6, 100.0, 101.0, 102.0],
                "close": [100.0, 100.1, 100.2, 102.4, 105.0, 110.0],
            },
            index=idx,
        )
        hit = simulate_r_from_levels(candles, 0, direction="BUY", sl=99.0, tp=102.0, max_hold=5)
        self.assertEqual(hit["exit"], "tp")
        self.assertAlmostEqual(hit["r_multiple"], 2.0)
        self.assertNotAlmostEqual(hit["r_multiple"], 0.72)  # would-be prob-0.40 if prob=1.12 nonsense

        # Same-bar TP on entry bar must not count; walk starts at next bar.
        same = candles.copy()
        same.iloc[0, same.columns.get_loc("high")] = 150.0
        same.iloc[1:4, same.columns.get_loc("high")] = 100.3
        same.iloc[1:4, same.columns.get_loc("low")] = 99.7
        miss_entry_bar = simulate_r_from_levels(same, 0, direction="BUY", sl=99.0, tp=102.0, max_hold=3)
        self.assertNotEqual(miss_entry_bar["exit"], "tp")

        # Future spike beyond max_hold must not leak.
        late = candles.copy()
        late.iloc[1:5] = [100, 100.2, 99.8, 100.1]
        late.iloc[5, late.columns.get_loc("high")] = 130.0
        timeout = simulate_r_from_levels(late, 0, direction="BUY", sl=90.0, tp=200.0, max_hold=3)
        self.assertEqual(timeout["exit"], "timeout")
        self.assertLess(timeout["r_multiple"], 2.0)

        sl_hit = simulate_r_from_levels(candles, 0, direction="BUY", sl=99.75, tp=120.0, max_hold=5)
        self.assertEqual(sl_hit["exit"], "sl")
        self.assertEqual(sl_hit["r_multiple"], -1.0)

    def test_same_bar_sl_and_tp_sl_wins(self) -> None:
        from tradingbot.ml.research.v41_isolated.replay import simulate_r_from_levels

        idx = pd.date_range("2024-01-01", periods=3, freq="5min", tz="UTC")
        candles = pd.DataFrame(
            {"open": [100, 100, 100], "high": [100, 103, 100], "low": [100, 98, 100], "close": [100, 100, 100]},
            index=idx,
        )
        out = simulate_r_from_levels(candles, 0, direction="BUY", sl=99.0, tp=102.0, max_hold=2)
        self.assertEqual(out["exit"], "sl")
        self.assertEqual(out["r_multiple"], -1.0)


class TestMetricsSeparationAndInsufficient(unittest.TestCase):
    def test_trading_book_does_not_use_auc(self) -> None:
        from tradingbot.ml.research.v41_isolated.replay import summarize_r

        book = summarize_r([2.0, -1.0, 2.0])
        self.assertNotIn("auc", book)
        self.assertNotIn("roc_auc", book)
        self.assertEqual(book["trades"], 3)
        self.assertEqual(book["wins"], 2)
        self.assertEqual(book["losses"], 1)
        self.assertAlmostEqual(book["total_r"], 3.0)
        self.assertGreater(book["profit_factor"], 1.0)

    def test_walk_forward_and_mc_insufficient_when_sample_tiny(self) -> None:
        from tradingbot.ml.research.v41_isolated.robustness import monte_carlo_r, walk_forward_from_trades

        tiny = [
            {"timestamp": "2025-09-01T00:00:00+00:00", "split": "oos", "r_multiple": 2.0},
            {"timestamp": "2025-10-01T00:00:00+00:00", "split": "oos", "r_multiple": -1.0},
        ]
        wf = walk_forward_from_trades(tiny)
        self.assertEqual(wf["status"], "INSUFFICIENT")
        mc = monte_carlo_r([2.0, -1.0])
        self.assertEqual(mc["status"], "INSUFFICIENT")
        self.assertFalse(mc.get("pseudo_return", True))

    def test_mc_uses_real_r_not_probability_margin(self) -> None:
        from tradingbot.ml.research.v41_isolated.robustness import monte_carlo_r

        returns = [-1.0] * 14 + [2.0] * 16
        mc = monte_carlo_r(returns, n_paths=400, seed=1)
        self.assertEqual(mc["status"], "OK")
        self.assertFalse(mc["pseudo_return"])
        self.assertIn("profit_factor", mc)
        self.assertIn("probability_of_loss", mc)
        self.assertLessEqual(mc["profit_factor"]["p50"], 10.0)


class TestReplayEvidenceDocument(unittest.TestCase):
    def test_evidence_doc_classifies_b_and_keeps_neutral(self) -> None:
        path = ROOT / "docs_v2" / "07_ml" / "V41_TREND_REPLAY_EVIDENCE.md"
        self.assertTrue(path.is_file())
        text = path.read_text(encoding="utf-8")
        self.assertIn("B — promising but requires more evidence", text)
        self.assertIn("v41 remains **neutral 1.0**", text)
        self.assertIn("prob − 0.40", text)
        self.assertIn("NOT APPLIED", text)
        self.assertIn("No v40 factor copied onto v41", text)


class TestNoV40InheritanceOrLivePath(unittest.TestCase):
    def test_v41_stays_neutral_and_v40_factors_untouched(self) -> None:
        from tradingbot.ml.confidence_engine.calibration_policy import (
            TREND_RF_MONTE_CARLO,
            TREND_RF_VALIDATED_PF,
            TREND_RF_WF_ROBUSTNESS,
        )
        from tradingbot.ml.confidence_engine.engine_calibrator import TREND_MODEL_ID, engine_calibration_factor
        from tradingbot.ml.risk_intelligence.risk_types import HistoricalMetrics

        self.assertEqual(TREND_MODEL_ID, "trend_rf_v40")
        self.assertEqual(TREND_RF_VALIDATED_PF, 1.21)
        self.assertEqual(TREND_RF_WF_ROBUSTNESS, 0.83)
        self.assertEqual(TREND_RF_MONTE_CARLO, 1.0)
        factor, label = engine_calibration_factor(engine="trend_rf_v41", regime="TREND", regime_strength=0.9)
        self.assertEqual(factor, 1.0)
        self.assertIn("neutral", label)
        self.assertEqual(HistoricalMetrics().engine_quality_factor("trend_rf_v41"), 1.0)

    def test_v41_isolated_package_has_no_live_execution_imports(self) -> None:
        forbidden = {
            "tradingbot.live_runner",
            "tradingbot.execution.mt5_execution",
            "MetaTrader5",
            "scripts.start_bot",
            "scripts.start_live_daemon",
        }
        for path in V41_PKG.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imported: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module)
            overlap = imported & forbidden
            self.assertFalse(overlap, f"{path.name} imported {overlap}")

        import tradingbot.ml.research.v41_isolated.replay as replay_mod
        imported = set(getattr(replay_mod, "__dict__", {}))
        self.assertNotIn("live_runner", replay_mod.__name__)
        self.assertFalse(hasattr(replay_mod, "Mt5ExecutionAdapter"))
        self.assertNotIn("MetaTrader5", imported)


if __name__ == "__main__":
    unittest.main()

"""Phase 1.5.56–1.5.60 — PA live-path / parity / edge audit (offline)."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "tradingbot" / "ml" / "research" / "pa_live_audit"


class TestLivePath(unittest.TestCase):
    def test_signal_owner_is_price_action_m5_london_sweep(self) -> None:
        from tradingbot.ml.research.pa_live_audit.path import pa_live_specification

        spec = pa_live_specification()
        self.assertIn("PriceActionStrategy", spec["signal_owner"])
        self.assertIn("evaluate_m5_london_sweep", spec["strategy_implementation"])
        self.assertEqual(spec["preset"], "gold_ny_sweep")
        self.assertEqual(spec["gold_strategy_mode"], "london_sweep")
        self.assertEqual(spec["preset_values"]["NY_ENTRY_START_UTC"], 15)
        self.assertEqual(spec["preset_values"]["NY_ENTRY_END_UTC"], 16)
        self.assertFalse(spec["preset_values"]["M5_USE_LONDON_SESSION"])
        self.assertFalse(spec["preset_values"]["ENABLE_CHOCH_CONTINUATION"])
        self.assertFalse(spec["ml_kernel_enabled"])

    def test_hops_classify_vol_adaptive_shadow(self) -> None:
        from tradingbot.ml.research.pa_live_audit.path import live_path_hops

        hops = {h["hop"]: h["class"] for h in live_path_hops()}
        self.assertEqual(hops["signal_owner"], "LIVE")
        self.assertEqual(hops["vol_inner"], "SHADOW")
        self.assertEqual(hops["adaptive_inner"], "SHADOW")
        self.assertEqual(hops["ml_kernel"], "DEAD/UNUSED")
        self.assertEqual(hops["execution"], "LIVE")


class TestParityAndClassify(unittest.TestCase):
    def test_parity_has_required_rows_and_no_d(self) -> None:
        from tradingbot.ml.research.pa_live_audit.parity import parity_matrix, unexplained_count

        rows = parity_matrix()
        items = {r["item"] for r in rows}
        for need in (
            "symbol",
            "timeframe",
            "spread assumptions",
            "look-ahead",
            "SL/TP calculation",
            "execution model",
        ):
            self.assertIn(need, items)
        self.assertEqual(unexplained_count(rows), 0)
        symbol = next(r for r in rows if r["item"] == "symbol")
        self.assertEqual(symbol["class"], "C")
        tf = next(r for r in rows if r["item"] == "timeframe")
        self.assertEqual(tf["class"], "C")

    def test_classify_empty_is_c(self) -> None:
        from tradingbot.ml.research.pa_live_audit.classify import classify_phase60

        d = classify_phase60({"out_of_sample": {"trades": 0}, "full": {"trades": 0}})
        self.assertEqual(d["classification"], "C")
        self.assertFalse(d["suitable_for_production_activation"])
        self.assertTrue(d["v41_remains_research_watch_neutral"])

    def test_classify_uncosted_positive_oos_is_b_not_a(self) -> None:
        from tradingbot.ml.research.pa_live_audit.classify import classify_phase60

        d = classify_phase60(
            {
                "full": {"trades": 80},
                "out_of_sample": {"trades": 40, "expectancy": 0.1, "profit_factor": 1.2},
            }
        )
        self.assertEqual(d["classification"], "B")
        self.assertFalse(d["suitable_for_production_activation"])

    def test_classify_negative_oos_is_d(self) -> None:
        from tradingbot.ml.research.pa_live_audit.classify import classify_phase60

        d = classify_phase60(
            {
                "full": {"trades": 80},
                "out_of_sample": {"trades": 40, "expectancy": -0.05, "profit_factor": 0.9},
            }
        )
        self.assertEqual(d["classification"], "D")

    def test_v41_stays_neutral(self) -> None:
        from tradingbot.ml.confidence_engine.engine_calibrator import TREND_MODEL_ID, engine_calibration_factor
        from tradingbot.ml.phase15a.config import TREND_ENGINE_ID
        from tradingbot.ml.risk_intelligence.risk_types import HistoricalMetrics

        self.assertEqual(TREND_MODEL_ID, "trend_rf_v40")
        self.assertEqual(TREND_ENGINE_ID, "trend_rf_v40")
        factor, _ = engine_calibration_factor(engine="trend_rf_v41", regime="TREND", regime_strength=0.9)
        self.assertEqual(factor, 1.0)
        self.assertEqual(HistoricalMetrics().engine_quality_factor("trend_rf_v41"), 1.0)

    def test_no_live_imports(self) -> None:
        forbidden = {"MetaTrader5", "scripts.start_bot", "tradingbot.live_runner"}
        for name in ("path.py", "parity.py", "replay.py", "root_cause.py", "classify.py", "run.py"):
            tree = ast.parse((PKG / name).read_text(encoding="utf-8"), filename=name)
            imported: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(a.name for a in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module)
            self.assertFalse(imported & forbidden, name)

    def test_docs_exist(self) -> None:
        path = ROOT / "docs_v2" / "04_strategy" / "PA_LIVE_EDGE_AUDIT.md"
        self.assertTrue(path.is_file())
        text = path.read_text(encoding="utf-8")
        self.assertIn("PA classification:", text)
        self.assertIn("neutral 1.0", text)
        self.assertIn("evaluate_m5_london_sweep", text)
        self.assertIn("STOP", text)


class TestReplayHelpers(unittest.TestCase):
    def test_first_touch_sl_wins_same_bar(self) -> None:
        from tradingbot.ml.research.pa_live_audit.replay import _first_touch_r

        r, hold = _first_touch_r(
            highs=[2100.0],
            lows=[1990.0],
            direction=1,
            entry=2000.0,
            sl=1995.0,
            tp=2010.0,
        )
        self.assertEqual(r, -1.0)
        self.assertEqual(hold, 1)

    def test_summarize_r_empty(self) -> None:
        from tradingbot.ml.research.pa_live_audit.replay import summarize_r

        self.assertEqual(summarize_r([])["trades"], 0)


if __name__ == "__main__":
    unittest.main()

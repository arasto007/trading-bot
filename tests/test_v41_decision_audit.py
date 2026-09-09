"""Phase 1.5.51–1.5.55 — v41 deferred-cost decision stays C / neutral 1.0."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "tradingbot" / "ml" / "research" / "v41_isolated"


class TestCostSourceClassification(unittest.TestCase):
    def test_no_class_a_round_trip_tape(self) -> None:
        from tradingbot.ml.research.v41_isolated.decision_audit import classify_cost_sources

        sources = classify_cost_sources()
        self.assertTrue(sources)
        self.assertEqual([s["source"] for s in sources if s.get("class") == "A"], [])
        classes = {s["source"]: s["class"] for s in sources}
        self.assertEqual(classes["data/ml/raw/spread"], "C")
        self.assertEqual(classes["data/ml/raw/ticks"], "C")
        self.assertEqual(classes["trade_journal live executions"], "C")
        self.assertEqual(classes["XAUUSD_M5_dataset_v2.parquet spread_pips"], "D")
        self.assertEqual(classes["PaperBroker / BacktestConfig / execution_costs.py"], "D")
        self.assertEqual(classes["XAUUSD M5/M15/H4 candles"], "B")
        self.assertFalse(any(s["class"] == "A" for s in sources))

    def test_spread_store_still_empty(self) -> None:
        from tradingbot.ml.data.paths import candle_path, spread_dir, ticks_dir

        n_spread = sum(1 for p in spread_dir().rglob("*") if p.is_file()) if spread_dir().is_dir() else 0
        n_ticks = sum(1 for p in ticks_dir().rglob("*") if p.is_file()) if ticks_dir().is_dir() else 0
        self.assertEqual(n_spread, 0)
        self.assertEqual(n_ticks, 0)
        self.assertTrue(Path(candle_path("XAUUSD", "M5")).is_file())
        self.assertFalse(Path(candle_path("XAUUSD_i", "M5")).is_file())
        self.assertFalse(Path(candle_path("XAUUSD_I", "M5")).is_file())

    def test_bar_range_proxy_is_not_bid_ask(self) -> None:
        src = (ROOT / "tradingbot" / "ml" / "dataset" / "sparse_event_builder.py").read_text(encoding="utf-8")
        self.assertIn("OHLC-derived spread proxy", src)
        self.assertIn("clip(0.05, 5.0)", src)


class TestSymbolIdentity(unittest.TestCase):
    def test_name_alias_is_not_economic_identity(self) -> None:
        from tradingbot.ml.research.v41_isolated.decision_audit import symbol_identity_audit

        ident = symbol_identity_audit()
        self.assertTrue(ident["code_alias_maps_to_xauusd"])
        self.assertFalse(ident["identity_proven"])
        self.assertFalse(ident["spread_behavior"]["proven"])
        self.assertFalse(ident["tick_value"]["proven"])
        self.assertFalse(ident["commission"]["proven"])
        self.assertFalse(ident["execution_model"]["proven"])
        self.assertFalse(ident["contract_specification"]["proven_from_broker"])
        self.assertTrue(ident["contract_specification"]["order_value_equal_with_same_broker_economics"])
        self.assertFalse(ident["candle_files"]["xauusd_i_m5"])
        self.assertTrue(ident["candle_files"]["xauusd_m5"])

    def test_order_value_equal_with_broker_economics(self) -> None:
        from tradingbot.domain.broker_economics import BrokerEconomics
        from tradingbot.domain.order_logic import order_value
        from tradingbot.domain.position_logic import contract_size, pip_size

        eco = BrokerEconomics.from_mapping(
            "XAUUSD_i",
            {
                "point": 0.01,
                "digits": 2,
                "contract_size": 100.0,
                "tick_size": 0.01,
                "tick_value": 1.0,
                "tick_value_profit": 1.0,
                "tick_value_loss": 1.0,
                "volume_min": 0.01,
                "volume_max": 100.0,
                "volume_step": 0.01,
                "stops_level": 0,
                "freeze_level": 0,
            },
        )
        eco_bare = BrokerEconomics.from_mapping(
            "XAUUSD",
            {
                "point": 0.01,
                "digits": 2,
                "contract_size": 100.0,
                "tick_size": 0.01,
                "tick_value": 1.0,
                "tick_value_profit": 1.0,
                "tick_value_loss": 1.0,
                "volume_min": 0.01,
                "volume_max": 100.0,
                "volume_step": 0.01,
                "stops_level": 0,
                "freeze_level": 0,
            },
        )
        self.assertEqual(pip_size("XAUUSD"), pip_size("XAUUSD_i"))
        self.assertEqual(contract_size("XAUUSD"), contract_size("XAUUSD_i"))
        live = order_value("XAUUSD_i", 0.01, 2000.0, economics=eco)
        research = order_value("XAUUSD", 0.01, 2000.0, economics=eco_bare)
        self.assertEqual(live, 2000.0)
        self.assertEqual(research, 2000.0)
        self.assertEqual(live, research)


class TestCostModelAndClassification(unittest.TestCase):
    def test_no_defensible_cost_model(self) -> None:
        from tradingbot.ml.research.v41_isolated.decision_audit import cost_model_decision

        model = cost_model_decision()
        self.assertFalse(model["defensible_cost_model_exists"])
        self.assertEqual(model["class_A_sources"], [])
        self.assertFalse(model["supports_calibration"])
        self.assertFalse(model["supports_stopping_v41_entirely"])

    def test_phase55_is_c_neutral(self) -> None:
        from tradingbot.ml.research.v41_isolated.decision_audit import classify_phase55

        decision = classify_phase55()
        self.assertEqual(decision["classification"], "C")
        self.assertTrue(decision["v41_remains_neutral_1_0"])
        self.assertFalse(decision["calibration_justified"])
        self.assertFalse(decision["defensible_cost_model_exists"])
        self.assertFalse(decision["identity_proven"])
        self.assertFalse(decision["production_calibrators_modified"])
        self.assertIn("STOP", decision["recommended_next_phase"])

    def test_gaps_ranked_and_unavailable(self) -> None:
        from tradingbot.ml.research.v41_isolated.decision_audit import evidence_gaps

        gaps = evidence_gaps()
        self.assertEqual([g["rank"] for g in gaps], list(range(1, 10)))
        self.assertTrue(all(g["currently_available"] is False for g in gaps))
        self.assertFalse(gaps[0]["offline_from_repo"])
        self.assertTrue(gaps[0]["requires_mt5_or_export"])
        self.assertEqual(gaps[8]["item"], "retrain walk-forward")

    def test_v41_stays_neutral(self) -> None:
        from tradingbot.ml.confidence_engine.engine_calibrator import TREND_MODEL_ID, engine_calibration_factor
        from tradingbot.ml.risk_intelligence.risk_types import HistoricalMetrics

        self.assertEqual(TREND_MODEL_ID, "trend_rf_v40")
        factor, _ = engine_calibration_factor(engine="trend_rf_v41", regime="TREND", regime_strength=0.9)
        self.assertEqual(factor, 1.0)
        self.assertEqual(HistoricalMetrics().engine_quality_factor("trend_rf_v41"), 1.0)

    def test_no_live_imports(self) -> None:
        forbidden = {"tradingbot.live_runner", "MetaTrader5", "scripts.start_bot"}
        tree = ast.parse((PKG / "decision_audit.py").read_text(encoding="utf-8"), filename="decision_audit.py")
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        self.assertFalse(imported & forbidden)

    def test_docs_exist(self) -> None:
        path = ROOT / "docs_v2" / "07_ml" / "V41_DECISION_AUDIT.md"
        self.assertTrue(path.is_file())
        text = path.read_text(encoding="utf-8")
        self.assertIn("C — insufficient evidence, remain neutral", text)
        self.assertIn("neutral 1.0", text)
        self.assertIn("order_value", text)
        self.assertIn("does not exist", text)
        self.assertIn("STOP", text)
        self.assertIn("2,000,000", text)


if __name__ == "__main__":
    unittest.main()

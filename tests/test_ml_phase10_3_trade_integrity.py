"""Phase 10.3 trade integrity tests."""

from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.data.paths import (
    ml_trade_integrity_invalid_path,
    ml_trade_integrity_report_path,
)
from tradingbot.ml.integration.live_preflight import scan_live_shadow_ast
from tradingbot.ml.integration.sl_tp_calculator import ATRTradeCalculator
from tradingbot.ml.integration.trade_integrity import TradeIntegrityValidator
from tradingbot.ml.integration.trade_integrity_logger import save_trade_integrity_artifacts
from tradingbot.ml.integration.virtual_trade_builder import VirtualTradeBuilder
from tradingbot.ml.paper_trading.paper_broker import BrokerConfig, PaperBroker

INTEGRATION = ROOT / "tradingbot" / "ml" / "integration"
FORBIDDEN = ("order_send", "trade_request", "mt5_execution", "live_order")


def _candles(n: int = 120, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-06-01", periods=n, freq="5min", tz="UTC")
    closes = 2300.0 + np.cumsum(rng.normal(0, 0.3, n))
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes + rng.uniform(0.5, 2.0, n),
            "low": closes - rng.uniform(0.5, 2.0, n),
            "close": closes,
            "volume": rng.integers(50, 200, n),
        },
        index=idx,
    )


class TestPhase103TradeIntegrity(unittest.TestCase):
    def setUp(self) -> None:
        self.candles = _candles()
        self.calc = ATRTradeCalculator()
        self.validator = TradeIntegrityValidator(risk_percent=0.005, target_rr=2.0)
        self.builder = VirtualTradeBuilder(risk_percent=0.005)
        self.broker = PaperBroker(BrokerConfig())

    def test_ast_scan_no_forbidden(self):
        self.assertEqual(scan_live_shadow_ast(), [])

    def test_no_execution_imports_in_new_modules(self):
        for name in (
            "sl_tp_calculator.py",
            "trade_integrity.py",
            "virtual_trade_builder.py",
            "trade_integrity_logger.py",
        ):
            tree = ast.parse((INTEGRATION / name).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        for token in FORBIDDEN:
                            self.assertNotIn(token, alias.name)
                if isinstance(node, ast.ImportFrom) and node.module:
                    for token in FORBIDDEN:
                        self.assertNotIn(token, node.module)

    def test_buy_sl_calculation(self):
        levels = self.calc.compute(self.candles, 100, "BUY")
        assert levels is not None
        self.assertLess(levels.stop_loss, levels.entry)

    def test_buy_tp_calculation(self):
        levels = self.calc.compute(self.candles, 100, "BUY")
        assert levels is not None
        self.assertGreater(levels.take_profit, levels.entry)

    def test_sell_sl_calculation(self):
        levels = self.calc.compute(self.candles, 100, "SELL")
        assert levels is not None
        self.assertGreater(levels.stop_loss, levels.entry)

    def test_sell_tp_calculation(self):
        levels = self.calc.compute(self.candles, 100, "SELL")
        assert levels is not None
        self.assertLess(levels.take_profit, levels.entry)

    def test_rr_ratio_is_two(self):
        levels = self.calc.compute(self.candles, 100, "BUY")
        assert levels is not None
        self.assertAlmostEqual(levels.rr_ratio, 2.0, places=2)

    def test_invalid_sl_equals_entry_detected(self):
        result = self.validator.validate_trade(
            entry=2300.0,
            stop_loss=2300.0,
            take_profit=2310.0,
            direction="BUY",
            equity=10_000.0,
        )
        self.assertFalse(result.valid)
        self.assertTrue(any("stop_loss equals entry" in e for e in result.errors))

    def test_invalid_tp_equals_entry_detected(self):
        result = self.validator.validate_trade(
            entry=2300.0,
            stop_loss=2290.0,
            take_profit=2300.0,
            direction="BUY",
            equity=10_000.0,
        )
        self.assertFalse(result.valid)

    def test_buy_level_ordering(self):
        levels = self.calc.compute(self.candles, 100, "BUY")
        assert levels is not None
        result = self.validator.validate_levels(levels, equity=10_000.0, lot=0.01)
        self.assertTrue(result.valid)

    def test_sell_level_ordering(self):
        levels = self.calc.compute(self.candles, 100, "SELL")
        assert levels is not None
        result = self.validator.validate_levels(levels, equity=10_000.0, lot=0.01)
        self.assertTrue(result.valid)

    def test_position_sizing(self):
        size, risk_amt = self.validator.compute_position_size(10_000.0, 0.005, 2300.0, 2290.0)
        self.assertEqual(risk_amt, 50.0)
        self.assertGreater(size, 0)

    def test_zero_stop_distance_position_size(self):
        size, risk_amt = self.validator.compute_position_size(10_000.0, 0.005, 2300.0, 2300.0)
        self.assertEqual(size, 0.0)
        self.assertEqual(risk_amt, 50.0)

    def test_atr_positive(self):
        levels = self.calc.compute(self.candles, 100, "BUY")
        assert levels is not None
        self.assertGreater(levels.atr, 0)

    def test_zero_atr_handling(self):
        result = self.validator.validate_trade(
            entry=2300.0,
            stop_loss=2290.0,
            take_profit=2320.0,
            direction="BUY",
            equity=10_000.0,
            atr=0.0,
        )
        self.assertFalse(result.valid)
        self.assertTrue(any("ATR" in e for e in result.errors))

    def test_virtual_broker_buy_sl_before_tp(self):
        bar = pd.Series({"open": 100, "high": 105, "low": 94, "close": 101})
        hit = self.broker.resolve_bar(bar, direction=1, stop_loss=95, take_profit=104)
        self.assertEqual(hit, ("SL", 95.0))

    def test_virtual_broker_sell_sl_before_tp(self):
        bar = pd.Series({"open": 100, "high": 106, "low": 95, "close": 99})
        hit = self.broker.resolve_bar(bar, direction=-1, stop_loss=105, take_profit=96)
        self.assertEqual(hit, ("SL", 105.0))

    def test_virtual_broker_buy_tp_only(self):
        bar = pd.Series({"open": 100, "high": 110, "low": 99, "close": 108})
        hit = self.broker.resolve_bar(bar, direction=1, stop_loss=95, take_profit=105)
        self.assertEqual(hit, ("TP", 105.0))

    def test_builder_produces_valid_plan(self):
        plan, invalid = self.builder.build(
            candles=self.candles,
            bar_index=100,
            direction="BUY",
            symbol="XAUUSD",
            timestamp="2024-06-01T12:00:00+00:00",
            equity=10_000.0,
            risk_lot=0.01,
        )
        self.assertIsNotNone(plan)
        self.assertIsNone(invalid)
        self.assertEqual(plan.validation_status, "valid")

    def test_builder_rejects_bad_direction(self):
        plan, invalid = self.builder.build(
            candles=self.candles,
            bar_index=100,
            direction="HOLD",
            symbol="XAUUSD",
            timestamp="t",
            equity=10_000.0,
        )
        self.assertIsNone(plan)
        self.assertIsNotNone(invalid)

    def test_integrity_logger_writes_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            save_trade_integrity_artifacts(
                "test_run",
                valid_trades=[{"rr_ratio": 2.0}],
                invalid_trades=[],
                base_dir=tmp,
            )
            self.assertTrue(ml_trade_integrity_report_path("test_run", tmp).is_file())
            report = json.loads(ml_trade_integrity_report_path("test_run", tmp).read_text())
            self.assertTrue(report["all_valid"])

    def test_deterministic_atr_levels(self):
        a = self.calc.compute(self.candles, 100, "BUY")
        b = self.calc.compute(self.candles, 100, "BUY")
        assert a is not None and b is not None
        self.assertEqual(a.entry, b.entry)
        self.assertEqual(a.stop_loss, b.stop_loss)
        self.assertEqual(a.take_profit, b.take_profit)

    def test_invalid_trades_logged_on_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            save_trade_integrity_artifacts(
                "bad_run",
                valid_trades=[],
                invalid_trades=[{"blocked_reason": "test"}],
                base_dir=tmp,
            )
            invalid = json.loads(ml_trade_integrity_invalid_path("bad_run", tmp).read_text())
            self.assertEqual(len(invalid), 1)


if __name__ == "__main__":
    unittest.main()

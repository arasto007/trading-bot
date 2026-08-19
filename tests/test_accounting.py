"""Unit tests for unified accounting engine."""

from __future__ import annotations

import unittest

from tradingbot.accounting.broker_constraints import constraints_for_symbol
from tradingbot.accounting.engine import AccountingEngine
from tradingbot.accounting.pnl import calculate_pnl
from tradingbot.accounting.position_sizing import resolve_position_size
from tradingbot.services.exit_policy import _pnl as exit_policy_pnl


class TestAccountingPnl(unittest.TestCase):
    def test_pnl_matches_exit_policy(self) -> None:
        entry, exit_p = 3300.0, 3290.0
        lot = 0.01
        self.assertEqual(
            calculate_pnl(entry, exit_p, is_buy=True, lot=lot, symbol="XAUUSD"),
            exit_policy_pnl(entry, exit_p, is_buy=True, lot=lot, symbol="XAUUSD"),
        )


class TestPositionSizing(unittest.TestCase):
    def test_min_lot_limit_recorded(self) -> None:
        result = resolve_position_size(
            equity=200.0,
            configured_risk_percent=0.3,
            entry_price=3300.0,
            stop_loss=3290.0,
            symbol="XAUUSD",
        )
        self.assertTrue(result.min_lot_limit_applied)
        self.assertEqual(result.limit_reason, "MIN_LOT_LIMIT")
        self.assertEqual(result.executed_lot, 0.01)
        self.assertGreater(result.actual_risk_percent, result.configured_risk_percent)

    def test_risk_deviation_reported(self) -> None:
        result = resolve_position_size(
            equity=200.0,
            configured_risk_percent=0.3,
            entry_price=3300.0,
            stop_loss=3290.0,
            symbol="XAUUSD",
        )
        self.assertNotEqual(result.risk_deviation_percent, 0.0)


class TestAccountingEngine(unittest.TestCase):
    def test_close_updates_balance(self) -> None:
        engine = AccountingEngine(initial_balance=200.0, symbol="XAUUSD")
        engine.close_trade(
            exit_info={
                "exit_timestamp": "2026-01-01T01:00:00+00:00",
                "exit_price": 3290.0,
                "exit_reason": "sl",
                "pnl": -10.0,
                "pnl_r": -1.0,
                "duration_bars": 5,
                "duration_sec": 1500,
                "mae": 1.0,
                "mfe": 0.5,
                "spread": 0.3,
            },
            entry_timestamp="2026-01-01T00:00:00+00:00",
            entry_price=3300.0,
            direction="BUY",
            lot=0.01,
            sl=3290.0,
            tp=3320.0,
            risk_percent=0.3,
        )
        self.assertEqual(engine.balance, 190.0)
        self.assertEqual(engine.realized_pnl, -10.0)
        self.assertEqual(len(engine.ledger.closed_trades), 1)

    def test_performance_metrics(self) -> None:
        engine = AccountingEngine(initial_balance=200.0)
        for pnl in (10.0, -5.0, 15.0):
            engine.close_trade(
                exit_info={
                    "exit_timestamp": "2026-01-01T01:00:00+00:00",
                    "exit_price": 3300.0,
                    "exit_reason": "tp",
                    "pnl": pnl,
                    "pnl_r": 1.0,
                    "duration_bars": 1,
                    "duration_sec": 300,
                    "mae": 0.0,
                    "mfe": 1.0,
                    "spread": 0.3,
                },
                entry_timestamp="2026-01-01T00:00:00+00:00",
                entry_price=3290.0,
                direction="BUY",
                lot=0.01,
                sl=3280.0,
                tp=3310.0,
            )
        perf = engine.performance_metrics()
        self.assertEqual(perf["net_profit"], 20.0)
        self.assertEqual(perf["completed_trades"], 3)


class TestBrokerConstraints(unittest.TestCase):
    def test_margin_calculation(self) -> None:
        bc = constraints_for_symbol("XAUUSD", leverage=100.0)
        margin = bc.margin_required(0.01, 3300.0)
        self.assertAlmostEqual(margin, 33.0, places=1)


if __name__ == "__main__":
    unittest.main()

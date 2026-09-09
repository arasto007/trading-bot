"""Phase 25A — symbol mapping, broker economics, sizing, volume constraints."""

from __future__ import annotations

import math
import unittest
from unittest.mock import patch

from tradingbot.adapters.symbols import (
    SymbolResolutionError,
    get_environment_trading_symbol,
    parse_account_environment,
    resolve_broker_symbol,
    validate_configured_symbol,
    validate_configured_symbol_or_raise,
)
from tradingbot.domain.broker_economics import (
    BrokerEconomics,
    lot_from_broker_economics,
    validate_sl_tp_vs_stops,
)
from tradingbot.domain.order_logic import check_order_risk, order_value


def _xau_economics(symbol: str = "XAUUSD_i") -> BrokerEconomics:
    return BrokerEconomics.from_mapping(
        symbol,
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


class TestOrderValueParity(unittest.TestCase):
    def test_same_economics_same_notional_regardless_of_name(self) -> None:
        eco_i = _xau_economics("XAUUSD_i")
        eco_bare = _xau_economics("XAUUSD")
        v_i = order_value("XAUUSD_i", 0.01, 2000.0, economics=eco_i)
        v_bare = order_value("XAUUSD", 0.01, 2000.0, economics=eco_bare)
        self.assertEqual(v_i, 2000.0)
        self.assertEqual(v_bare, 2000.0)
        self.assertEqual(v_i, v_bare)

    def test_order_value_requires_economics(self) -> None:
        self.assertEqual(order_value("XAUUSD_i", 0.01, 2000.0), 0.0)
        ok, reason = check_order_risk("XAUUSD_i", 0.01, 2000.0)
        self.assertFalse(ok)
        self.assertIn("BROKER_ECONOMICS_REQUIRED", reason)


class TestTickBasedSizing(unittest.TestCase):
    def test_half_percent_risk_preserved(self) -> None:
        eco = _xau_economics()
        equity = 10_000.0
        entry = 2000.0
        sl = 1990.0  # $10 stop distance
        lot, reason = lot_from_broker_economics(equity, 0.005, entry, sl, eco)
        self.assertIsNone(reason)
        assert lot is not None
        loss_per_lot = eco.monetary_loss_per_lot(10.0)
        assert loss_per_lot is not None
        actual_risk = lot * loss_per_lot
        self.assertAlmostEqual(actual_risk, equity * 0.005, places=1)

    def test_missing_tick_size_fails_closed(self) -> None:
        eco = _xau_economics()
        bad = BrokerEconomics.from_mapping(
            "BAD",
            {
                "point": 0.01,
                "digits": 2,
                "contract_size": 100.0,
                "tick_size": 0.0,
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
        lot, reason = lot_from_broker_economics(10_000, 0.005, 2000, 1990, bad)
        self.assertIsNone(lot)
        self.assertEqual(reason, "INVALID_TICK_SIZE")

    def test_missing_tick_value_fails_closed(self) -> None:
        eco = BrokerEconomics.from_mapping(
            "BAD",
            {
                "point": 0.01,
                "digits": 2,
                "contract_size": 100.0,
                "tick_size": 0.01,
                "tick_value": 0.0,
                "tick_value_profit": 0.0,
                "tick_value_loss": 0.0,
                "volume_min": 0.01,
                "volume_max": 100.0,
                "volume_step": 0.01,
                "stops_level": 0,
                "freeze_level": 0,
            },
        )
        lot, reason = lot_from_broker_economics(10_000, 0.005, 2000, 1990, eco)
        self.assertIsNone(lot)
        self.assertIn("INVALID", reason or "")

    def test_invalid_stop_distance(self) -> None:
        eco = _xau_economics()
        lot, reason = lot_from_broker_economics(10_000, 0.005, 2000, 2000, eco)
        self.assertIsNone(lot)
        self.assertEqual(reason, "INVALID_STOP_DISTANCE")


class TestVolumeConstraints(unittest.TestCase):
    def test_below_min_rejected(self) -> None:
        eco = _xau_economics()
        lot, reason = lot_from_broker_economics(50.0, 0.005, 2000, 1990.0, eco)
        self.assertIsNone(lot)
        self.assertEqual(reason, "VOLUME_BELOW_MIN")

    def test_floor_to_step_not_up(self) -> None:
        eco = _xau_economics()
        self.assertEqual(eco.floor_to_volume_step(0.011), 0.01)
        self.assertEqual(eco.floor_to_volume_step(0.019), 0.01)
        self.assertEqual(eco.floor_to_volume_step(0.007), 0.0)

    def test_max_volume_cap(self) -> None:
        eco = _xau_economics()
        lot, _ = lot_from_broker_economics(10_000_000, 0.005, 2000, 1990, eco)
        self.assertIsNotNone(lot)
        assert lot is not None
        self.assertLessEqual(lot, eco.volume_max)

    def test_no_upward_risk_increase(self) -> None:
        eco = _xau_economics()
        equity = 793.99
        entry = 4374.0
        sl = 4371.0  # $3 stop — raw lot ~0.013, floors to 0.01
        lot, _ = lot_from_broker_economics(equity, 0.005, entry, sl, eco)
        self.assertIsNotNone(lot)
        assert lot is not None
        loss = eco.monetary_loss_per_lot(abs(entry - sl))
        assert loss is not None
        self.assertLessEqual(lot * loss, equity * 0.005 * 1.0001)


class TestStopsFreeze(unittest.TestCase):
    def test_stops_level_conversion(self) -> None:
        eco = BrokerEconomics.from_mapping(
            "X",
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
                "stops_level": 50,
                "freeze_level": 0,
            },
        )
        self.assertAlmostEqual(eco.stops_distance_price(), 0.5)

    def test_sl_inside_stops_rejected(self) -> None:
        eco = BrokerEconomics.from_mapping(
            "X",
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
                "stops_level": 100,
                "freeze_level": 0,
            },
        )
        ok, msg = validate_sl_tp_vs_stops(2000.0, 1999.5, None, is_buy=True, economics=eco)
        self.assertFalse(ok)
        self.assertIn("stops_level", msg)

    def test_zero_stops_allows(self) -> None:
        eco = _xau_economics()
        ok, msg = validate_sl_tp_vs_stops(2000.0, 1990.0, 2010.0, is_buy=True, economics=eco)
        self.assertTrue(ok)
        self.assertEqual(msg, "ok")


class TestSymbolMapping(unittest.TestCase):
    def test_demo_real_map_to_xauusd_i(self) -> None:
        cfg = {
            "ACCOUNT_ENVIRONMENT": "DEMO",
            "SYMBOL_BY_ENVIRONMENT": {"DEMO": "XAUUSD_i", "REAL": "XAUUSD_i"},
            "BROKER_SYMBOL_CATALOG": {"XAUUSD_i": {"exists": True}},
        }
        self.assertEqual(get_environment_trading_symbol(cfg), "XAUUSD_i")
        cfg["ACCOUNT_ENVIRONMENT"] = "REAL"
        self.assertEqual(get_environment_trading_symbol(cfg), "XAUUSD_i")

    def test_missing_symbol_fail_closed(self) -> None:
        cfg = {
            "SYMBOL_BY_ENVIRONMENT": {"DEMO": "XAUUSD_i", "REAL": "XAUUSD_i"},
            "BROKER_SYMBOL_CATALOG": {"XAUUSD_i": {"exists": False}},
        }
        ok, reason = validate_configured_symbol("XAUUSD_i", cfg)
        self.assertFalse(ok)
        with self.assertRaises(SymbolResolutionError):
            validate_configured_symbol_or_raise("XAUUSD_i", cfg)

    def test_no_automatic_fallback(self) -> None:
        cfg = {
            "ACCOUNT_ENVIRONMENT": "DEMO",
            "SYMBOL_BY_ENVIRONMENT": {"DEMO": "XAUUSD_i", "REAL": "XAUUSD_i"},
            "SYMBOL_RESOLUTION_STRICT": True,
            "BROKER_SYMBOL_CATALOG": {"XAUUSD_i": {"exists": True}},
        }
        resolved = resolve_broker_symbol("XAUUSD", cfg)
        self.assertEqual(resolved, "XAUUSD_i")

    def test_resolver_does_not_symbol_select(self) -> None:
        cfg = {
            "SYMBOL_BY_ENVIRONMENT": {"DEMO": "XAUUSD_i", "REAL": "XAUUSD_i"},
            "BROKER_SYMBOL_CATALOG": {"XAUUSD_i": {"exists": True}},
        }
        with patch("MetaTrader5.symbol_select") as mock_select:
            resolve_broker_symbol("XAUUSD_i", cfg)
            mock_select.assert_not_called()


class TestEnvironmentParsing(unittest.TestCase):
    def test_parse_demo_real(self) -> None:
        self.assertEqual(parse_account_environment({"ACCOUNT_ENVIRONMENT": "DEMO"}), "DEMO")
        self.assertEqual(parse_account_environment({"ACCOUNT_ENVIRONMENT": "REAL"}), "REAL")


if __name__ == "__main__":
    unittest.main()

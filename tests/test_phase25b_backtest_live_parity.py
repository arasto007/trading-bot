"""Phase 25B — backtest/live execution reconcile and parity matrix (offline only)."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd

from tradingbot.adapters.mt5_execution import Mt5ExecutionAdapter
from tradingbot.backtest.broker import SimulatedBroker
from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.cost_model import CostAvailability, build_backtest_cost_model
from tradingbot.backtest.data_source import BacktestMarketData
from tradingbot.backtest.instrument import OFFLINE_INSTRUMENT_CATALOG, resolve_backtest_economics
from tradingbot.backtest.risk import BacktestRiskGate
from tradingbot.config.live import LIVE_TRADING_CONFIG, PRIMARY_SYMBOL
from tradingbot.config.pa_symbol_tf_presets import get_symbol_tf_overrides
from tradingbot.domain.broker_economics import BrokerEconomics, lot_from_broker_economics
from tradingbot.domain.gold_strategies.m5_london_sweep import _in_entry_window, m5_ny_entry_hours
from tradingbot.domain.ohlcv import exclude_forming_bar
from tradingbot.services.demo_account_guard import allow_real_account_trading


def _xau_economics(symbol: str = "XAUUSD_i") -> BrokerEconomics:
    return BrokerEconomics.from_mapping(symbol, OFFLINE_INSTRUMENT_CATALOG["XAUUSD_i"])


def _legacy_catalog() -> dict:
    return {"BROKER_SYMBOL_CATALOG": {"XAUUSD_i": dict(OFFLINE_INSTRUMENT_CATALOG["XAUUSD_i"])}}


class TestBacktestDefaults(unittest.TestCase):
    def test_production_defaults(self) -> None:
        cfg = BacktestConfig()
        self.assertEqual(cfg.symbols, [PRIMARY_SYMBOL])
        self.assertEqual(cfg.timeframe, "M5")
        self.assertAlmostEqual(cfg.risk_per_trade, 0.005)
        self.assertFalse(cfg.require_htf_alignment_m5)
        self.assertFalse(cfg.require_htf_alignment_m15)
        self.assertEqual(cfg.htf_timeframe, "H4")
        self.assertTrue(cfg.simulate_forming_bar)

    def test_live_risk_default(self) -> None:
        self.assertAlmostEqual(LIVE_TRADING_CONFIG["RISK_PER_TRADE"], 0.005)


class TestSymbolReconcile(unittest.TestCase):
    def test_reconcile_does_not_symbol_select(self) -> None:
        adapter = Mt5ExecutionAdapter({"BASE_DIR": ".", "SYMBOL_BY_ENVIRONMENT": {"DEMO": "XAUUSD_i"}})
        info = MagicMock()
        info.visible = False
        info.trade_mode = 4
        with patch("MetaTrader5.symbol_info", return_value=info), patch(
            "MetaTrader5.symbol_select"
        ) as mock_select, patch(
            "tradingbot.adapters.mt5_execution.resolve_broker_symbol", return_value="XAUUSD_i"
        ):
            broker, err = adapter._reconcile_broker_symbol("XAUUSD_i")
            mock_select.assert_not_called()
        self.assertIsNone(broker)
        self.assertIn("SYMBOL_NOT_VISIBLE", err or "")

    def test_reconcile_uses_configured_symbol(self) -> None:
        adapter = Mt5ExecutionAdapter({"BASE_DIR": "."})
        info = MagicMock()
        info.visible = True
        info.trade_mode = 4
        with patch("MetaTrader5.symbol_info", return_value=info), patch(
            "tradingbot.adapters.mt5_execution.resolve_broker_symbol", return_value="XAUUSD_i"
        ) as mock_resolve:
            broker, err = adapter._reconcile_broker_symbol("XAUUSD_i")
            mock_resolve.assert_called_once()
        self.assertEqual(broker, "XAUUSD_i")
        self.assertIsNone(err)


class TestCrossPathSizingParity(unittest.TestCase):
    def test_same_economics_same_lot(self) -> None:
        eco = _xau_economics()
        legacy = _legacy_catalog()
        equity = 10_000.0
        entry = 2000.0
        sl = 1990.0
        live_lot, live_reason = lot_from_broker_economics(equity, 0.005, entry, sl, eco)
        gate = BacktestRiskGate(BacktestConfig(), legacy)
        bt_lot = gate._position_size(equity, entry, sl, "XAUUSD_i", risk_pct=0.005)
        self.assertIsNone(live_reason)
        self.assertAlmostEqual(live_lot or 0.0, bt_lot)

    def test_volume_floor_parity(self) -> None:
        eco = _xau_economics()
        broker_cfg = BacktestConfig()
        broker = SimulatedBroker(broker_cfg, MagicMock(), legacy_config=_legacy_catalog())
        self.assertEqual(broker._normalize_lot(0.011, eco), 0.01)
        self.assertEqual(broker._normalize_lot(0.007, eco), 0.0)
        self.assertEqual(broker._normalize_lot(0.003, eco), 0.0)


class TestFormingBarParity(unittest.TestCase):
    def test_synthetic_forming_bar_excluded(self) -> None:
        idx = pd.date_range("2024-01-01 15:00", periods=5, freq="5min", tz="UTC")
        df = pd.DataFrame(
            {
                "open": [1.0, 1.1, 1.2, 1.3, 1.4],
                "high": [1.1, 1.2, 1.3, 1.4, 1.5],
                "low": [0.9, 1.0, 1.1, 1.2, 1.3],
                "close": [1.05, 1.15, 1.25, 1.35, 1.45],
                "volume": [100] * 5,
            },
            index=idx,
        )
        cfg = BacktestConfig(timeframe="M5", simulate_forming_bar=True)
        md = BacktestMarketData(cfg, {})
        md._frames = {"XAUUSD_i": df}
        md._length = len(df)
        md.set_cursor(4)
        window = md.get_ohlcv_window("XAUUSD_i", bars=500)
        assert window is not None
        self.assertEqual(len(window), 6)  # 5 closed + 1 synthetic forming
        closed = exclude_forming_bar(window, min_rows=1)
        assert closed is not None
        self.assertEqual(closed.index[-1], idx[4])


class TestSessionParity(unittest.TestCase):
    def test_ny_session_boundaries(self) -> None:
        pa = get_symbol_tf_overrides("XAUUSD_i", "M5")
        start, end = m5_ny_entry_hours(pa)
        self.assertEqual((start, end), (15, 16))
        idx = pd.date_range("2024-01-02 14:00", periods=3, freq="1h", tz="UTC")
        df = pd.DataFrame(
            {"open": [1.0] * 3, "high": [1.0] * 3, "low": [1.0] * 3, "close": [1.0] * 3, "volume": [1] * 3},
            index=idx,
        )
        self.assertFalse(_in_entry_window(df, 0, pa))  # 14 UTC
        self.assertTrue(_in_entry_window(df, 1, pa))   # 15 UTC
        self.assertFalse(_in_entry_window(df, 2, pa))  # 16 UTC


class TestHtfParity(unittest.TestCase):
    def test_m5_htf_not_required(self) -> None:
        pa = get_symbol_tf_overrides("XAUUSD_i", "M5")
        self.assertFalse(pa.get("REQUIRE_HTF_ALIGNMENT_M5"))
        cfg = BacktestConfig()
        self.assertFalse(cfg.require_htf_alignment_m5)


class TestSpreadAndCostModel(unittest.TestCase):
    def test_proxy_spread_mode(self) -> None:
        cfg = BacktestConfig(spread_mode="PROXY", slippage_status="MODELED_PROXY", commission_status="ZERO")
        model = build_backtest_cost_model(cfg, spread_mode="PROXY")
        self.assertEqual(model.spread_mode.value, "PROXY")
        self.assertEqual(model.spread.availability, CostAvailability.MODELED)
        self.assertIsNotNone(model.spread_pips_at_hour(15))

    def test_unknown_spread_mode(self) -> None:
        cfg = BacktestConfig(spread_mode="UNKNOWN")
        model = build_backtest_cost_model(cfg, spread_mode="UNKNOWN")
        self.assertEqual(model.spread.availability, CostAvailability.UNKNOWN)

    def test_commission_zero_explicit(self) -> None:
        cfg = BacktestConfig(commission_per_lot=0.0, commission_status="ZERO")
        model = build_backtest_cost_model(cfg)
        self.assertEqual(model.commission.availability, CostAvailability.ZERO)

    def test_swap_unknown(self) -> None:
        model = build_backtest_cost_model(BacktestConfig())
        self.assertEqual(model.swap.availability, CostAvailability.UNKNOWN)


class TestRealSafetyGate(unittest.TestCase):
    def test_unset_blocks_real(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            if "TRADINGBOT_ALLOW_REAL" in __import__("os").environ:
                del __import__("os").environ["TRADINGBOT_ALLOW_REAL"]
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(allow_real_account_trading())

    def test_explicit_allow(self) -> None:
        with patch.dict("os.environ", {"TRADINGBOT_ALLOW_REAL": "1"}):
            self.assertTrue(allow_real_account_trading())


class TestOfflineEconomics(unittest.TestCase):
    def test_resolve_without_mt5(self) -> None:
        eco = resolve_backtest_economics("XAUUSD_i", _legacy_catalog())
        self.assertIsNotNone(eco)
        assert eco is not None
        self.assertEqual(eco.contract_size, 100.0)

    def test_missing_symbol_fails_closed(self) -> None:
        eco = resolve_backtest_economics("EURUSD", {}, allow_offline_fallback=False)
        self.assertIsNone(eco)


if __name__ == "__main__":
    unittest.main()

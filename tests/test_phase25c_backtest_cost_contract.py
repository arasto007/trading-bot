"""Phase 25C — retry hardening, dataset instrument contract, cost traceability."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from tradingbot.adapters.mt5_execution import (
    Mt5ExecutionAdapter,
    _order_send_with_retry,
    _refresh_retry_price_from_tick,
)
from tradingbot.backtest.broker import SimulatedBroker
from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.cost_model import (
    CostAvailability,
    CostCompleteness,
    SpreadMode,
    assess_cost_completeness,
    build_backtest_cost_model,
    detect_spread_mode_from_frame,
    estimate_round_trip_cost,
    spread_pips_from_bar,
)
from tradingbot.backtest.dataset_contract import (
    InstrumentContractError,
    resolve_broker_symbol_for_dataset,
    resolve_dataset_instrument,
    validate_dataset_frames,
)
from tradingbot.backtest.instrument import OFFLINE_INSTRUMENT_CATALOG
from tradingbot.backtest.metrics import compute_metrics
from tradingbot.backtest.models import BacktestResult
from tradingbot.config.live import PRIMARY_SYMBOL
from tradingbot.services.demo_account_guard import allow_real_account_trading


def _legacy() -> dict:
    return {"BROKER_SYMBOL_CATALOG": {"XAUUSD_i": dict(OFFLINE_INSTRUMENT_CATALOG["XAUUSD_i"])}}


def _ohlc_only_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {"open": [1.0], "high": [1.1], "low": [0.9], "close": [1.05], "volume": [1.0]}
    )


def _bid_ask_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [2000.0],
            "high": [2001.0],
            "low": [1999.0],
            "close": [2000.0],
            "volume": [100.0],
            "bid": [1999.85],
            "ask": [2000.15],
        }
    )


class TestRetrySymbolSelect(unittest.TestCase):
    def test_retry_does_not_symbol_select(self) -> None:
        mt5 = MagicMock()
        mt5.ORDER_TYPE_BUY = 0
        result_ok = MagicMock(retcode=10009)
        mt5.order_send = MagicMock(side_effect=[MagicMock(retcode=10004), result_ok])
        request = {"type": mt5.ORDER_TYPE_BUY, "symbol": "XAUUSD_i", "volume": 0.01}
        with patch("MetaTrader5.symbol_select") as mock_select, patch(
            "tradingbot.adapters.mt5_execution.ensure_mt5_connected"
        ), patch("time.sleep"), patch(
            "tradingbot.adapters.mt5_execution._refresh_retry_price_from_tick", return_value=True
        ):
            out = _order_send_with_retry(mt5, request, {}, "XAUUSD_i")
            mock_select.assert_not_called()
        self.assertIs(out, result_ok)
        self.assertEqual(request["symbol"], "XAUUSD_i")

    def test_refresh_price_without_symbol_select(self) -> None:
        mt5 = MagicMock()
        mt5.ORDER_TYPE_BUY = 0
        tick = MagicMock(ask=2000.5, bid=2000.3)
        mt5.symbol_info_tick.return_value = tick
        req = {"type": mt5.ORDER_TYPE_BUY}
        self.assertTrue(_refresh_retry_price_from_tick(mt5, req, "XAUUSD_i"))
        self.assertEqual(req["price"], 2000.5)

    def test_reconcile_still_no_symbol_select(self) -> None:
        adapter = Mt5ExecutionAdapter({"BASE_DIR": "."})
        info = MagicMock(visible=False, trade_mode=4)
        with patch("MetaTrader5.symbol_info", return_value=info), patch(
            "MetaTrader5.symbol_select"
        ) as mock_select, patch(
            "tradingbot.adapters.mt5_execution.resolve_broker_symbol", return_value="XAUUSD_i"
        ):
            broker, err = adapter._reconcile_broker_symbol("XAUUSD_i")
            mock_select.assert_not_called()
        self.assertIsNone(broker)
        self.assertIn("SYMBOL_NOT_VISIBLE", err or "")


class TestDatasetSymbolContract(unittest.TestCase):
    def test_matching_symbol(self) -> None:
        broker, src = resolve_broker_symbol_for_dataset(
            "XAUUSD_i", configured_symbol="XAUUSD_i"
        )
        self.assertEqual(broker, "XAUUSD_i")
        self.assertEqual(src, "match")

    def test_mismatch_requires_explicit_map(self) -> None:
        with self.assertRaises(InstrumentContractError) as ctx:
            resolve_broker_symbol_for_dataset("XAUUSD", configured_symbol="XAUUSD_i")
        self.assertEqual(ctx.exception.code, "SYMBOL_MISMATCH")

    def test_explicit_mapping(self) -> None:
        broker, src = resolve_broker_symbol_for_dataset(
            "XAUUSD",
            configured_symbol="XAUUSD_i",
            dataset_symbol_map={"XAUUSD": "XAUUSD_i"},
        )
        self.assertEqual(broker, "XAUUSD_i")
        self.assertEqual(src, "explicit_map")

    def test_missing_economics_fail_closed(self) -> None:
        with self.assertRaises(InstrumentContractError) as ctx:
            resolve_dataset_instrument(
                "UNKNOWN_SYM",
                configured_symbol="UNKNOWN_SYM",
                legacy_config={},
                allow_offline_fallback=False,
            )
        self.assertEqual(ctx.exception.code, "ECONOMICS_UNAVAILABLE")

    def test_invalid_economics(self) -> None:
        bad = {
            "BROKER_SYMBOL_CATALOG": {
                "XAUUSD_i": {
                    **OFFLINE_INSTRUMENT_CATALOG["XAUUSD_i"],
                    "tick_size": 0.0,
                }
            }
        }
        with self.assertRaises(InstrumentContractError) as ctx:
            resolve_dataset_instrument("XAUUSD_i", configured_symbol="XAUUSD_i", legacy_config=bad)
        self.assertEqual(ctx.exception.code, "INVALID_ECONOMICS")

    def test_validate_frames(self) -> None:
        frames = {"XAUUSD_i": _ohlc_only_frame()}
        contracts = validate_dataset_frames(
            frames, configured_symbol="XAUUSD_i", legacy_config=_legacy()
        )
        self.assertIn("XAUUSD_i", contracts)


class TestSpreadModes(unittest.TestCase):
    def test_detect_bid_ask_dataset(self) -> None:
        self.assertEqual(detect_spread_mode_from_frame(_bid_ask_frame()), SpreadMode.DATASET)

    def test_detect_ohlc_proxy(self) -> None:
        self.assertEqual(detect_spread_mode_from_frame(_ohlc_only_frame()), SpreadMode.PROXY)

    def test_bid_ask_spread_calculation(self) -> None:
        bar = _bid_ask_frame().iloc[0]
        pips = spread_pips_from_bar(bar, symbol="XAUUSD_i")
        self.assertIsNotNone(pips)
        assert pips is not None
        self.assertAlmostEqual(pips, 3.0, places=2)

    def test_proxy_mode_not_labeled_dataset(self) -> None:
        cfg = BacktestConfig(spread_mode="PROXY")
        model = build_backtest_cost_model(cfg, spread_mode="PROXY", frame=_ohlc_only_frame())
        self.assertEqual(model.spread_mode, SpreadMode.PROXY)
        self.assertEqual(model.spread.source, "variable_proxy")

    def test_unknown_spread_mode(self) -> None:
        cfg = BacktestConfig(spread_mode="UNKNOWN")
        model = build_backtest_cost_model(cfg, spread_mode="UNKNOWN")
        self.assertEqual(model.spread.availability, CostAvailability.UNKNOWN)


class TestCommissionSwapSlippage(unittest.TestCase):
    def test_commission_zero_requires_evidence(self) -> None:
        cfg = BacktestConfig(commission_per_lot=0.0, commission_status="ZERO")
        model = build_backtest_cost_model(cfg)
        self.assertEqual(model.commission.availability, CostAvailability.ZERO)

    def test_commission_unknown_by_default(self) -> None:
        cfg = BacktestConfig(commission_per_lot=0.0)
        model = build_backtest_cost_model(cfg)
        self.assertEqual(model.commission.availability, CostAvailability.UNKNOWN)

    def test_commission_modeled(self) -> None:
        cfg = BacktestConfig(commission_per_lot=3.5, commission_status="MODELED")
        model = build_backtest_cost_model(cfg)
        self.assertEqual(model.commission.availability, CostAvailability.MODELED)
        self.assertEqual(model.commission.value, 3.5)

    def test_swap_unknown(self) -> None:
        model = build_backtest_cost_model(BacktestConfig())
        self.assertEqual(model.swap.availability, CostAvailability.UNKNOWN)

    def test_slippage_modeled_proxy(self) -> None:
        cfg = BacktestConfig(slippage_pips=0.8, slippage_status="MODELED_PROXY")
        model = build_backtest_cost_model(cfg)
        self.assertEqual(model.slippage.availability, CostAvailability.MODELED_PROXY)
        self.assertEqual(model.slippage.mode, "MODELED_PROXY")

    def test_slippage_unknown(self) -> None:
        cfg = BacktestConfig(slippage_status="UNKNOWN")
        model = build_backtest_cost_model(cfg)
        self.assertEqual(model.slippage.availability, CostAvailability.UNKNOWN)

    def test_deviation_not_slippage(self) -> None:
        from tradingbot.adapters import mt5_execution

        self.assertEqual(mt5_execution._DEVIATION, 20)
        cfg = BacktestConfig(slippage_status="UNKNOWN")
        model = build_backtest_cost_model(cfg)
        self.assertNotEqual(model.slippage.mode, "deviation")


class TestRoundTripCost(unittest.TestCase):
    def test_no_spread_double_count(self) -> None:
        cfg = BacktestConfig(
            spread_mode="PROXY",
            commission_status="ZERO",
            slippage_status="MODELED_PROXY",
            slippage_pips=0.8,
        )
        model = build_backtest_cost_model(cfg, spread_mode="PROXY")
        rt = estimate_round_trip_cost(model, hour=15)
        spread_traces = [t for t in rt.entry_traces + rt.exit_traces if t.component == "spread"]
        self.assertEqual(len(spread_traces), 2)
        self.assertAlmostEqual(sum(t.value or 0 for t in spread_traces), model.spread_pips_at_hour(15) or 0)

    def test_cost_completeness_partial(self) -> None:
        cfg = BacktestConfig(spread_mode="PROXY", commission_status="ZERO", swap_status="UNKNOWN")
        model = build_backtest_cost_model(cfg, spread_mode="PROXY")
        self.assertEqual(assess_cost_completeness(model), CostCompleteness.PARTIAL)


class TestBrokerCostSafety(unittest.TestCase):
    def test_commission_unknown_blocks_execute(self) -> None:
        cfg = BacktestConfig(commission_status="UNKNOWN")
        broker = SimulatedBroker(cfg, MagicMock(), legacy_config=_legacy())
        from tradingbot.domain.enums import SignalDirection
        from tradingbot.domain.models import TradingSignal

        sig = TradingSignal(
            direction=SignalDirection.BUY,
            confidence=0.6,
            symbol="XAUUSD_i",
            timeframe="M5",
            stop_loss=1990.0,
            take_profit=2010.0,
            strategy_name="test",
        )
        data = MagicMock()
        data.current_bar.return_value = _bid_ask_frame().iloc[0]
        data.current_time.return_value = None
        broker._data = data
        res = broker.execute(sig, 0.01)
        self.assertFalse(res.success)
        self.assertIn("commission", res.message.lower())

    def test_slippage_unknown_blocks_entry(self) -> None:
        cfg = BacktestConfig(
            commission_status="ZERO",
            slippage_status="UNKNOWN",
            spread_mode="PROXY",
        )
        broker = SimulatedBroker(cfg, MagicMock(), legacy_config=_legacy())
        from tradingbot.domain.enums import SignalDirection
        from tradingbot.domain.models import TradingSignal

        sig = TradingSignal(
            direction=SignalDirection.BUY,
            confidence=0.6,
            symbol="XAUUSD_i",
            timeframe="M5",
            stop_loss=1990.0,
            take_profit=2010.0,
            strategy_name="test",
        )
        data = MagicMock()
        data.current_bar.return_value = _ohlc_only_frame().iloc[0]
        data.current_time.return_value = None
        broker._data = data
        res = broker.execute(sig, 0.01)
        self.assertFalse(res.success)
        self.assertIn("slippage", res.message.lower())


class TestMetricsCostCompleteness(unittest.TestCase):
    def test_partial_not_cost_adjusted(self) -> None:
        result = BacktestResult(
            config=BacktestConfig(),
            initial_balance=1000,
            final_balance=1000,
            trades=[],
            cost_completeness="PARTIAL",
        )
        metrics = compute_metrics(result, cost_completeness="PARTIAL")
        self.assertEqual(metrics["cost_completeness"], "PARTIAL")
        self.assertFalse(metrics["cost_adjusted_metrics"])


class TestRealSafetyGate(unittest.TestCase):
    def test_unset_blocked(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(allow_real_account_trading())

    def test_explicit_allowed(self) -> None:
        with patch.dict("os.environ", {"TRADINGBOT_ALLOW_REAL": "true"}):
            self.assertTrue(allow_real_account_trading())


if __name__ == "__main__":
    unittest.main()

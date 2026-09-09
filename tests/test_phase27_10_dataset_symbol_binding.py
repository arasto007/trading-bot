"""Phase 27.10 — dataset symbol binding contract tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.data_source import BacktestMarketData
from tradingbot.backtest.dataset_contract import (
    InstrumentContractError,
    classify_dataset_binding,
    resolve_broker_symbol_for_dataset,
    resolve_dataset_instrument,
    validate_dataset_symbol_map,
)
from tradingbot.backtest.dataset_provenance import (
    DatasetMetadata,
    apply_sidecar_to_backtest_config,
    infer_symbol_from_filename,
)
from tradingbot.backtest.instrument import OFFLINE_INSTRUMENT_CATALOG
from tradingbot.backtest.phase27_10_dataset_symbol_binding import (
    CANONICAL_SYMBOL,
    PHASE2710_JSON,
    PHASE2710_MD,
    run_phase27_10_collection,
)
from tradingbot.config.live import PRIMARY_SYMBOL


def setUpModule() -> None:
    run_phase27_10_collection(Path(__file__).resolve().parents[1])


class TestPhase2710DatasetSymbolBinding(unittest.TestCase):
    def test_artifact_valid(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2710_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["phase"], "27.10")
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["canonical_production_symbol"], "XAUUSD_i")
        self.assertTrue(payload["canonical_unchanged"])

    def test_missing_map_fail_closed(self) -> None:
        with self.assertRaises(InstrumentContractError) as ctx:
            resolve_broker_symbol_for_dataset("XAUUSD", configured_symbol="XAUUSD_i")
        self.assertEqual(ctx.exception.code, "SYMBOL_MISMATCH")
        with self.assertRaises(InstrumentContractError):
            resolve_broker_symbol_for_dataset(
                "XAUUSD",
                configured_symbol="XAUUSD_i",
                dataset_symbol_map={},
            )

    def test_explicit_valid_map(self) -> None:
        broker, source = resolve_broker_symbol_for_dataset(
            "XAUUSD",
            configured_symbol="XAUUSD_i",
            dataset_symbol_map={"XAUUSD": "XAUUSD_i"},
        )
        self.assertEqual(broker, "XAUUSD_i")
        self.assertEqual(source, "explicit_map")
        binding = classify_dataset_binding(
            "XAUUSD",
            configured_symbol="XAUUSD_i",
            dataset_symbol_map={"XAUUSD": "XAUUSD_i"},
        )
        self.assertFalse(binding.blocked)
        self.assertEqual(binding.ev_eq_01, "NOT_PROVEN")

    def test_invalid_empty_map_target(self) -> None:
        with self.assertRaises(InstrumentContractError) as ctx:
            resolve_broker_symbol_for_dataset(
                "XAUUSD",
                configured_symbol="XAUUSD_i",
                dataset_symbol_map={"XAUUSD": ""},
            )
        self.assertEqual(ctx.exception.code, "INVALID_MAP")

    def test_invalid_self_map_not_canonical(self) -> None:
        with self.assertRaises(InstrumentContractError) as ctx:
            resolve_broker_symbol_for_dataset(
                "XAUUSD",
                configured_symbol="XAUUSD_i",
                dataset_symbol_map={"XAUUSD": "XAUUSD"},
            )
        self.assertEqual(ctx.exception.code, "INVALID_MAP")

    def test_invalid_other_symbol_map(self) -> None:
        with self.assertRaises(InstrumentContractError) as ctx:
            validate_dataset_symbol_map({"XAUUSD": "EURUSD"}, configured_symbol="XAUUSD_i")
        self.assertEqual(ctx.exception.code, "INVALID_MAP")

    def test_silent_fallback_prevented(self) -> None:
        binding = classify_dataset_binding("XAUUSD", configured_symbol="XAUUSD_i")
        self.assertTrue(binding.blocked)
        self.assertIsNone(binding.mapped_broker_symbol)
        self.assertNotEqual(binding.mapped_broker_symbol, "XAUUSD_i")

    def test_xauusd_i_direct_binding(self) -> None:
        broker, source = resolve_broker_symbol_for_dataset(
            "XAUUSD_i", configured_symbol="XAUUSD_i"
        )
        self.assertEqual(broker, "XAUUSD_i")
        self.assertEqual(source, "match")

    def test_economics_lookup_after_explicit_mapping(self) -> None:
        contract = resolve_dataset_instrument(
            "XAUUSD",
            configured_symbol="XAUUSD_i",
            dataset_symbol_map={"XAUUSD": "XAUUSD_i"},
        )
        self.assertEqual(contract.broker_symbol, "XAUUSD_i")
        self.assertEqual(contract.economics.symbol, "XAUUSD_i")
        self.assertEqual(contract.mapping_source, "explicit_map")
        self.assertNotIn("XAUUSD", OFFLINE_INSTRUMENT_CATALOG)

    def test_canonical_symbol_unchanged(self) -> None:
        self.assertEqual(PRIMARY_SYMBOL, "XAUUSD_i")
        self.assertEqual(CANONICAL_SYMBOL, "XAUUSD_i")
        self.assertEqual(BacktestConfig().configured_instrument_symbol, "XAUUSD_i")
        self.assertEqual(BacktestConfig().dataset_symbol_map, {})

    def test_ev_eq_01_not_proven_by_map(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2710_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["operator_policy"]["ev_eq_01"], "NOT_PROVEN")
        for row in payload["inventory"]:
            self.assertEqual(row["ev_eq_01"], "NOT_PROVEN")

    def test_data_source_fetch_does_not_use_live_resolver(self) -> None:
        cfg = BacktestConfig(symbols=["XAUUSD"], dataset_symbol_map={})
        data = BacktestMarketData(cfg, {})
        with self.assertRaises(InstrumentContractError):
            data._bind_symbol("XAUUSD")
        cfg.dataset_symbol_map = {"XAUUSD": "XAUUSD_i"}
        self.assertEqual(data._bind_symbol("XAUUSD"), "XAUUSD_i")

    def test_inject_does_not_identity_bind_xauusd(self) -> None:
        import pandas as pd

        cfg = BacktestConfig(symbols=["XAUUSD"], dataset_symbol_map={})
        data = BacktestMarketData(cfg, {})
        idx = pd.date_range("2024-01-01", periods=2, freq="5min")
        frame = pd.DataFrame(
            {"open": [1, 1], "high": [1, 1], "low": [1, 1], "close": [1, 1], "volume": [1, 1]},
            index=idx,
        )
        data.inject({"XAUUSD": frame})
        self.assertNotIn("XAUUSD", data._broker_symbols)
        self.assertEqual(data._binding_errors["XAUUSD"]["code"], "SYMBOL_MISMATCH")

    def test_invalid_sidecar_map_not_applied(self) -> None:
        cfg = BacktestConfig()
        meta = DatasetMetadata(
            dataset_symbol="XAUUSD",
            configured_instrument_symbol="XAUUSD_i",
            dataset_symbol_map={"XAUUSD": "XAUUSD"},
        )
        with self.assertRaises(InstrumentContractError):
            apply_sidecar_to_backtest_config(cfg, meta)
        self.assertEqual(cfg.dataset_symbol_map, {})

    def test_filename_inference_does_not_convert(self) -> None:
        self.assertEqual(infer_symbol_from_filename("XAUUSD_M5_30d.parquet"), "XAUUSD")
        self.assertEqual(infer_symbol_from_filename("XAUUSD_i_5m.parquet"), "XAUUSD_i")

    def test_inventory_covers_known_sets(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2710_JSON).read_text(encoding="utf-8"))
        self.assertGreaterEqual(payload["dataset_count"], 30)
        self.assertGreaterEqual(payload["logical_xauusd_count"], 1)
        self.assertFalse(payload["sidecars_rewritten"])
        self.assertTrue(payload["parquet_immutable"])
        self.assertFalse(payload["safety_confirmation"]["mt5_started"])
        self.assertFalse(payload["safety_confirmation"]["backtest_executed"])

    def test_fetch_mt5_binds_before_select(self) -> None:
        cfg = BacktestConfig(symbols=["XAUUSD"], dataset_symbol_map={})
        data = BacktestMarketData(cfg, {})
        with patch("tradingbot.backtest.data_source.ensure_legacy_path"), patch(
            "MetaTrader5.symbol_select"
        ) as select:
            with self.assertRaises(InstrumentContractError):
                data._fetch_mt5("XAUUSD", "unused.parquet")
            select.assert_not_called()

    def test_md_exists(self) -> None:
        root = Path(__file__).resolve().parents[1]
        text = (root / PHASE2710_MD).read_text(encoding="utf-8")
        self.assertIn("ONLY_WITH_EXPLICIT_DATASET_MAP", text)
        self.assertIn("NOT_PROVEN", text)
        self.assertIn("STOP after Phase 27.10", text)

    def test_no_production_mutations(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2710_JSON).read_text(encoding="utf-8"))
        safety = payload["safety_confirmation"]
        self.assertFalse(safety["strategy_modified"])
        self.assertFalse(safety["riskgate_modified"])
        self.assertFalse(safety["execution_modified"])
        self.assertFalse(safety["equivalence_fabricated"])
        self.assertEqual(payload["production_readiness"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()

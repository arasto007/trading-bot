"""Phase 27.20 — explicit dataset_symbol_map closure tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.dataset_contract import (
    InstrumentContractError,
    classify_dataset_binding,
    resolve_broker_symbol_for_dataset,
    resolve_dataset_instrument,
    validate_dataset_symbol_map,
)
from tradingbot.backtest.instrument import OFFLINE_INSTRUMENT_CATALOG
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_20_dataset_mapping_closure import (
    CANONICAL_SYMBOL,
    CAT_A,
    CAT_B,
    CAT_C,
    CAT_D,
    PHASE2720_JSON,
    PHASE2720_MD,
    classify_mapping_category,
    filename_is_not_a_mapping,
    run_phase27_20_collection,
)


def setUpModule() -> None:
    run_phase27_20_collection(Path(__file__).resolve().parents[1])


class TestPhase2720DatasetMappingClosure(unittest.TestCase):
    def test_artifact_valid(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2720_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["phase"], "27.20")
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["canonical_symbol"], "XAUUSD_i")
        self.assertTrue(payload["canonical_unchanged"])
        self.assertFalse(payload["invented_new_map_convention"])
        self.assertFalse(payload["maps_inserted"])
        self.assertEqual(payload["default_backtest_dataset_symbol_map"], {})
        self.assertEqual(payload["logical_xauusd_count"], 30)
        self.assertEqual(payload["category_counts"][CAT_B], 30)
        self.assertEqual(payload["category_counts"][CAT_C], 2)
        self.assertEqual(payload["category_counts"][CAT_A], 0)
        self.assertEqual(payload["authorization_required_count"], 30)
        self.assertEqual(len(payload["report_table"]), payload["dataset_count"])

    def test_no_implicit_mapping(self) -> None:
        with self.assertRaises(InstrumentContractError) as ctx:
            resolve_broker_symbol_for_dataset("XAUUSD", configured_symbol="XAUUSD_i")
        self.assertEqual(ctx.exception.code, "SYMBOL_MISMATCH")
        binding = classify_dataset_binding("XAUUSD", configured_symbol="XAUUSD_i")
        self.assertTrue(binding.blocked)
        self.assertIsNone(binding.mapped_broker_symbol)
        self.assertTrue(filename_is_not_a_mapping("XAUUSD_M5_180d.parquet"))
        self.assertEqual(
            classify_mapping_category(
                logical_symbol="XAUUSD",
                sidecar_map={},
                broker=None,
                server=None,
                source="UNKNOWN",
            ),
            CAT_B,
        )

    def test_explicit_map_works(self) -> None:
        broker, source = resolve_broker_symbol_for_dataset(
            "XAUUSD",
            configured_symbol="XAUUSD_i",
            dataset_symbol_map={"XAUUSD": "XAUUSD_i"},
        )
        self.assertEqual(broker, "XAUUSD_i")
        self.assertEqual(source, "explicit_map")

    def test_invalid_map_fails(self) -> None:
        with self.assertRaises(InstrumentContractError) as ctx:
            validate_dataset_symbol_map({"XAUUSD": "EURUSD"}, configured_symbol="XAUUSD_i")
        self.assertEqual(ctx.exception.code, "INVALID_MAP")
        with self.assertRaises(InstrumentContractError):
            resolve_broker_symbol_for_dataset(
                "XAUUSD",
                configured_symbol="XAUUSD_i",
                dataset_symbol_map={"XAUUSD": "XAUUSD"},
            )

    def test_unmapped_dataset_stays_blocked(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2720_JSON).read_text(encoding="utf-8"))
        for row in payload["inventory"]:
            if row["logical_symbol"] == "XAUUSD":
                self.assertEqual(row["category"], CAT_B)
                self.assertEqual(row["mapping_status"], "BLOCKED")
                self.assertTrue(row["mapping_blocked"])
                self.assertIsNone(row["proposed_mapping"])
                self.assertFalse(row["filename_used_as_map"])

    def test_canonical_xauusd_i_works_directly(self) -> None:
        broker, source = resolve_broker_symbol_for_dataset(
            "XAUUSD_i", configured_symbol="XAUUSD_i"
        )
        self.assertEqual(broker, "XAUUSD_i")
        self.assertEqual(source, "match")
        self.assertEqual(
            classify_mapping_category(
                logical_symbol="XAUUSD_i",
                sidecar_map={},
                broker=None,
                server=None,
                source=None,
            ),
            CAT_C,
        )
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2720_JSON).read_text(encoding="utf-8"))
        for name in payload["canonical_xauusd_i_datasets"]:
            self.assertIn("XAUUSD_i", name)

    def test_economics_only_after_explicit_map(self) -> None:
        with self.assertRaises(InstrumentContractError):
            resolve_dataset_instrument("XAUUSD", configured_symbol="XAUUSD_i")
        contract = resolve_dataset_instrument(
            "XAUUSD",
            configured_symbol="XAUUSD_i",
            dataset_symbol_map={"XAUUSD": "XAUUSD_i"},
        )
        self.assertEqual(contract.broker_symbol, "XAUUSD_i")
        self.assertEqual(contract.economics.symbol, "XAUUSD_i")
        self.assertNotIn("XAUUSD", OFFLINE_INSTRUMENT_CATALOG)

    def test_unknown_label_is_other(self) -> None:
        self.assertEqual(
            classify_mapping_category(
                logical_symbol="UNKNOWN",
                sidecar_map={},
                broker=None,
                server=None,
                source=None,
            ),
            CAT_D,
        )

    def test_config_default_and_no_new_convention(self) -> None:
        self.assertEqual(BacktestConfig().dataset_symbol_map, {})
        self.assertEqual(CANONICAL_SYMBOL, "XAUUSD_i")
        src = (
            Path(__file__).resolve().parents[1]
            / "tradingbot"
            / "backtest"
            / "phase27_20_dataset_mapping_closure.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("from tradingbot.adapters.symbols import resolve_broker_symbol", src)
        self.assertNotIn("symbol_select(", src)
        self.assertNotIn("order_send(", src)

    def test_safety_final_gate_and_md(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2720_JSON).read_text(encoding="utf-8"))
        p16 = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p16["FINAL_GATE"], "BLOCKED")
        self.assertEqual(payload["phase27_16_final_gate_unchanged"], "BLOCKED")
        self.assertTrue(payload["original_datasets_untouched"])
        safety = payload["safety_confirmation"]
        self.assertFalse(safety["parquet_rewritten"])
        self.assertFalse(safety["sidecars_rewritten"])
        self.assertFalse(safety["maps_silently_inserted"])
        self.assertFalse(safety["strategy_modified"])
        self.assertFalse(safety["riskgate_modified"])
        self.assertFalse(safety["execution_modified"])
        self.assertFalse(safety["canonical_symbol_changed"])
        self.assertFalse(safety["phase_27_21_started"])
        text = (root / PHASE2720_MD).read_text(encoding="utf-8")
        self.assertIn("STOP after Phase 27.20", text)
        self.assertIn("ONLY_WITH_EXPLICIT_DATASET_MAP", text)
        self.assertIn("| dataset | logical_symbol |", text)


if __name__ == "__main__":
    unittest.main()

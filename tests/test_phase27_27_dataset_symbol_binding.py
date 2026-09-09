"""Phase 27.27 — dataset provenance and explicit symbol-binding tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.dataset_contract import (
    InstrumentContractError,
    resolve_broker_symbol_for_dataset,
    validate_dataset_symbol_map,
)
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_27_dataset_symbol_binding import (
    CANONICAL_SYMBOL,
    DIRECT_CANONICAL_MATCH,
    EXPLICIT_MAPPED,
    INVALID_MAP,
    MISSING_EXPLICIT_MAP,
    PHASE2727_JSON,
    PHASE2727_MD,
    UNKNOWN_PROVENANCE,
    classify_binding_state,
    run_phase27_27_collection,
)


FORBIDDEN_SOURCE_TOKENS = (
    "symbol_select(",
    "order_send(",
    "load_dotenv",
    'Path(".env")',
)


def setUpModule() -> None:
    run_phase27_27_collection(Path(__file__).resolve().parents[1])


class TestPhase2727DatasetSymbolBinding(unittest.TestCase):
    def test_direct_xauusd_i_binding(self) -> None:
        row = classify_binding_state("XAUUSD_i")
        self.assertEqual(row["binding_state"], DIRECT_CANONICAL_MATCH)
        self.assertTrue(row["allowed"])
        self.assertEqual(row["broker_symbol"], "XAUUSD_i")
        broker, source = resolve_broker_symbol_for_dataset("XAUUSD_i", configured_symbol="XAUUSD_i")
        self.assertEqual(broker, "XAUUSD_i")
        self.assertEqual(source, "match")

    def test_xauusd_without_map_blocked(self) -> None:
        row = classify_binding_state("XAUUSD", dataset_symbol_map={})
        self.assertEqual(row["binding_state"], MISSING_EXPLICIT_MAP)
        self.assertTrue(row["blocked"])
        self.assertIsNone(row["broker_symbol"])
        with self.assertRaises(InstrumentContractError) as ctx:
            resolve_broker_symbol_for_dataset("XAUUSD", configured_symbol="XAUUSD_i")
        self.assertEqual(ctx.exception.code, "SYMBOL_MISMATCH")

    def test_xauusd_with_explicit_map_allowed(self) -> None:
        row = classify_binding_state("XAUUSD", dataset_symbol_map={"XAUUSD": "XAUUSD_i"})
        self.assertEqual(row["binding_state"], EXPLICIT_MAPPED)
        self.assertTrue(row["allowed"])
        self.assertEqual(row["broker_symbol"], "XAUUSD_i")

    def test_invalid_and_malformed_and_unavailable_maps_blocked(self) -> None:
        invalid = classify_binding_state("XAUUSD", dataset_symbol_map={"XAUUSD": "EURUSD"})
        self.assertEqual(invalid["binding_state"], INVALID_MAP)
        self.assertTrue(invalid["blocked"])
        with self.assertRaises(InstrumentContractError) as malformed:
            validate_dataset_symbol_map(["XAUUSD", "XAUUSD_i"], configured_symbol="XAUUSD_i")  # type: ignore[arg-type]
        self.assertEqual(malformed.exception.code, "INVALID_MAP")
        with self.assertRaises(InstrumentContractError) as nested:
            validate_dataset_symbol_map({"XAUUSD": {"to": "XAUUSD_i"}}, configured_symbol="XAUUSD_i")  # type: ignore[dict-item]
        self.assertEqual(nested.exception.code, "INVALID_MAP")
        with self.assertRaises(InstrumentContractError) as unavailable:
            validate_dataset_symbol_map(
                {"XAUUSD": "XAUUSD_i"},
                configured_symbol="XAUUSD_i",
                available_broker_symbols=frozenset({"EURUSD"}),
            )
        self.assertEqual(unavailable.exception.code, "INVALID_MAP")
        with self.assertRaises(InstrumentContractError) as missing_target:
            validate_dataset_symbol_map({"XAUUSD": "MISSING_GOLD"}, configured_symbol="XAUUSD_i")
        self.assertEqual(missing_target.exception.code, "INVALID_MAP")

    def test_resolver_cannot_silently_alias(self) -> None:
        root = Path(__file__).resolve().parents[1]
        src = (root / "tradingbot" / "backtest" / "dataset_contract.py").read_text(encoding="utf-8")
        for token in FORBIDDEN_SOURCE_TOKENS:
            self.assertNotIn(token, src)
        payload = json.loads((root / PHASE2727_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["resolver_audit"]["silent_xauusd_to_xauusd_i_possible"])
        self.assertTrue(payload["resolver_audit"]["missing_mappings_fail_closed"])
        self.assertEqual(payload["resolver_audit"]["live_helper_used_as_dataset_bind"], [])
        self.assertNotIn(
            "from tradingbot.adapters.symbols import resolve_broker_symbol",
            (root / "tradingbot" / "backtest" / "data_source.py").read_text(encoding="utf-8"),
        )

    def test_sidecar_and_fingerprint_immutability(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2727_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["canonical_parquet_changed"])
        self.assertTrue(payload["fingerprints_preserved"])
        self.assertTrue(payload["original_datasets_untouched"])
        self.assertFalse(payload["sidecars_rewritten"])
        self.assertFalse(payload["maps_inserted"])
        self.assertEqual(payload["canonical_fingerprints_before"], payload["canonical_fingerprints_after"])
        for row in payload["inventory"]:
            self.assertFalse(row["sidecar_rewritten"])
            self.assertFalse(row["parquet_rewritten"])
            self.assertFalse(row["filename_used_as_map"])
            if row["sidecar_present"]:
                self.assertIsNotNone(row["sidecar_symbol"])
                self.assertFalse(row["sidecar_rewritten"])

    def test_ev_eq_01_and_gate_remain_blocked(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2727_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["ev_eq_01"], "NOT_PROVEN")
        self.assertEqual(payload["dataset_binding_policy"], "ONLY_WITH_EXPLICIT_DATASET_MAP")
        self.assertEqual(payload["canonical_symbol"], CANONICAL_SYMBOL)
        self.assertEqual(BacktestConfig().dataset_symbol_map, {})
        self.assertFalse(payload["complete_costs_required_weakened"])
        p16 = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p16["FINAL_GATE"], "BLOCKED")
        self.assertEqual(payload["phase27_16_final_gate_unchanged"], "BLOCKED")
        unknown = classify_binding_state("UNKNOWN")
        self.assertEqual(unknown["binding_state"], UNKNOWN_PROVENANCE)
        text = (root / PHASE2727_MD).read_text(encoding="utf-8")
        self.assertIn("STOP after Phase 27.27", text)
        self.assertIn("| Dataset | Logical Symbol | Broker Symbol | Binding State |", text)

"""Phase 43 — broker cost / executable readiness tests (no Phase 40 rescan)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase43_broker_cost_execution_validation import (
    FROZEN_PHASE40,
    PHASE,
    PHASE43_GATES_MD,
    PHASE43_JSON,
    PHASE43_MD,
    PHASE43_READY_MD,
    REQUIRED_ARTIFACT_KEYS,
    detect_product_tokens,
    run_phase43_collection,
)

FORBIDDEN_ARTIFACT_KEYS = ("password", "mt5_password", "token", "api_key", "investor")
FORBIDDEN_SOURCE_TOKENS = (
    "symbol_select(",
    "order_send(",
    "load_dotenv",
    'Path(".env")',
    "get_mt5_credentials",
    "from tradingbot.config.live",
    "launch_terminal(",
    "run_phase40_collection(",
    "run_phase42_collection(",
)


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    artifact = root / PHASE43_JSON
    if artifact.is_file():
        payload = json.loads(artifact.read_text(encoding="utf-8"))
        if (
            payload.get("phase") == PHASE
            and payload.get("phase40_scan_rerun") is False
            and payload.get("FINAL_GATE") == "BLOCKED"
            and (root / PHASE43_MD).is_file()
            and (root / PHASE43_GATES_MD).is_file()
            and (root / PHASE43_READY_MD).is_file()
        ):
            return
    run_phase43_collection(root)


class TestPhase43BrokerCostExecutionValidation(unittest.TestCase):
    def test_frozen_baseline_and_blockers(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE43_JSON).read_text(encoding="utf-8"))
        frozen = payload["frozen_phase40"]
        self.assertEqual(frozen["signals"], FROZEN_PHASE40["signals"])
        self.assertEqual(frozen["expectancy_R"], FROZEN_PHASE40["expectancy_R"])
        self.assertEqual(frozen["events"], FROZEN_PHASE40["events"])
        self.assertFalse(payload["phase40_scan_rerun"])
        self.assertFalse(payload["phase40_baseline_verified"]["values_overwritten"])
        self.assertEqual(payload["account_product"]["ACCOUNT_PRODUCT_STATUS"], "UNKNOWN")
        self.assertEqual(payload["commission"]["status"], "UNKNOWN")
        self.assertFalse(payload["commission"]["verified_schedule"])
        self.assertEqual(payload["request_fill"]["pairs"], 0)
        self.assertEqual(payload["symbol"]["SYMBOL_MAPPING"], "NOT_PROVEN")
        self.assertEqual(payload["ev_eq_01"]["status"], "NOT_PROVEN")
        self.assertEqual(payload["cost_gates"]["PASS_COUNT"], 0)
        self.assertFalse(payload["executable_contract"]["EXECUTABLE_READY"])
        self.assertFalse(payload["executable_contract"]["executable_evaluation_run"])
        self.assertTrue(payload["executable_contract"]["unknown_not_converted_to_zero"])
        self.assertEqual(payload["verdict"]["EXECUTABLE_RESULT"], "BLOCKED")
        self.assertEqual(payload["verdict"]["OVERALL_VERDICT"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(payload["verdict"]["profitability_verdict"], "NOT_ISSUED")
        self.assertEqual(payload["FINAL_GATE"], "BLOCKED")
        self.assertFalse(payload["phase_44_started"])
        self.assertEqual(payload["cost_margin"]["COST_MARGIN"], "INSUFFICIENT / UNKNOWN")
        self.assertFalse(payload["cost_margin"]["survives_costs_claimed"])
        self.assertTrue(payload["horizon_reconciliation"]["do_not_treat_as_contradiction"])
        self.assertFalse(payload["horizon_reconciliation"]["tiny_positive_full_horizon_robust"])
        self.assertTrue(payload["dependence"]["do_not_treat_signals_as_iid"])

    def test_product_detector_does_not_infer_from_broker(self) -> None:
        out = detect_product_tokens({"company": "LiteFinance Global LLC", "server": "LiteFinance-MT5-Live"})
        self.assertEqual(out["account_product_type"], "UNKNOWN")
        self.assertFalse(out["inferred_from_broker_name"])
        hit = detect_product_tokens({"account_comment": "ECN RAW USD"})
        self.assertEqual(hit["account_product_type"], "ECN")

    def test_safety(self) -> None:
        root = Path(__file__).resolve().parents[1]
        raw = (root / PHASE43_JSON).read_text(encoding="utf-8")
        payload = json.loads(raw)
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        self.assertFalse(payload["env_accessed"])
        self.assertEqual(payload["production_safety"]["TRADING"], "NOT_PERFORMED")
        self.assertEqual(payload["production_safety"]["ORDERS"], 0)
        self.assertEqual(payload["production_safety"]["ENV"], "NOT_READ")
        self.assertEqual(payload["production_safety"]["PHASE40_RESCAN"], "NO")
        self.assertFalse(payload["production_safety"]["MT5_LAUNCHED"])
        for secret in FORBIDDEN_ARTIFACT_KEYS:
            self.assertNotRegex(raw.lower(), rf'"{secret}"\s*:')
        src = (root / "tradingbot/backtest/phase43_broker_cost_execution_validation.py").read_text(encoding="utf-8")
        for token in FORBIDDEN_SOURCE_TOKENS:
            self.assertNotIn(token, src)
        md = (root / PHASE43_MD).read_text(encoding="utf-8")
        self.assertIn("STOP AFTER PHASE 43", md)
        self.assertIn("DO NOT START PHASE 44", md)
        ready = (root / PHASE43_READY_MD).read_text(encoding="utf-8")
        self.assertIn("EXECUTABLE_READY", ready)
        self.assertIn("not converted to zero", ready)


if __name__ == "__main__":
    unittest.main()

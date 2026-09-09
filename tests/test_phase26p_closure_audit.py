"""Phase 26P — Closure audit tests (static/consolidation only)."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from tradingbot.adapters.risk_gate import detect_account_tier
from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.phase26p_closure_audit import (
    ALLOWED_TRUTH_STATUSES,
    MANDATORY_TRUTH_AREAS,
    PHASE26_CLOSURE_MD,
    PHASE26P_JSON,
    run_phase26p_collection,
)

FORBIDDEN_UPGRADES = (
    "mathematically proved zero trades",
    "A-level proven",
    "formally proven end-to-end",
    "production approved",
    "ready for real money",
    "EV-EQ-01 PROVEN",
)


def setUpModule() -> None:
    run_phase26p_collection(Path(__file__).resolve().parents[1])


class TestPhase26PClosure(unittest.TestCase):
    def test_artifact_exists_and_valid_json(self) -> None:
        root = Path(__file__).resolve().parents[1]
        path = root / PHASE26P_JSON
        self.assertTrue(path.is_file())
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["phase"], "26P")
        self.assertIn("phase_matrix", payload)
        self.assertIn("truth_matrix", payload)

    def test_closure_markdown_exists(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.assertTrue((root / PHASE26_CLOSURE_MD).is_file())

    def test_all_28_truth_areas_present(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE26P_JSON).read_text(encoding="utf-8"))
        areas = {row["area"] for row in payload["truth_matrix"]}
        self.assertEqual(areas, set(MANDATORY_TRUTH_AREAS))

    def test_truth_statuses_allowed(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE26P_JSON).read_text(encoding="utf-8"))
        for row in payload["truth_matrix"]:
            self.assertIn(row["status"], ALLOWED_TRUTH_STATUSES, msg=row["area"])

    def test_ev_eq_01_remains_not_proven(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE26P_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["broker_cost"]["ev_eq_01"], "NOT_PROVEN")
        ev_row = next(r for r in payload["truth_matrix"] if r["area"] == "EV-EQ-01")
        self.assertIn(ev_row["status"], {"BLOCKED", "UNKNOWN"})

    def test_zero_trade_not_upgraded_to_full_proof(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE26P_JSON).read_text(encoding="utf-8"))
        zt = payload["zero_trade"]
        self.assertIn("B", zt["evidence_level"])
        self.assertEqual(zt["full_engine_walk"], "DEFERRED — 26K not executed (~45 min)")
        blob = json.dumps(payload).lower()
        for phrase in FORBIDDEN_UPGRADES:
            self.assertNotIn(phrase.lower(), blob, msg=phrase)

    def test_equity_1000_is_small_and_backtest_defaults(self) -> None:
        self.assertEqual(detect_account_tier(1000.0).value, "SMALL")
        self.assertEqual(BacktestConfig().risk_per_trade, 0.005)
        self.assertEqual(BacktestConfig().timeframe, "M5")
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE26P_JSON).read_text(encoding="utf-8"))
        snap = payload["code_truth_snapshot"]
        self.assertEqual(snap["equity_1000_tier"], "SMALL")
        self.assertEqual(snap["BacktestConfig.risk_per_trade"], 0.005)
        self.assertEqual(snap["BacktestConfig.timeframe"], "M5")

    def test_no_production_or_config_changes(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE26P_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["production_behavior_changed"])
        self.assertFalse(payload["safety"]["PRODUCTION_CODE_CHANGED"])
        self.assertFalse(payload["safety"]["CONFIGURATION_CHANGED"])

    def test_no_mt5_backtest_engine_execution(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE26P_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["safety"]["MT5_CONNECTED"])
        self.assertFalse(payload["safety"]["BACKTEST_EXECUTED"])
        self.assertFalse(payload["safety"]["FULL_ENGINE_EXECUTED"])
        self.assertFalse(payload["safety"]["ENV_ACCESSED"])
        self.assertFalse(payload["safety"]["CREDENTIALS_ACCESSED"])

    def test_superseded_distinguishable(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE26P_JSON).read_text(encoding="utf-8"))
        self.assertTrue(payload["superseded"])
        md = (root / PHASE26_CLOSURE_MD).read_text(encoding="utf-8")
        self.assertIn("DEFERRED", md)
        self.assertIn("NOT_PROVEN", md)

    def test_production_readiness_not_approved(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE26P_JSON).read_text(encoding="utf-8"))
        pr = payload["production_readiness"]
        self.assertEqual(pr["status"], "BLOCKED")
        self.assertFalse(pr["phase26_authorizes_production"])
        md = (root / PHASE26_CLOSURE_MD).read_text(encoding="utf-8")
        self.assertRegex(md, r"BLOCKED", msg="closure doc must not approve production")

    def test_phase_matrix_covers_26a_through_26o(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE26P_JSON).read_text(encoding="utf-8"))
        phases = {row["phase"] for row in payload["phase_matrix"]}
        expected = {f"26{x}" for x in "ABCDEFGHIJKLMNO"}
        self.assertEqual(phases, expected)

    def test_closure_md_contains_truth_matrix_table(self) -> None:
        root = Path(__file__).resolve().parents[1]
        md = (root / PHASE26_CLOSURE_MD).read_text(encoding="utf-8")
        for area in ("EV-EQ-01", "ZERO-TRADE ATTRIBUTION", "PRODUCTION READINESS"):
            self.assertIn(area, md)


if __name__ == "__main__":
    unittest.main()

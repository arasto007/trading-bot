"""Phase 26N — Documentation contradiction cleanup tests (static/doc-only)."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from tradingbot.adapters.risk_gate import detect_account_tier
from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.phase26n_documentation_contradiction_cleanup import (
    CANONICAL_DOC_PATHS,
    PHASE26N_JSON,
    STALE_RISK_PATTERN,
    STALE_TF_PATTERN,
    SUPERSEDED_MARKER,
    run_phase26n_collection,
)

PRODUCTION_PATH_PREFIXES = (
    "tradingbot/adapters/risk_gate.py",
    "tradingbot/adapters/mt5_execution.py",
    "tradingbot/domain/broker_economics.py",
    "tradingbot/backtest/config.py",
    "tradingbot/backtest/engine.py",
)


def setUpModule() -> None:
    run_phase26n_collection(Path(__file__).resolve().parents[1])


class TestPhase26NArtifact(unittest.TestCase):
    def test_artifact_exists_and_valid_json(self) -> None:
        root = Path(__file__).resolve().parents[1]
        path = root / PHASE26N_JSON
        self.assertTrue(path.is_file())
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["phase"], "26N")
        self.assertIn("risk_per_trade", payload)
        self.assertIn("backtest_timeframe", payload)

    def test_code_risk_per_trade_is_0_005(self) -> None:
        self.assertEqual(BacktestConfig().risk_per_trade, 0.005)

    def test_code_timeframe_is_m5(self) -> None:
        self.assertEqual(BacktestConfig().timeframe, "M5")

    def test_configuration_truth_documents_current_values(self) -> None:
        root = Path(__file__).resolve().parents[1]
        text = (root / "docs_v2/01_truth/CONFIGURATION_TRUTH.md").read_text(encoding="utf-8")
        self.assertIn("BacktestConfig.risk_per_trade", text)
        self.assertIn("0.005", text)
        self.assertIn("BacktestConfig.timeframe", text)
        self.assertIn("M5", text)

    def test_no_stale_current_state_risk_claims_in_canonical_docs(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for rel in CANONICAL_DOC_PATHS:
            path = root / rel
            if not path.is_file():
                continue
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if STALE_RISK_PATTERN.search(line) and not SUPERSEDED_MARKER.search(line):
                    self.fail(f"stale risk claim {rel}:{i}: {line[:120]}")

    def test_no_stale_current_state_m1_claims_in_canonical_docs(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for rel in CANONICAL_DOC_PATHS:
            path = root / rel
            if not path.is_file():
                continue
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if STALE_TF_PATTERN.search(line) and not SUPERSEDED_MARKER.search(line):
                    self.fail(f"stale TF claim {rel}:{i}: {line[:120]}")

    def test_equity_1000_is_small_not_micro(self) -> None:
        self.assertEqual(detect_account_tier(1000.0).value, "SMALL")
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE26N_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["account_tier_terminology"]["equity_1000_tier"], "SMALL")

    def test_historical_audit_preserved(self) -> None:
        root = Path(__file__).resolve().parents[1]
        prod = (root / "docs_v2/01_truth/PRODUCTION_READINESS_AUDIT.md").read_text(encoding="utf-8")
        self.assertIn("Superseded", prod)
        self.assertIn("was M1", prod)
        self.assertIn("0.01", prod)  # historical pre-25B claim preserved in superseded block

    def test_remaining_contradictions_recorded_not_hidden(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE26N_JSON).read_text(encoding="utf-8"))
        self.assertIn("contradictions_remaining", payload)
        self.assertIn("unknowns", payload)
        self.assertIsInstance(payload["contradictions_remaining"], list)

    def test_no_production_behavior_change(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE26N_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["production_behavior_changed"])
        self.assertFalse(payload["safety"]["PRODUCTION_CODE_CHANGED"])
        self.assertFalse(payload["safety"]["CONFIGURATION_CHANGED"])
        self.assertFalse(payload["safety"]["BACKTEST_EXECUTED"])


if __name__ == "__main__":
    unittest.main()

"""Phase 26O — Legacy docs/ truth sweep tests (static/doc-only)."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from tradingbot.adapters.risk_gate import detect_account_tier
from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.phase26o_legacy_docs_truth_sweep import (
    CORRECTIONS_APPLIED,
    HISTORICAL_MARKER,
    PHASE26O_JSON,
    STALE_M1_DEFAULT,
    STALE_RISK_01,
    run_phase26o_collection,
)

ALLOWED_CHANGED_PREFIX = "docs/"


def setUpModule() -> None:
    run_phase26o_collection(Path(__file__).resolve().parents[1])


class TestPhase26OArtifact(unittest.TestCase):
    def test_artifact_exists_and_valid_json(self) -> None:
        root = Path(__file__).resolve().parents[1]
        path = root / PHASE26O_JSON
        self.assertTrue(path.is_file())
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["phase"], "26O")
        self.assertEqual(payload["scope"], "docs/")

    def test_no_current_state_1pct_backtest_risk_in_legacy_docs(self) -> None:
        root = Path(__file__).resolve().parents[1]
        docs = root / "docs"
        for path in docs.rglob("*.md"):
            rel = path.relative_to(root).as_posix()
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if STALE_RISK_01.search(line) and not HISTORICAL_MARKER.search(line):
                    if "VOL_REGIME_MAX_LOT" in line:
                        continue
                    self.fail(f"stale 1% risk claim {rel}:{i}: {line[:120]}")

    def test_no_current_state_m1_backtest_default_in_legacy_docs(self) -> None:
        root = Path(__file__).resolve().parents[1]
        docs = root / "docs"
        for path in docs.rglob("*.md"):
            rel = path.relative_to(root).as_posix()
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if STALE_M1_DEFAULT.search(line) and not HISTORICAL_MARKER.search(line):
                    self.fail(f"stale M1 default claim {rel}:{i}: {line[:120]}")

    def test_backtest_config_defaults_documented_in_phase3(self) -> None:
        root = Path(__file__).resolve().parents[1]
        text = (root / "docs/PHASE3_BACKTEST_FA.md").read_text(encoding="utf-8")
        self.assertIn("0.005", text)
        self.assertIn("M5", text)
        self.assertEqual(BacktestConfig().risk_per_trade, 0.005)
        self.assertEqual(BacktestConfig().timeframe, "M5")

    def test_historical_m1_preserved(self) -> None:
        root = Path(__file__).resolve().parents[1]
        text = (root / "docs/phase8_data_collection.md").read_text(encoding="utf-8")
        self.assertIn("M1", text)
        self.assertIn("historical", text.lower())

    def test_equity_1000_not_micro(self) -> None:
        self.assertEqual(detect_account_tier(1000.0).value, "SMALL")
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE26O_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["code_truth"]["equity_1000_tier"], "SMALL")

    def test_no_proven_xauusd_equivalence_claims(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE26O_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["symbol_claims"]["equivalence_claims"], [])

    def test_no_production_or_config_changes(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE26O_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["production_behavior_changed"])
        self.assertFalse(payload["safety"]["PRODUCTION_CODE_CHANGED"])
        self.assertFalse(payload["safety"]["CONFIGURATION_CHANGED"])

    def test_ambiguous_recorded_not_hidden(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE26O_JSON).read_text(encoding="utf-8"))
        self.assertIn("unknowns", payload)
        self.assertIn("ambiguous_claims", payload["risk_01_references"])
        self.assertIn("remaining_contradictions", payload)

    def test_only_intended_legacy_docs_changed(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE26O_JSON).read_text(encoding="utf-8"))
        changed = payload["documentation_files_changed"]
        self.assertEqual(set(changed), set(CORRECTIONS_APPLIED.keys()))
        for path in changed:
            self.assertTrue(path.startswith(ALLOWED_CHANGED_PREFIX), msg=path)
        self.assertFalse(any(p.startswith("docs_v2/") for p in changed))


if __name__ == "__main__":
    unittest.main()

"""Phase 61 edge-survival forensics tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase61_edge_survival_forensics import (
    PHASE,
    PHASE40_JSON,
    PHASE61_JSON,
    PHASE61_MD,
    REQUIRED_ARTIFACT_KEYS,
    contribution_analysis,
    run_phase61_collection,
    score_edge_quality,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    art = root / PHASE61_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("phase40_scan_rerun") is False:
            return
    run_phase61_collection(root)


class TestPhase61(unittest.TestCase):
    def test_events_match_frozen_expectancy_and_no_invention(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE61_JSON).read_text(encoding="utf-8"))
        ev = payload["events"]
        self.assertEqual(ev["signal_count"], 2847)
        self.assertEqual(ev["event_count_including_open_only"], 420)
        self.assertEqual(ev["event_count_resolved"], 419)
        self.assertAlmostEqual(ev["performance"]["expectancy_R"], 0.04866, places=4)
        self.assertEqual(ev["construction"]["jsonl_asian_range"], "NOT_PERSISTED")
        self.assertFalse(ev["construction"]["strategy_logic_rerun"])
        self.assertIn("asian_high", ev["fields_unknown"])
        conc = payload["contribution"]["classification"]
        self.assertIn(conc, {"LOW_CONCENTRATION", "MODERATE_CONCENTRATION", "HIGH_CONCENTRATION", "EXTREME_CONCENTRATION"})
        self.assertEqual(payload["fold_cost_survival"]["contradiction_resolution"], "NOT_RESOLVED")
        self.assertIn("OOS_vs_RECENT_CONTRADICTION", payload["fold_cost_survival"])
        self.assertEqual(payload["profitability_verdict"], "NOT_ISSUED")
        self.assertIn("MODELED", payload["modeled_cost_uncertainty"]["label"])
        self.assertEqual(payload["bootstrap"]["seed"], 400040)
        self.assertFalse(payload["bootstrap"]["vs_phase40"]["silent_replacement"])
        self.assertEqual(payload["session"]["SESSION_DEPENDENCY"], "HIGH")
        self.assertFalse(payload["regime"]["models_refit"])

    def test_quality_rules_and_safety(self) -> None:
        quality = score_edge_quality(
            gross_e=0.04866,
            time_clf="UNSTABLE",
            regime_dep="HIGH",
            session_dep="HIGH",
            conc="EXTREME_CONCENTRATION",
            rare_cat=False,
            oos_e=0.4,
            recent_e=-0.4,
            boot_p5=-0.13,
            be=0.04866,
            modeled_base_e=-0.05,
        )
        self.assertEqual(quality["EDGE_QUALITY"], "FRAGILE")
        rows = [{"r_result": r} for r in (5.0, 2.0, 1.0, -1.0, -1.0)]
        conc = contribution_analysis(rows)
        self.assertIn("CONCENTRATION", conc["classification"])
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE61_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        self.assertFalse(payload["env_accessed"])
        self.assertFalse(payload["mt5_launched"])
        self.assertFalse(payload["phase40_scan_rerun"])
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase61_edge_survival_forensics.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("EDGE_QUALITY", (root / PHASE61_MD).read_text(encoding="utf-8"))
        self.assertIn(payload["DECISION_ECONOMICS"], {
            "YES_HIGH_VALUE",
            "YES_BUT_ONLY_AFTER_OPERATOR_EVIDENCE",
            "LOW_VALUE",
            "NO_VALUE_CURRENTLY",
            "UNKNOWN",
        })


if __name__ == "__main__":
    unittest.main()

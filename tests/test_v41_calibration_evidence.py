"""Phase 1.5.31–1.5.35 — v41 calibration evidence stays offline and untransferred."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TestV41CalibrationEvidenceIsolation(unittest.TestCase):
    def test_v40_calibration_constants_unchanged(self) -> None:
        from tradingbot.ml.confidence_engine.calibration_policy import (
            TREND_RF_MONTE_CARLO,
            TREND_RF_VALIDATED_PF,
            TREND_RF_WF_ROBUSTNESS,
        )
        from tradingbot.ml.confidence_engine.engine_calibrator import (
            TREND_MODEL_ID,
            engine_calibration_factor,
        )
        from tradingbot.ml.risk_intelligence.risk_types import HistoricalMetrics

        self.assertEqual(TREND_MODEL_ID, "trend_rf_v40")
        self.assertEqual(TREND_RF_VALIDATED_PF, 1.21)
        self.assertEqual(TREND_RF_WF_ROBUSTNESS, 0.83)
        self.assertEqual(TREND_RF_MONTE_CARLO, 1.0)

        v41_factor, v41_label = engine_calibration_factor(
            engine="trend_rf_v41", regime="TREND", regime_strength=0.9
        )
        self.assertEqual(v41_factor, 1.0)
        self.assertIn("neutral", v41_label)

        v40_factor, _ = engine_calibration_factor(
            engine="trend_rf_v40", regime="TREND", regime_strength=0.9
        )
        self.assertGreater(v40_factor, 1.0)

        history = HistoricalMetrics()
        self.assertEqual(history.engine_quality_factor("trend_rf_v41"), 1.0)
        v40_quality = history.engine_quality_factor("trend_rf_v40")
        self.assertNotEqual(v40_quality, 1.0)
        self.assertAlmostEqual(v40_quality, 0.922625, places=6)

    def test_evidence_document_classifies_insufficient(self) -> None:
        path = ROOT / "docs_v2" / "07_ml" / "V41_CALIBRATION_EVIDENCE.md"
        self.assertTrue(path.is_file())
        text = path.read_text(encoding="utf-8")
        self.assertIn("C — insufficient evidence", text)
        self.assertIn("No v40 calibration factors were transferred", text)
        self.assertIn("V41_WALK_FORWARD_EVIDENCE (trading metrics) = MISSING", text)
        self.assertIn("V41_ISOLATED_MONTE_CARLO = MISSING", text)

    def test_v41_bundle_metadata_is_readable(self) -> None:
        from tradingbot.ml.phase15a.config import trend_rf_bundle_root

        root = trend_rf_bundle_root(version="v41")
        if not root.is_dir():
            self.skipTest("trend_rf_bundle_v41 not present on this machine")
        meta = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(meta.get("engine_id"), "trend_rf_v41")
        self.assertEqual(meta.get("train_rows"), 796)
        self.assertNotEqual(meta.get("train_rows"), 672614)


if __name__ == "__main__":
    unittest.main()

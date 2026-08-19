"""Tests for Phase 9.9 runtime feature validation helpers."""

from __future__ import annotations

import unittest

from tradingbot.ml.research.regime_router.phase99_feature_validation import (
    hold_result_with_diagnostics,
    ordered_feature_vector,
    validate_runtime_feature_vector,
)


class TestPhase99FeatureValidation(unittest.TestCase):
    def test_validate_rejects_missing_feature(self):
        ok, errors = validate_runtime_feature_vector({"a": 1.0}, ["a", "b"])
        self.assertFalse(ok)
        self.assertIn("missing:b", errors)

    def test_validate_accepts_ordered_vector(self):
        feats = {"a": 1.0, "b": -1.0}
        ok, errors = validate_runtime_feature_vector(feats, ["a", "b"])
        self.assertTrue(ok)
        self.assertEqual(errors, [])

    def test_hold_result_includes_diagnostics(self):
        result = hold_result_with_diagnostics(errors=["missing:x"], feature_source="feature_builder", model_version="test")
        self.assertTrue(result["feature_validation_failed"])
        self.assertFalse(result["predict_proba_called"])

    def test_ordered_feature_vector(self):
        ordered = ordered_feature_vector({"b": 2.0, "a": 1.0}, ["a", "b"])
        self.assertEqual(list(ordered.keys()), ["a", "b"])


if __name__ == "__main__":
    unittest.main()

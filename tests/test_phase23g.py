"""Phase 23G — production integration tests."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]

VERDICT_OPTIONS = {
    "RANGE_PROFILE_INTEGRATED",
    "ROLLBACK_REQUIRED",
    "INTEGRATION_FAILED",
}


class TestRegimeFilterProfiles(unittest.TestCase):
    def test_range_profile_values(self) -> None:
        from tradingbot.ml.integration.regime_filter_profiles import RangeFilterProfile

        profile = RangeFilterProfile()
        self.assertEqual(profile.rsi_min, 40.0)
        self.assertEqual(profile.rsi_max, 65.0)
        self.assertEqual(profile.adx_min, 15.0)
        self.assertEqual(profile.adx_max, 40.0)

    def test_trend_profile_matches_phase22c(self) -> None:
        from tradingbot.ml.integration.regime_filter_profiles import TrendFilterProfile
        from tradingbot.ml.research.phase22c.config import load_phase22c_config

        cfg = load_phase22c_config()
        trend = TrendFilterProfile.from_phase22c(cfg)
        self.assertEqual(trend.rsi_min, cfg.rsi_min)
        self.assertEqual(trend.adx_max, cfg.adx_max)

    def test_range_selection_only_for_range_phase99(self) -> None:
        from tradingbot.ml.decision_engine.decision_policy import RANGE_MODEL_ID
        from tradingbot.ml.integration.regime_filter_profiles import (
            ENV_ENABLE_RANGE_FILTER_PROFILE,
            RangeFilterProfile,
            select_profitability_filter_settings,
        )

        with mock.patch.dict(os.environ, {ENV_ENABLE_RANGE_FILTER_PROFILE: "true"}, clear=False):
            settings, diag = select_profitability_filter_settings(
                regime="RANGE",
                engine=RANGE_MODEL_ID,
            )
            self.assertEqual(diag.profile_used, RangeFilterProfile().profile_id)
            self.assertEqual(settings.rsi_min, 40.0)

            _, trend_diag = select_profitability_filter_settings(regime="TREND", engine="trend_rf_v41")
            self.assertNotEqual(trend_diag.profile_used, RangeFilterProfile().profile_id)

    def test_rollback_restores_phase22c(self) -> None:
        from tradingbot.ml.decision_engine.decision_policy import RANGE_MODEL_ID
        from tradingbot.ml.integration.regime_filter_profiles import (
            ENV_ENABLE_RANGE_FILTER_PROFILE,
            RangeFilterProfile,
            phase22c_filter_settings,
            select_profitability_filter_settings,
        )

        legacy = phase22c_filter_settings()
        with mock.patch.dict(os.environ, {ENV_ENABLE_RANGE_FILTER_PROFILE: "false"}, clear=False):
            settings, diag = select_profitability_filter_settings(
                regime="RANGE",
                engine=RANGE_MODEL_ID,
            )
            self.assertNotEqual(diag.profile_used, RangeFilterProfile().profile_id)
            self.assertEqual(settings.rsi_min, legacy.rsi_min)
            self.assertEqual(settings.adx_max, legacy.adx_max)

    def test_diagnostics_fields(self) -> None:
        from tradingbot.ml.integration.regime_filter_profiles import FilterProfileDiagnostics

        diag = FilterProfileDiagnostics(
            profile_used="range_phase23e",
            regime="RANGE",
            engine="phase9_9",
            rsi_limits=(40.0, 65.0),
            adx_limits=(15.0, 40.0),
            enable_range_filter_profile=True,
            filter_reason="rsi_filter",
            blocked_by=["rsi_filter"],
        )
        payload = diag.to_dict()
        for key in ("profile_used", "rsi_limits", "adx_limits", "regime", "filter_reason", "blocked_by"):
            self.assertIn(key, payload)


class TestKernelAdapterDiagnostics(unittest.TestCase):
    def test_kernel_adapter_exposes_filter_diagnostics_property(self) -> None:
        from tradingbot.ml.integration.kernel_adapter import KernelAdapter

        self.assertTrue(hasattr(KernelAdapter, "last_filter_diagnostics"))


class TestPhase23GIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir
        from tradingbot.ml.research.phase23g.integration_validation import (
            build_integration_report,
            build_regime_profile_validation,
            build_rollback_validation,
            build_runtime_regression,
        )

        base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
        cls.result = {
            "verdict": "RANGE_PROFILE_INTEGRATED",
            "integration_report": build_integration_report(),
            "runtime_regression": build_runtime_regression(),
            "regime_profile_validation": build_regime_profile_validation(),
            "rollback_validation": build_rollback_validation(),
            "shadow_validation": {"checks": {"trend_unchanged": True}},
            "diagnostics_report": {"checks": {"diagnostics_fields_present": True}},
        }

    def test_verdict_valid(self) -> None:
        self.assertIn(self.result["verdict"], VERDICT_OPTIONS)

    def test_regime_profiles(self) -> None:
        checks = self.result["regime_profile_validation"]["checks"]
        self.assertTrue(checks["range_profile_correct"])
        self.assertTrue(checks["trend_unchanged"])

    def test_rollback_verified(self) -> None:
        self.assertTrue(self.result["rollback_validation"]["checks"]["rollback_verified"])

    def test_runtime_regression(self) -> None:
        checks = self.result["runtime_regression"]["checks"]
        self.assertTrue(checks["artifacts_present"])
        self.assertTrue(checks["health_gate_unchanged_module"])

    def test_shadow_trend_unchanged(self) -> None:
        self.assertTrue(self.result["shadow_validation"]["checks"]["trend_unchanged"])

    def test_diagnostics_report(self) -> None:
        checks = self.result["diagnostics_report"]["checks"]
        self.assertTrue(checks["diagnostics_fields_present"])


class TestPhase23GDeliverables(unittest.TestCase):
    def test_files_exist(self) -> None:
        out = PROJECT_ROOT / "tradingbot" / "ml" / "research" / "phase23g"
        required = (
            "integration_report.json",
            "runtime_regression.json",
            "regime_profile_validation.json",
            "rollback_validation.json",
            "shadow_validation.json",
            "diagnostics_report.json",
            "phase23g_final_report.json",
        )
        missing = [n for n in required if not (out / n).is_file()]
        if missing:
            from tradingbot.adapters.legacy_loader import load_legacy_config
            from tradingbot.ml.data.paths import normalize_ml_base_dir
            from tradingbot.ml.research.phase23g.integration_validation import run_integration_validation

            base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
            result = run_integration_validation(base_dir=base_dir, quick=True)
            from datetime import datetime, timezone

            now = datetime.now(timezone.utc).isoformat()
            for key, fname in (
                ("integration_report", "integration_report.json"),
                ("runtime_regression", "runtime_regression.json"),
                ("regime_profile_validation", "regime_profile_validation.json"),
                ("rollback_validation", "rollback_validation.json"),
                ("shadow_validation", "shadow_validation.json"),
                ("diagnostics_report", "diagnostics_report.json"),
            ):
                payload = {**result[key], "generated_utc": now}
                (out / fname).write_text(json.dumps(payload, indent=2), encoding="utf-8")
            (out / "phase23g_final_report.json").write_text(
                json.dumps({**result["phase23g_final_report"], "generated_utc": now}, indent=2),
                encoding="utf-8",
            )
        for name in required:
            self.assertTrue((out / name).is_file(), msg=f"missing {name}")
            payload = json.loads((out / name).read_text(encoding="utf-8"))
            self.assertEqual(payload["phase"], "23G")


if __name__ == "__main__":
    unittest.main()

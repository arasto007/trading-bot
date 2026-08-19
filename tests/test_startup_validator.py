"""Unit tests for startup validator."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tradingbot.config.legacy_settings import kernel_settings_from_legacy
from tradingbot.services.startup_validator import StartupValidationError, validate_startup


class TestStartupValidator(unittest.TestCase):
    def test_missing_use_ml_kernel_fails(self) -> None:
        settings = kernel_settings_from_legacy()
        with tempfile.TemporaryDirectory() as tmp:
            legacy = {"BASE_DIR": tmp}
            env = {k: v for k, v in os.environ.items() if k != "USE_ML_KERNEL"}
            with mock.patch.dict(os.environ, env, clear=True):
                with self.assertRaises(StartupValidationError) as ctx:
                    validate_startup(
                        settings=settings,
                        legacy_config=legacy,
                        dry_run=True,
                        skip_mt5=True,
                    )
                self.assertEqual(ctx.exception.code, "USE_ML_KERNEL_MISSING")

    def test_emergency_stop_fails(self) -> None:
        settings = kernel_settings_from_legacy()
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"USE_ML_KERNEL": "0", "TRADINGBOT_SKIP_MT5_STARTUP": "1"}, clear=True):
                with mock.patch("tradingbot.services.startup_validator.is_emergency_stop_active", return_value=True):
                    with mock.patch("tradingbot.services.startup_validator._check_filesystem", return_value={"data_dir": True, "data_writable": True, "logs_dir": True, "logs_writable": True, "sqlite_available": True}):
                        with self.assertRaises(StartupValidationError) as ctx:
                            validate_startup(
                                settings=settings,
                                legacy_config={"BASE_DIR": tmp},
                                dry_run=True,
                                skip_mt5=True,
                            )
                        self.assertEqual(ctx.exception.code, "EMERGENCY_STOP_ACTIVE")

    def test_protector_duplicate_ownership_fails(self) -> None:
        settings = kernel_settings_from_legacy()
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"USE_ML_KERNEL": "0", "TRADINGBOT_SKIP_MT5_STARTUP": "1"}, clear=True):
                with mock.patch("tradingbot.services.startup_validator._check_filesystem", return_value={"data_dir": True, "data_writable": True, "logs_dir": True, "logs_writable": True, "sqlite_available": True}):
                    with self.assertRaises(StartupValidationError) as ctx:
                        validate_startup(
                            settings=settings,
                            legacy_config={"BASE_DIR": tmp},
                            dry_run=True,
                            enable_protector=True,
                            skip_mt5=True,
                        )
                    self.assertEqual(ctx.exception.code, "DUPLICATE_POSITION_OWNERSHIP")

    def test_legacy_mode_passes_without_ml_artifacts(self) -> None:
        settings = kernel_settings_from_legacy()
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"USE_ML_KERNEL": "0", "TRADINGBOT_SKIP_MT5_STARTUP": "1"}, clear=True):
                with mock.patch("tradingbot.services.startup_validator._check_filesystem", return_value={"data_dir": True, "data_writable": True, "logs_dir": True, "logs_writable": True, "sqlite_available": True}):
                    with mock.patch("tradingbot.services.startup_validator._check_mt5", return_value=(True, None)):
                        report = validate_startup(
                            settings=settings,
                            legacy_config={"BASE_DIR": tmp},
                            dry_run=True,
                            skip_mt5=True,
                        )
                        self.assertEqual(report.execution_mode, "dry_run")
                        self.assertFalse(report.ml_kernel_enabled)


if __name__ == "__main__":
    unittest.main()

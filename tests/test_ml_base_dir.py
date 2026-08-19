"""Tests for ML base_dir normalization (legacy BASE_DIR vs data/ml layout)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class TestNormalizeMlBaseDir(unittest.TestCase):
    def test_project_root_maps_to_none(self) -> None:
        from tradingbot.adapters.legacy_loader import project_root
        from tradingbot.ml.data.paths import normalize_ml_base_dir

        self.assertIsNone(normalize_ml_base_dir(str(project_root())))

    def test_custom_tmp_dir_preserved(self) -> None:
        from tradingbot.ml.data.paths import normalize_ml_base_dir

        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(normalize_ml_base_dir(tmp), tmp)

    def test_build_strategy_registry_with_legacy_base_dir(self) -> None:
        from tradingbot.adapters.legacy_loader import load_legacy_config, project_root
        from tradingbot.ml.integration.factory import build_strategy_registry
        from tradingbot.ml.integration.ml_kernel_registry import MLKernelRegistry

        if not (project_root() / "data" / "ml" / "research" / "phase9_9_best" / "model.pkl").is_file():
            self.skipTest("phase9_9 model not on disk")

        with mock.patch.dict(os.environ, {"USE_ML_KERNEL": "true"}, clear=False):
            cfg = load_legacy_config()
            reg = build_strategy_registry(cfg, base_dir=cfg.get("BASE_DIR"))
            self.assertIsInstance(reg, MLKernelRegistry)


if __name__ == "__main__":
    unittest.main()

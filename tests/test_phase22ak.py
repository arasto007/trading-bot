"""Phase 22AK — controlled end-to-end model freeze execution tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.data.paths import (
    phase9_9_backup_root,
    phase9_9_freeze_manifest_path,
    phase9_9_metadata_path,
    phase9_9_model_path,
)
from tradingbot.ml.paper_trading.model_registry import (
    FreezeContractRequiredError,
    build_test_freeze_contract,
    freeze_phase9_9_artifacts,
    load_phase9_9_bundle,
    validate_freeze_contract,
)
from tradingbot.ml.research.phase22ak.freeze_execution import (
    EXPECTED_PRODUCTION_WINNER,
    build_backup_validation,
    build_runtime_validation,
    build_winner_resolution_report,
    validate_freeze_contract_complete,
)


class TestPhase22AKFreezeExecution(unittest.TestCase):
    def test_successful_freeze_from_existing_optimizer_state(self):
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir

        base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
        if not phase9_9_model_path(base_dir).is_file():
            self.skipTest("phase9_9 artifacts missing; run phase22ak run_investigation.py first")

        runtime = build_runtime_validation(base_dir=base_dir)
        self.assertTrue(runtime["checks"]["bundle_loaded"])
        self.assertTrue(runtime["checks"]["checksum_valid"])
        self.assertTrue(runtime["healthgate_phase9_passes"])

        metadata = json.loads(phase9_9_metadata_path(base_dir).read_text(encoding="utf-8"))
        self.assertEqual(metadata.get("freeze_authority"), "ACCEPTANCE_PASS_HIGHEST_COMPOSITE")

    def test_backup_exists_after_execution(self):
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir

        base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
        backup_root = phase9_9_backup_root(base_dir)
        valid_backups = [
            path
            for path in backup_root.iterdir()
            if path.is_dir() and (path / "model.pkl").is_file()
        ] if backup_root.is_dir() else []
        if not valid_backups:
            self.skipTest("valid backup missing; run phase22ak run_investigation.py first")

        backup_report = build_backup_validation(
            base_dir=base_dir,
            before_snapshot={"files_present": {"model.pkl": True}, "artifact_checksums": {}},
        )
        self.assertTrue(backup_report["backup_created"])
        self.assertTrue(backup_report["backup_files_present"].get("model.pkl"))

    def test_manifest_exists_after_execution(self):
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir

        base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
        manifest_path = phase9_9_freeze_manifest_path(base_dir)
        if not manifest_path.is_file():
            self.skipTest("freeze manifest missing; run phase22ak run_investigation.py first")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest.get("freeze_authority"), "ACCEPTANCE_PASS_HIGHEST_COMPOSITE")
        self.assertIn("artifact_checksums", manifest)
        self.assertIn("acceptance_snapshot", manifest)

    def test_runtime_loader_succeeds(self):
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir

        base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
        if not phase9_9_model_path(base_dir).is_file():
            self.skipTest("phase9_9 artifacts missing")

        bundle = load_phase9_9_bundle(base_dir=base_dir, build_if_missing=False)
        self.assertTrue(bundle.feature_order)
        prob = bundle.predict_proba({feature: 0.0 for feature in bundle.feature_order})
        self.assertGreaterEqual(prob, 0.0)
        self.assertLessEqual(prob, 1.0)

    def test_rejected_candidate_cannot_freeze(self):
        contract = build_test_freeze_contract()
        contract["acceptance_status"] = {"final_verdict": "FAIL", "checks": {}}
        self.assertIn("acceptance_not_pass", validate_freeze_contract(contract))
        ok, errors = validate_freeze_contract_complete(contract)
        self.assertFalse(ok)
        self.assertTrue(any("acceptance" in err for err in errors))

    def test_isolated_freeze_writes_backup_and_manifest(self):
        from tests.test_ml_paper_phase9_10 import _setup_paper

        with tempfile.TemporaryDirectory() as tmp:
            _setup_paper(tmp)
            from tradingbot.ml.dataset.store import DatasetStore

            df = DatasetStore(tmp).load_v2("XAUUSD", "M5")
            assert df is not None
            contract = build_test_freeze_contract()
            freeze_phase9_9_artifacts(df, contract=contract, base_dir=tmp)
            self.assertTrue(phase9_9_freeze_manifest_path(tmp).is_file())
            backup_root = phase9_9_backup_root(tmp)
            self.assertTrue(backup_root.is_dir())
            self.assertTrue(any(backup_root.iterdir()))
            metadata = json.loads(phase9_9_metadata_path(tmp).read_text(encoding="utf-8"))
            self.assertEqual(metadata["candidate_id"], contract["candidate_id"])

    def test_freeze_without_contract_raises(self):
        import pandas as pd

        df = pd.DataFrame({"label": [0, 1] * 30})
        with self.assertRaises(FreezeContractRequiredError):
            freeze_phase9_9_artifacts(df, contract=None)


class TestPhase22AKMigrationReport(unittest.TestCase):
    def test_verdict_model_frozen_successfully(self):
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir
        from tradingbot.ml.research.phase22ak.freeze_execution import build_winner_resolution_report

        base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
        final_path = ROOT / "tradingbot" / "ml" / "research" / "phase22ak" / "phase22ak_final_report.json"
        if not final_path.is_file():
            self.skipTest("run phase22ak run_investigation.py first")

        final = json.loads(final_path.read_text(encoding="utf-8"))
        self.assertEqual(final["verdict"], "MODEL_FROZEN_SUCCESSFULLY")
        self.assertEqual(final.get("production_winner"), EXPECTED_PRODUCTION_WINNER)

        winner = build_winner_resolution_report(base_dir=base_dir)
        self.assertTrue(winner["single_eligible_candidate"])


class TestPhase22AKDeliverables(unittest.TestCase):
    def test_deliverables_exist(self):
        out = ROOT / "tradingbot" / "ml" / "research" / "phase22ak"
        for name in (
            "optimizer_execution_report.json",
            "winner_resolution_report.json",
            "freeze_execution_report.json",
            "artifact_before_after.json",
            "runtime_validation.json",
            "backup_validation.json",
            "phase22ak_final_report.json",
        ):
            path = out / name
            if not path.is_file():
                self.skipTest("run phase22ak run_investigation.py first")
            self.assertTrue(json.loads(path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()

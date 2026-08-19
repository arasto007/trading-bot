"""Tests for Phase 24B ORB forward demo infrastructure."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TestPhase24BOrbForwardDemo(unittest.TestCase):
    def test_frozen_config_loads_and_matches_phase23b(self) -> None:
        from tradingbot.research.orb_forward_demo import (
            CANONICAL_FROZEN,
            CERT_MATRIX_PATH,
            FROZEN_ORB_PATH,
            load_frozen_orb_config,
        )

        self.assertTrue(FROZEN_ORB_PATH.is_file())
        self.assertTrue(CERT_MATRIX_PATH.is_file())
        blob = load_frozen_orb_config()
        cert = json.loads(CERT_MATRIX_PATH.read_text(encoding="utf-8"))
        self.assertEqual(cert.get("frozen_orb"), blob.get("frozen_orb_ref"))
        self.assertEqual(blob.get("parameters"), CANONICAL_FROZEN["parameters"])

    def test_load_frozen_orb_config_raises_on_tampered_config(self) -> None:
        from tradingbot.research.orb_forward_demo import FROZEN_ORB_PATH, load_frozen_orb_config

        original = FROZEN_ORB_PATH.read_text(encoding="utf-8")
        try:
            data = json.loads(original)
            data["parameters"]["atr_break"] = 0.99
            FROZEN_ORB_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
            with self.assertRaises(ValueError):
                load_frozen_orb_config()
        finally:
            FROZEN_ORB_PATH.write_text(original, encoding="utf-8", newline="\n")

    def test_cli_script_exists(self) -> None:
        path = ROOT / "scripts" / "phase24b_orb_forward_demo.py"
        self.assertTrue(path.is_file())

    def test_no_live_or_risk_gate_imports_in_module_source(self) -> None:
        path = ROOT / "tradingbot" / "research" / "orb_forward_demo.py"
        forbidden = (
            "live.py",
            "live_runner",
            "risk_gate",
            "portfolio_router",
            "trading_kernel",
            "meta_decision",
        )
        import_lines = [
            ln.strip().lower()
            for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip().startswith(("import ", "from "))
        ]
        joined = "\n".join(import_lines)
        for token in forbidden:
            self.assertNotIn(token, joined, msg=f"forbidden import {token!r} in orb_forward_demo")

    def test_rollup_insufficient_sample_when_no_trades(self) -> None:
        from tradingbot.research import orb_forward_demo as demo

        demo.ensure_dirs()
        for name in (
            demo.TRADES_LOG,
            demo.SETUPS_LOG,
            demo.RESULT_PATH,
            demo.CUMULATIVE_PATH,
            demo.BACKTEST_VS_DEMO_PATH,
        ):
            if name.exists():
                name.unlink()
        summary = demo.rollup_metrics()
        self.assertEqual(summary["performance_gate"], "INSUFFICIENT_SAMPLE")
        text = demo.RESULT_PATH.read_text(encoding="utf-8")
        self.assertIn("PERFORMANCE_GATE=INSUFFICIENT_SAMPLE", text)
        self.assertIn("FINAL_VERDICT=INSUFFICIENT_SAMPLE", text)


if __name__ == "__main__":
    unittest.main()

"""Phase 42 — broker cost / execution closure tests (no Phase 40 rescan)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase42_broker_cost_execution_closure import (
    PHASE,
    PHASE42_JSON,
    PHASE42_MATRIX_MD,
    PHASE42_MD,
    PHASE42_READY_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase42_collection,
)
from tradingbot.backtest.phase42_cost_reconstruction import overnight_candidates, reconstruct_frozen_phase40

FORBIDDEN_ARTIFACT_KEYS = ("password", "mt5_password", "token", "api_key", "investor")
FORBIDDEN_SOURCE_TOKENS = (
    "symbol_select(",
    "order_send(",
    "load_dotenv",
    'Path(".env")',
    "get_mt5_credentials",
    "from tradingbot.config.live",
    "launch_terminal(",
    "run_phase40_collection(",
)


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    artifact = root / PHASE42_JSON
    if artifact.is_file():
        payload = json.loads(artifact.read_text(encoding="utf-8"))
        if (
            payload.get("phase") == PHASE
            and payload.get("phase40_scan_rerun") is False
            and payload.get("FINAL_GATE") == "BLOCKED"
            and (root / PHASE42_MD).is_file()
            and (root / PHASE42_MATRIX_MD).is_file()
            and (root / PHASE42_READY_MD).is_file()
        ):
            return
    run_phase42_collection(root)


class TestPhase42BrokerCostExecutionClosure(unittest.TestCase):
    def test_gate_remains_blocked_no_rescan(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE42_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["phase"], "42")
        self.assertFalse(payload["phase40_scan_rerun"])
        self.assertEqual(payload["commission"]["status"], "UNKNOWN")
        self.assertFalse(payload["commission"]["verified_schedule"])
        self.assertTrue(payload["commission"]["zero_is_not_verified"])
        self.assertEqual(payload["request_fill"]["pairs"], 0)
        self.assertEqual(payload["symbol"]["SYMBOL_MAPPING"], "NOT_PROVEN")
        self.assertFalse(payload["symbol"]["broker_wide_absence_concluded"])
        self.assertEqual(payload["symbol"]["CURRENT_TERMINAL_XAUUSD"], "NOT_OBSERVED")
        self.assertEqual(payload["ev_eq_01"]["status"], "NOT_PROVEN")
        self.assertEqual(payload["slippage"]["SLIPPAGE_POLICY"], "MODELED")
        self.assertEqual(payload["spread"]["SPREAD_POLICY"], "PROXY / PARTIAL")
        self.assertEqual(payload["swap"]["HISTORICAL_SWAP"], "UNKNOWN")
        self.assertEqual(payload["cost_gates"]["cost_ready_gate_count"], 0)
        self.assertFalse(payload["executable_contract"]["EXECUTABLE_BACKTEST_READY"])
        self.assertEqual(payload["executable_contract"]["readiness"], "BLOCKED")
        self.assertFalse(payload["executable_contract"]["executable_evaluation_run"])
        self.assertFalse(payload["reconstruction"]["commission_applied"])
        self.assertEqual(payload["reconstruction"]["status"], "BLOCKED_FOR_EXECUTABLE")
        self.assertEqual(payload["FINAL_GATE"], "BLOCKED")
        self.assertEqual(payload["verdict"]["overall"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(payload["verdict"]["EXECUTABLE_RESULT"], "NOT_RUN")
        self.assertEqual(payload["verdict"]["profitability_verdict"], "NOT_ISSUED")
        self.assertFalse(payload["phase_43_started"])
        self.assertFalse(payload["parameters_optimized"])
        self.assertFalse(payload["silent_xauusd_mapping"])
        self.assertGreaterEqual(len(payload["blocker_update"]), 8)
        self.assertTrue(all(b["CLOSURE"] == "OPEN" for b in payload["blocker_update"]))

    def test_safety_no_env_no_phase40_no_live_import(self) -> None:
        root = Path(__file__).resolve().parents[1]
        raw = (root / PHASE42_JSON).read_text(encoding="utf-8")
        payload = json.loads(raw)
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        self.assertFalse(payload["env_accessed"])
        self.assertEqual(payload["production_safety"]["TRADING"], "NOT_PERFORMED")
        self.assertEqual(payload["production_safety"]["ORDERS"], 0)
        self.assertEqual(payload["production_safety"]["BOT"], "NOT_STARTED")
        self.assertEqual(payload["production_safety"]["ENV"], "NOT_READ/CHANGED")
        self.assertEqual(payload["production_safety"]["PHASE40_RESCAN"], "NO")
        self.assertFalse(payload["production_safety"]["MT5_LAUNCHED"])
        self.assertEqual(payload["production_safety"]["production_changes"], "NONE")
        self.assertFalse(((payload.get("mt5") or {}).get("launch") or {}).get("launched_by_phase"))
        for secret in FORBIDDEN_ARTIFACT_KEYS:
            self.assertNotRegex(raw.lower(), rf'"{secret}"\s*:')
        for rel in (
            "tradingbot/backtest/phase42_broker_cost_execution_closure.py",
            "tradingbot/backtest/phase42_cost_reconstruction.py",
        ):
            src = (root / rel).read_text(encoding="utf-8")
            for token in FORBIDDEN_SOURCE_TOKENS:
                self.assertNotIn(token, src)
        md = (root / PHASE42_MD).read_text(encoding="utf-8")
        self.assertIn("STOP AFTER PHASE 42", md)
        self.assertIn("DO NOT START PHASE 43", md)
        ready = (root / PHASE42_READY_MD).read_text(encoding="utf-8")
        self.assertIn("EXECUTABLE_BACKTEST_READY", ready)
        matrix = (root / PHASE42_MATRIX_MD).read_text(encoding="utf-8")
        self.assertIn("cost_ready_gate_count", matrix)

    def test_reconstruction_does_not_invent_commission(self) -> None:
        rows = [
            {
                "outcome": "loss",
                "duration_minutes": 600,
                "timestamp": "2024-01-03T12:00:00+00:00",
                "exit_time": "2024-01-03T22:00:00+00:00",
                "entry_price": 2000.0,
                "stop_loss": 1990.0,
            }
        ]
        holds = overnight_candidates(rows)
        self.assertEqual(holds["resolved_trades"], 1)
        self.assertEqual(holds["share_ge_8h"], 1.0)
        recon = reconstruct_frozen_phase40(
            Path(__file__).resolve().parents[1],
            {"tick_size": 0.01, "tick_value": 1.0},
            {"current_swap_long": -89.136, "current_swap_short": 3.45},
        )
        self.assertFalse(recon["commission_applied"])
        self.assertEqual(recon["commission_status"], "UNKNOWN")
        self.assertFalse(recon["signals_regenerated"])
        self.assertEqual(recon["status"], "BLOCKED_FOR_EXECUTABLE")


if __name__ == "__main__":
    unittest.main()

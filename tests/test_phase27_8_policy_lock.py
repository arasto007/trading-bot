"""Phase 27.8 — Operator policy lock and policy≠evidence tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.cost_model import CostAvailability, CostCompleteness, build_backtest_cost_model
from tradingbot.backtest.dataset_contract import InstrumentContractError, resolve_broker_symbol_for_dataset
from tradingbot.backtest.metrics import compute_metrics
from tradingbot.backtest.models import BacktestResult
from tradingbot.backtest.phase27_8_policy_lock import (
    FORBIDDEN_OUTPUT_KEYS,
    LOCKED_POLICY,
    OPERATOR_POLICY_MD,
    PHASE278_JSON,
    PHASE278_MD,
    align_policy_with_evidence,
    cost_adjusted_validation_allowed,
    modeled_slippage_is_not_realized,
    parse_operator_policy,
    run_phase27_8_collection,
    silent_xauusd_binding_forbidden,
    verified_schedule_is_gate_not_proof,
    write_operator_policy_md,
)

FORBIDDEN = frozenset({"login", "password", "mt5_password"})


def setUpModule() -> None:
    run_phase27_8_collection(Path(__file__).resolve().parents[1])


class TestPhase278PolicyLock(unittest.TestCase):
    def test_artifact_valid(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE278_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["phase"], "27.8")
        self.assertEqual(payload["status"], "LOCKED")
        self.assertFalse(payload["awaiting_operator"])
        self.assertTrue(payload["policy_is_not_evidence"])

    def test_policy_document_not_awaiting(self) -> None:
        root = Path(__file__).resolve().parents[1]
        text = (root / OPERATOR_POLICY_MD).read_text(encoding="utf-8")
        header = "\n".join(text.splitlines()[:8])
        self.assertIn("LOCKED", header)
        self.assertNotIn("AWAITING OPERATOR", header)

    def test_six_decisions_preserved_exactly(self) -> None:
        root = Path(__file__).resolve().parents[1]
        parsed = parse_operator_policy((root / OPERATOR_POLICY_MD).read_text(encoding="utf-8"))
        self.assertTrue(parsed["locked"])
        self.assertTrue(parsed["matches_operator_selection"])
        self.assertEqual(parsed["decisions"], LOCKED_POLICY)
        payload = json.loads((root / PHASE278_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["operator_policy"]["decisions"], LOCKED_POLICY)

    def test_policy_is_not_evidence(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE278_JSON).read_text(encoding="utf-8"))
        self.assertTrue(payload["policy_is_not_evidence"])
        self.assertEqual(payload["policy_vs_evidence"]["rule"], "POLICY_IS_NOT_EVIDENCE")
        self.assertEqual(payload["inherited_evidence"]["ev_eq_01"], "NOT_PROVEN")
        self.assertFalse(payload["inherited_evidence"]["verified_schedule"])

    def test_decision_3_verified_schedule_is_gate_not_proof(self) -> None:
        gate = verified_schedule_is_gate_not_proof(False)
        self.assertEqual(gate["policy"], "VERIFIED_SCHEDULE")
        self.assertFalse(gate["policy_means_verified_schedule_exists"])
        self.assertFalse(gate["commission_accepted_for_validation"])
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE278_JSON).read_text(encoding="utf-8"))
        self.assertTrue(
            payload["policy_vs_evidence"]["decision_3_verified_schedule_is_not_current_verification"]
        )
        text = (root / OPERATOR_POLICY_MD).read_text(encoding="utf-8")
        self.assertIn("may only be accepted for validation when a verified", text)
        self.assertIn("not a verification", text.lower())

    def test_decision_1_does_not_claim_equivalence(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE278_JSON).read_text(encoding="utf-8"))
        self.assertTrue(payload["policy_vs_evidence"]["decision_1_does_not_claim_equivalence"])
        self.assertEqual(payload["policy_vs_evidence"]["ev_eq_01"], "NOT_PROVEN")
        text = (root / OPERATOR_POLICY_MD).read_text(encoding="utf-8")
        self.assertIn("NOT_PROVEN", text)
        self.assertIn("economically equivalent", text)

    def test_decision_2_forbids_silent_xauusd_binding(self) -> None:
        binding = silent_xauusd_binding_forbidden()
        self.assertTrue(binding["silent_bind_raised"])
        self.assertEqual(binding["silent_bind_code"], "SYMBOL_MISMATCH")
        self.assertTrue(binding["explicit_map_permitted"])
        self.assertTrue(binding["empty_map_is_not_a_relationship"])
        with self.assertRaises(InstrumentContractError):
            resolve_broker_symbol_for_dataset("XAUUSD", configured_symbol="XAUUSD_i")
        with self.assertRaises(InstrumentContractError):
            resolve_broker_symbol_for_dataset(
                "XAUUSD",
                configured_symbol="XAUUSD_i",
                dataset_symbol_map={},
            )
        mapped, source = resolve_broker_symbol_for_dataset(
            "XAUUSD",
            configured_symbol="XAUUSD_i",
            dataset_symbol_map={"XAUUSD": "XAUUSD_i"},
        )
        self.assertEqual(mapped, "XAUUSD_i")
        self.assertEqual(source, "explicit_map")

    def test_decision_4_does_not_invent_historical_swap(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE278_JSON).read_text(encoding="utf-8"))
        self.assertTrue(payload["policy_vs_evidence"]["decision_4_forbids_invented_historical_swap"])
        self.assertEqual(payload["inherited_evidence"]["historical_swap_series"], "UNKNOWN")
        text = (root / OPERATOR_POLICY_MD).read_text(encoding="utf-8")
        self.assertIn("historical swap series must not be invented", text)

    def test_decision_5_modeled_is_not_realized(self) -> None:
        slip = modeled_slippage_is_not_realized(True)
        self.assertTrue(slip["modeled_permitted"])
        self.assertFalse(slip["represented_as_realized"])
        self.assertFalse(slip["realized_historical_slippage_proven"])
        self.assertFalse(slip["mt5_deviation_is_slippage"])
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE278_JSON).read_text(encoding="utf-8"))
        self.assertTrue(payload["policy_vs_evidence"]["decision_5_modeled_is_not_realized"])
        text = (root / OPERATOR_POLICY_MD).read_text(encoding="utf-8")
        self.assertIn("never be represented as realized slippage", text)

    def test_decision_6_complete_costs_required_blocks_incomplete(self) -> None:
        self.assertFalse(cost_adjusted_validation_allowed(CostCompleteness.UNKNOWN))
        self.assertFalse(cost_adjusted_validation_allowed(CostCompleteness.PARTIAL))
        self.assertTrue(cost_adjusted_validation_allowed(CostCompleteness.COMPLETE))
        result = BacktestResult(
            config=BacktestConfig(),
            initial_balance=1000.0,
            final_balance=1000.0,
            trades=[],
            equity_curve=[{"equity": 1000.0}],
        )
        unknown = compute_metrics(result, cost_completeness=CostCompleteness.UNKNOWN)
        complete = compute_metrics(result, cost_completeness=CostCompleteness.COMPLETE)
        self.assertFalse(unknown["cost_adjusted_metrics"])
        self.assertTrue(complete["cost_adjusted_metrics"])
        model = build_backtest_cost_model(BacktestConfig())
        self.assertEqual(model.commission.availability, CostAvailability.UNKNOWN)

    def test_fail_closed_preserves_policy_on_evidence_gap(self) -> None:
        inherited = {
            "ev_eq_01": {"status": "NOT_PROVEN"},
            "commission": {"status": "UNKNOWN", "verified_schedule": False},
            "swap": {"historical_swap_series": "UNKNOWN"},
            "slippage": {"status": "UNKNOWN", "realized_sample_count": 0},
            "spread": {"historical_m5_tape_available": False},
            "cost_completeness": {"status": "UNKNOWN", "complete_count": 0},
            "real_operator_evidence": {"fresh_collected": False},
            "dataset_binding": {"xauusd_count": 30},
        }
        alignment = align_policy_with_evidence(LOCKED_POLICY, inherited)
        self.assertFalse(alignment["policy_changed_to_fit_evidence"])
        self.assertFalse(alignment["any_conflict_reconciled"])
        self.assertEqual(alignment["rule"], "PRESERVE_OPERATOR_POLICY_RECORD_EVIDENCE_GAP")
        for row in alignment["rows"]:
            self.assertEqual(row["preserved_policy"], LOCKED_POLICY[row["decision"]])
            self.assertTrue(row["gap"])
            self.assertFalse(row["conflict"])

    def test_parser_rejects_awaiting_header_as_locked(self) -> None:
        stale = (
            "# Operator Broker Policy Decision\n\n"
            "**Status:** AWAITING OPERATOR — Phase 27.6 does not fill these with guesses.\n\n"
            "## DECISION 1: Canonical gold symbol\n\n- [x] XAUUSD_i\n"
            "## DECISION 2\n\n- [x] ONLY_WITH_EXPLICIT_DATASET_MAP\n"
            "## DECISION 3\n\n- [x] VERIFIED_SCHEDULE\n"
            "## DECISION 4\n\n- [x] BROKER_RATE_ONLY\n"
            "## DECISION 5\n\n- [x] MODELED\n"
            "## DECISION 6\n\n- [x] COMPLETE_COSTS_REQUIRED\n"
        )
        parsed = parse_operator_policy(stale)
        self.assertTrue(parsed["awaiting_operator"])
        self.assertFalse(parsed["locked"])
        self.assertNotEqual(parsed["status"], "LOCKED")

    def test_production_remains_blocked(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE278_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["production_readiness"], "BLOCKED")
        self.assertFalse(payload["production_authorized"])
        self.assertEqual(payload["production_changes"], "NONE")
        self.assertFalse(payload["cost_ready_for_validation"])

    def test_evidence_gaps_recorded(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE278_JSON).read_text(encoding="utf-8"))
        missing = " ".join(payload["evidence_still_missing"])
        self.assertIn("EV-EQ-01", missing)
        self.assertIn("commission", missing.lower())
        self.assertIn("swap", missing.lower())
        self.assertIn("bid/ask", missing.lower())
        self.assertIn("slippage", missing.lower())
        self.assertFalse(payload["inherited_evidence"]["fresh_real_evidence"])
        self.assertFalse(payload["inherited_evidence"]["historical_m5_bidask"])

    def test_no_hidden_zero_costs(self) -> None:
        model = build_backtest_cost_model(BacktestConfig())
        self.assertEqual(model.commission.availability, CostAvailability.UNKNOWN)

    def test_safety_no_mt5_no_orders_no_secrets(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE278_JSON).read_text(encoding="utf-8"))
        safety = payload["safety_confirmation"]
        self.assertFalse(safety["mt5_started"])
        self.assertFalse(safety["symbol_select"])
        self.assertFalse(safety["orders_sent"])
        self.assertFalse(safety["credentials_accessed"])
        self.assertFalse(safety["env_modified"])
        self.assertFalse(safety["trading_enabled"])
        self.assertFalse(safety["evidence_fabricated"])
        blob = (root / PHASE278_JSON).read_text(encoding="utf-8").lower()
        for key in FORBIDDEN | FORBIDDEN_OUTPUT_KEYS:
            self.assertNotIn(f'"{key}"', blob)

    def test_immutable_historical_demo_evidence(self) -> None:
        root = Path(__file__).resolve().parents[1]
        demo = root / "logs/operator_broker_evidence_demo_raw.json"
        before = demo.read_text(encoding="utf-8")
        run_phase27_8_collection(root)
        self.assertEqual(before, demo.read_text(encoding="utf-8"))

    def test_phase27_6_does_not_overwrite_lock(self) -> None:
        root = Path(__file__).resolve().parents[1]
        write_operator_policy_md(root)
        from tradingbot.backtest.phase27_6_final_evidence_gate import _write_operator_policy_md

        _write_operator_policy_md(root)
        text = (root / OPERATOR_POLICY_MD).read_text(encoding="utf-8")
        header = "\n".join(text.splitlines()[:8])
        self.assertIn("LOCKED", header)
        self.assertNotIn("AWAITING OPERATOR", header)
        parsed = parse_operator_policy(text)
        self.assertEqual(parsed["decisions"], LOCKED_POLICY)

    def test_phase278_md_exists(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.assertTrue((root / PHASE278_MD).is_file())
        text = (root / PHASE278_MD).read_text(encoding="utf-8")
        self.assertIn("POLICY ≠ EVIDENCE", text)
        self.assertIn("BLOCKED", text)
        self.assertIn("STOP after Phase 27.8", text)

    def test_no_production_path_mutations(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE278_JSON).read_text(encoding="utf-8"))
        safety = payload["safety_confirmation"]
        for key in (
            "strategy_modified",
            "riskgate_modified",
            "execution_modified",
            "sizing_modified",
            "rr_modified",
            "ml_modified",
        ):
            self.assertFalse(safety[key])

    def test_cross_check_docs_no_longer_claim_undecided_policy(self) -> None:
        root = Path(__file__).resolve().parents[1]
        unknowns = (root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md").read_text(encoding="utf-8")
        self.assertIn("LOCKED", unknowns)
        self.assertNotIn("OPERATOR_BROKER_POLICY_DECISION.md` (UNDECIDED)", unknowns)
        design = (root / "docs_v2/01_truth/DEMO_REAL_SYMBOL_COST_DESIGN.md").read_text(encoding="utf-8")
        self.assertIn("POLICY AUTHORIZED", design)
        self.assertIn("ONLY_WITH_EXPLICIT_DATASET_MAP", design)
        self.assertNotIn("**not authorized** without operator policy decision", design)
        config = (root / "docs_v2/01_truth/CONFIGURATION_TRUTH.md").read_text(encoding="utf-8")
        self.assertIn("Phase 27.8", config)
        closure = (root / "docs_v2/01_truth/PHASE27_7_FINAL_BLOCKER_CLOSURE.md").read_text(encoding="utf-8")
        self.assertIn("Phase 27.8", closure)
        self.assertIn("does not convert missing evidence", closure)


if __name__ == "__main__":
    unittest.main()

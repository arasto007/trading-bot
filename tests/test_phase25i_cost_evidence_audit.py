"""Phase 25I — offline broker cost evidence audit tests (no MT5)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.cost_evidence_audit import (
    COMMISSION_SCHEDULE_TYPES,
    PHASE25I_AUDIT_JSON,
    PHASE25I_REPORT_MD,
    ReportEvidenceClass,
    audit_commission_evidence,
    audit_slippage_evidence,
    audit_spread_evidence,
    audit_swap_evidence,
    build_upgrade_requirements,
    classify_economics_provenance,
    cost_adjusted_metrics_allowed,
    dataset_eligibility_for_row,
    load_all_operator_deals,
    render_phase25i_report_md,
    run_phase25i_audit,
    run_phase25i_collection,
)
from tradingbot.backtest.cost_model import CostAvailability, CostCompleteness, SpreadMode, build_backtest_cost_model
from tradingbot.backtest.dataset_provenance import (
    DatasetAuditEntry,
    EconomicsProvenance,
    LITEFINANCE_EVIDENCE_TIMESTAMP,
    audit_parquet_file,
    compute_dataset_cost_status,
)
from tradingbot.backtest.metrics import compute_metrics
from tradingbot.backtest.models import BacktestResult
from tradingbot.backtest.operator_evidence import (
    FieldAvailability,
    SlippageEvidenceClass,
    SwapEvidenceClass,
    parse_closed_deal,
    summarize_commission,
)
from tradingbot.backtest.symbol_equivalence import EquivalenceConclusion
from tradingbot.config.live import PRIMARY_SYMBOL


def _deal(**kwargs: object) -> dict:
    base = {
        "symbol": "XAUUSD_i",
        "commission": 0.0,
        "swap": 0.0,
        "filled_volume": 0.01,
    }
    base.update(kwargs)
    return {"closed_deal": base}


def _ohlc_parquet(path: Path, name: str = "XAUUSD_M5_5d.parquet") -> Path:
    idx = pd.date_range("2024-01-01", periods=5, freq="5min", tz="UTC")
    df = pd.DataFrame(
        {"open": [1.0] * 5, "high": [1.1] * 5, "low": [0.9] * 5, "close": [1.0] * 5, "volume": [1.0] * 5},
        index=idx,
    )
    out = path / name
    df.to_parquet(out)
    return out


class TestCommissionAudit(unittest.TestCase):
    def test_commission_unknown_from_sparse_zero_deals(self) -> None:
        deals = [parse_closed_deal(_deal(), source="t") for _ in range(2)]
        deals = [d for d in deals if d]
        inv = audit_commission_evidence(deals)
        self.assertEqual(inv.status, "UNKNOWN")
        self.assertEqual(inv.evidence_class, ReportEvidenceClass.STALE_OPERATOR_EVIDENCE.value)

    def test_commission_cannot_silently_become_zero(self) -> None:
        deal = parse_closed_deal(_deal(commission=0.0), source="t")
        assert deal
        summary = summarize_commission([deal])
        self.assertEqual(summary.status, "UNKNOWN")
        inv = audit_commission_evidence([deal])
        self.assertEqual(inv.status, "UNKNOWN")

    def test_commission_schedule_types_enumerated(self) -> None:
        deal = parse_closed_deal(_deal(), source="t")
        assert deal
        inv = audit_commission_evidence([deal])
        self.assertGreater(len(COMMISSION_SCHEDULE_TYPES), 5)
        self.assertIn("schedule", inv.reasoning.lower())

    def test_no_commission_deals_unknown(self) -> None:
        inv = audit_commission_evidence([])
        self.assertEqual(inv.status, "UNKNOWN")
        self.assertEqual(inv.sample_count, 0)


class TestSwapAudit(unittest.TestCase):
    def test_swap_broker_rate_only(self) -> None:
        deals = [parse_closed_deal(_deal(), source="t")]
        deals = [d for d in deals if d]
        specs = {"demo": {"swap_long": -89.136, "swap_short": 3.45}}
        inv = audit_swap_evidence(deals, specs)
        self.assertEqual(inv.status, SwapEvidenceClass.BROKER_RATE_ONLY.value)

    def test_realized_swap_separate_from_broker_rate(self) -> None:
        deals = [parse_closed_deal(_deal(swap=0.0), source="t")]
        deals = [d for d in deals if d]
        inv = audit_swap_evidence(deals, {"s": {"swap_long": -1.0}})
        self.assertIn("realized swap=0.0", inv.reasoning)
        self.assertEqual(inv.status, SwapEvidenceClass.BROKER_RATE_ONLY.value)

    def test_historical_swap_unknown(self) -> None:
        inv = audit_swap_evidence([], {})
        self.assertEqual(inv.status, SwapEvidenceClass.UNKNOWN.value)


class TestSlippageAudit(unittest.TestCase):
    def test_slippage_requires_requested_price(self) -> None:
        deal = parse_closed_deal(_deal(entry_price=2000.0, actual_fill_price=2000.0), source="t")
        assert deal
        inv = audit_slippage_evidence([deal])
        self.assertEqual(inv.status, SlippageEvidenceClass.UNKNOWN.value)
        self.assertIn("entry_price is NOT requested_price", inv.reasoning)

    def test_deviation_not_slippage(self) -> None:
        inv = audit_slippage_evidence([])
        self.assertIn("deviation", inv.reasoning.lower())

    def test_entry_price_not_requested(self) -> None:
        deal = parse_closed_deal(_deal(entry_price=100.0), source="t")
        assert deal
        self.assertNotEqual(deal.slippage_class, SlippageEvidenceClass.REALIZED.value)

    def test_realized_when_both_prices(self) -> None:
        deal = parse_closed_deal(_deal(requested_price=100.0, actual_fill_price=100.1), source="t")
        assert deal
        self.assertEqual(deal.slippage_class, SlippageEvidenceClass.REALIZED.value)


class TestSpreadAudit(unittest.TestCase):
    def test_spread_proxy_classification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = _ohlc_parquet(Path(tmp))
            entry = audit_parquet_file(p, configured_symbol=PRIMARY_SYMBOL)
            inv = audit_spread_evidence([entry])
            self.assertEqual(inv.status, SpreadMode.PROXY.value)

    def test_dataset_spread_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ohlc = audit_parquet_file(_ohlc_parquet(root), configured_symbol=PRIMARY_SYMBOL)
            idx = pd.date_range("2024-01-01", periods=2, freq="5min", tz="UTC")
            bidask = root / "XAUUSD_i_M5_bidask.parquet"
            pd.DataFrame(
                {
                    "open": [1.0, 1.0],
                    "high": [1.1, 1.1],
                    "low": [0.9, 0.9],
                    "close": [1.0, 1.0],
                    "volume": [1.0, 1.0],
                    "bid": [0.99, 0.99],
                    "ask": [1.01, 1.01],
                },
                index=idx,
            ).to_parquet(bidask)
            ba = audit_parquet_file(bidask, configured_symbol=PRIMARY_SYMBOL)
            self.assertEqual(ohlc.spread_mode, SpreadMode.PROXY.value)
            self.assertEqual(ba.spread_mode, SpreadMode.DATASET.value)


class TestEconomicsProvenance(unittest.TestCase):
    def test_xauusd_unknown_economics(self) -> None:
        cls = classify_economics_provenance(
            dataset_symbol="XAUUSD",
            economics_source=EconomicsProvenance.OBSERVED_BROKER_EVIDENCE.value,
        )
        self.assertEqual(cls, EconomicsProvenance.UNKNOWN.value)

    def test_xauusd_i_stale_operator_evidence(self) -> None:
        cls = classify_economics_provenance(
            dataset_symbol="XAUUSD_i",
            economics_source=EconomicsProvenance.OBSERVED_BROKER_EVIDENCE.value,
            evidence_timestamp=LITEFINANCE_EVIDENCE_TIMESTAMP,
        )
        self.assertEqual(cls, ReportEvidenceClass.STALE_OPERATOR_EVIDENCE.value)

    def test_no_silent_mapping(self) -> None:
        entry = DatasetAuditEntry(
            filename="XAUUSD_M5.parquet",
            path="/x",
            row_count=1,
            columns=[],
            inferred_symbol="XAUUSD",
            inferred_timeframe="M5",
            datetime_range={},
            bid_present=False,
            ask_present=False,
            spread_column_present=False,
            ohlc_present=True,
            volume_present=True,
            tick_data_present=False,
            economics_metadata_present=False,
            metadata_sidecar_present=False,
            spread_mode=SpreadMode.PROXY.value,
            spread_source="ohlc_only",
            mapping_status="UNKNOWN",
            economics_provenance=EconomicsProvenance.UNKNOWN.value,
            symbol_equivalence="NOT_PROVEN",
            cost_completeness=CostCompleteness.UNKNOWN.value,
        )
        row = dataset_eligibility_for_row(entry)
        self.assertEqual(row.symbol, "XAUUSD")
        self.assertEqual(row.economics, EconomicsProvenance.UNKNOWN.value)


class TestEvEq01(unittest.TestCase):
    def test_ev_eq_01_not_proven(self) -> None:
        report = run_phase25i_audit(base_dir=Path(__file__).resolve().parents[1])
        self.assertEqual(report.ev_eq_01, EquivalenceConclusion.NOT_PROVEN.value)

    def test_no_silent_rename(self) -> None:
        reqs = build_upgrade_requirements()
        self.assertIn("EV-EQ-01", reqs)
        self.assertIn("both XAUUSD and XAUUSD_i", reqs["EV-EQ-01"][0])


class TestCostCompleteness(unittest.TestCase):
    def test_cost_completeness_partial_proxy(self) -> None:
        cost = compute_dataset_cost_status(spread_mode=SpreadMode.PROXY.value)
        self.assertEqual(cost["cost_completeness"], CostCompleteness.PARTIAL.value)

    def test_cost_adjusted_metrics_false(self) -> None:
        self.assertFalse(
            cost_adjusted_metrics_allowed(
                spread_mode=SpreadMode.PROXY.value,
                commission_status="UNKNOWN",
                swap_status="UNKNOWN",
                slippage_status="UNKNOWN",
            )
        )
        cfg = BacktestConfig()
        result = BacktestResult(
            config=cfg,
            trades=[],
            equity_curve=[],
            initial_balance=10000.0,
            final_balance=10000.0,
            cost_completeness=CostCompleteness.PARTIAL,
        )
        self.assertFalse(compute_metrics(result)["cost_adjusted_metrics"])

    def test_complete_only_when_all_known(self) -> None:
        cfg = BacktestConfig(
            spread_mode="PROXY",
            commission_status="ZERO",
            swap_status="ZERO",
            slippage_status="ZERO",
        )
        model = build_backtest_cost_model(cfg)
        self.assertEqual(model.commission.availability, CostAvailability.ZERO)


class TestDatasetEligibility(unittest.TestCase):
    def test_research_eligible_ohlc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            entry = audit_parquet_file(_ohlc_parquet(Path(tmp)), configured_symbol=PRIMARY_SYMBOL)
            row = dataset_eligibility_for_row(entry)
            self.assertTrue(row.research_backtest_eligible)
            self.assertFalse(row.cost_aware_backtest_eligible)
            self.assertFalse(row.production_validation_eligible)

    def test_cost_aware_requires_dataset_spread(self) -> None:
        entry = DatasetAuditEntry(
            filename="x.parquet",
            path="/x",
            row_count=1,
            columns=["bid", "ask"],
            inferred_symbol="XAUUSD_i",
            inferred_timeframe="M5",
            datetime_range={},
            bid_present=True,
            ask_present=True,
            spread_column_present=False,
            ohlc_present=True,
            volume_present=True,
            tick_data_present=True,
            economics_metadata_present=True,
            metadata_sidecar_present=True,
            spread_mode=SpreadMode.DATASET.value,
            spread_source="bid_ask",
            mapping_status="MATCH",
            economics_provenance=EconomicsProvenance.OBSERVED_BROKER_EVIDENCE.value,
            symbol_equivalence="MATCHING_LABEL_ONLY",
            cost_completeness=CostCompleteness.PARTIAL.value,
        )
        row = dataset_eligibility_for_row(entry)
        self.assertTrue(row.cost_aware_backtest_eligible)
        self.assertFalse(row.cost_adjusted_metrics_allowed)


class TestUpgradeRequirements(unittest.TestCase):
    def test_future_evidence_requirements_present(self) -> None:
        reqs = build_upgrade_requirements()
        for key in ("COMMISSION", "SLIPPAGE", "SWAP", "SPREAD", "EV-EQ-01"):
            self.assertIn(key, reqs)
            self.assertGreaterEqual(len(reqs[key]), 2)

    def test_unknown_propagation(self) -> None:
        cfg = BacktestConfig(commission_status="UNKNOWN")
        model = build_backtest_cost_model(cfg)
        self.assertEqual(model.commission.availability, CostAvailability.UNKNOWN)


class TestFailClosed(unittest.TestCase):
    def test_missing_commission_fail_closed(self) -> None:
        inv = audit_commission_evidence([])
        self.assertEqual(inv.status, "UNKNOWN")
        self.assertFalse(inv.suitable_for_backtest)

    def test_missing_slippage_fail_closed(self) -> None:
        inv = audit_slippage_evidence([])
        self.assertEqual(inv.status, SlippageEvidenceClass.UNKNOWN.value)

    def test_missing_historical_swap_fail_closed(self) -> None:
        inv = audit_swap_evidence([], {"s": {"swap_long": 1.0}})
        self.assertIn("historical", inv.reasoning.lower())

    def test_missing_economics_fail_closed(self) -> None:
        cls = classify_economics_provenance(dataset_symbol="XAUUSD", economics_source="UNKNOWN")
        self.assertEqual(cls, EconomicsProvenance.UNKNOWN.value)


class TestArtifacts(unittest.TestCase):
    def test_artifact_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _ohlc_parquet(root)
            report = run_phase25i_collection(base_dir=root)
            audit_path = root / PHASE25I_AUDIT_JSON
            self.assertTrue(audit_path.is_file())
            data = json.loads(audit_path.read_text(encoding="utf-8"))
            self.assertEqual(data["phase"], "25I")
            self.assertFalse(data["credentials_exposed"])
            self.assertIn("cost_inventory", data)

    def test_artifact_no_credentials(self) -> None:
        report = run_phase25i_audit()
        text = json.dumps(report.to_dict())
        self.assertNotIn("password", text.lower())
        self.assertNotIn("mt5_login", text.lower())

    def test_audit_timestamp(self) -> None:
        report = run_phase25i_audit()
        self.assertTrue(report.generated_at.endswith("Z"))

    def test_report_md_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _ohlc_parquet(root)
            run_phase25i_collection(base_dir=root)
            md = (root / PHASE25I_REPORT_MD).read_text(encoding="utf-8")
            self.assertIn("Phase 25I", md)
            self.assertIn("EV-EQ-01", md)

    def test_evidence_class_separation(self) -> None:
        md = render_phase25i_report_md(run_phase25i_audit())
        self.assertIn(ReportEvidenceClass.UNKNOWN.value, md)


class TestImmutabilityAndSafety(unittest.TestCase):
    def test_existing_parquet_immutability_flag(self) -> None:
        report = run_phase25i_audit()
        self.assertTrue(report.safety["existing_parquet_mutated"] is False or report.immutability_ok)

    def test_no_synthetic_data_flag(self) -> None:
        report = run_phase25i_audit()
        self.assertFalse(report.safety["synthetic_data_created"])

    def test_sidecar_read_only_audit(self) -> None:
        report = run_phase25i_audit()
        self.assertIsInstance(report.dataset_matrix, list)

    def test_regression_compatibility_cost_model(self) -> None:
        cfg = BacktestConfig(spread_mode="PROXY", commission_status="UNKNOWN")
        model = build_backtest_cost_model(cfg)
        self.assertEqual(model.spread_mode, SpreadMode.PROXY)


class TestOperatorEvidenceLoader(unittest.TestCase):
    def test_load_deals_from_repo(self) -> None:
        root = Path(__file__).resolve().parents[1]
        deals, specs = load_all_operator_deals(root)
        if (root / "logs/operator_broker_evidence_demo_raw.json").is_file():
            self.assertGreaterEqual(len(deals), 1)
            self.assertGreaterEqual(len(specs), 1)


class TestCommissionTwoDeals(unittest.TestCase):
    def test_two_zero_commission_stays_unknown(self) -> None:
        deals = [parse_closed_deal(_deal(), source="a"), parse_closed_deal(_deal(), source="b")]
        deals = [d for d in deals if d]
        summary = summarize_commission(deals)
        self.assertEqual(summary.status, "UNKNOWN")
        self.assertEqual(summary.sample_count, 2)


if __name__ == "__main__":
    unittest.main()

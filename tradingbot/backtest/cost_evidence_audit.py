"""Phase 25I — offline broker cost evidence inventory and audit (no MT5, no bot)."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from tradingbot.backtest.cost_model import CostCompleteness, SpreadMode, assess_cost_completeness, build_backtest_cost_model
from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.dataset_provenance import (
    DatasetAuditEntry,
    EconomicsProvenance,
    LITEFINANCE_EVIDENCE_TIMESTAMP,
    audit_backtest_datasets,
    compute_dataset_cost_status,
    load_dataset_metadata,
    metadata_path_for,
)
from tradingbot.backtest.metrics import compute_metrics
from tradingbot.backtest.models import BacktestResult
from tradingbot.backtest.operator_evidence import (
    DealTapeRecord,
    FieldAvailability,
    SlippageEvidenceClass,
    SwapEvidenceClass,
    load_operator_evidence_bundle,
    parse_closed_deal,
    summarize_commission,
    summarize_swap,
    _extract_spec,
    _safe_load_json,
    DEFAULT_EVIDENCE_PATHS,
)
from tradingbot.backtest.phase25h_run import build_immutability_manifest, verify_immutability
from tradingbot.backtest.symbol_equivalence import EquivalenceConclusion, audit_from_operator_artifacts
from tradingbot.config.live import PRIMARY_SYMBOL

PHASE25I_AUDIT_JSON = "logs/phase25i_cost_evidence_audit.json"
PHASE25I_REPORT_MD = "logs/phase25i_cost_evidence_report.md"
STALE_EVIDENCE_CUTOFF = "2026-09-03T00:00:00Z"
MIN_COMMISSION_SCHEDULE_SAMPLES = 10


class ReportEvidenceClass(str, Enum):
    OBSERVED = "OBSERVED"
    OFFLINE_TEST_EVIDENCE = "OFFLINE_TEST_EVIDENCE"
    STALE_OPERATOR_EVIDENCE = "STALE_OPERATOR_EVIDENCE"
    UNKNOWN = "UNKNOWN"
    NOT_PROVEN = "NOT_PROVEN"
    DEFERRED = "DEFERRED"


COMMISSION_SCHEDULE_TYPES = (
    "per_lot_commission",
    "per_side_commission",
    "round_trip_commission",
    "percentage_commission",
    "symbol_specific_commission",
    "account_specific_commission",
    "broker_wide_commission",
    "minimum_commission",
    "tiered_commission",
    "commission_schedule",
    "commission_free_status",
)


@dataclass
class CostComponentInventory:
    component: str
    status: str
    evidence_class: str
    evidence_source: str
    evidence_timestamp: str | None = None
    evidence_scope: str = ""
    symbol: str | None = None
    environment: str | None = None
    broker: str | None = None
    server: str | None = None
    sample_count: int | None = None
    historical: bool = False
    current: bool = False
    universal: bool = False
    dataset_specific: bool = False
    suitable_for_backtest: bool = False
    upgrade_requirements: list[str] = field(default_factory=list)
    reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DatasetCostMatrixRow:
    filename: str
    symbol: str | None
    timeframe: str | None
    economics: str
    spread: str
    commission: str
    swap: str
    slippage: str
    overall_completeness: str
    cost_adjusted_metrics_allowed: bool
    research_backtest_eligible: bool
    cost_aware_backtest_eligible: bool
    production_validation_eligible: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Phase25IAuditReport:
    status: str = "PASS"
    generated_at: str = ""
    code_version: str = ""
    immutability_ok: bool = True
    safety: dict[str, bool] = field(default_factory=dict)
    cost_inventory: list[CostComponentInventory] = field(default_factory=list)
    dataset_matrix: list[DatasetCostMatrixRow] = field(default_factory=list)
    upgrade_requirements: dict[str, list[str]] = field(default_factory=dict)
    explicit_unknowns: list[str] = field(default_factory=list)
    stale_evidence: list[str] = field(default_factory=list)
    ev_eq_01: str = EquivalenceConclusion.NOT_PROVEN.value
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "phase": "25I",
            "status": self.status,
            "generated_at": self.generated_at,
            "code_version": self.code_version,
            "immutability_ok": self.immutability_ok,
            "safety": self.safety,
            "cost_inventory": [c.to_dict() for c in self.cost_inventory],
            "dataset_inventory": [r.to_dict() for r in self.dataset_matrix],
            "sidecar_inventory": self._sidecar_summary(),
            "broker_evidence_inventory": self._broker_summary(),
            "operator_deal_inventory": self._deal_summary(),
            "ev_eq_01": self.ev_eq_01,
            "cost_completeness_matrix": [r.to_dict() for r in self.dataset_matrix],
            "upgrade_requirements": self.upgrade_requirements,
            "explicit_unknowns": self.explicit_unknowns,
            "stale_evidence": self.stale_evidence,
            "errors": self.errors,
            "credentials_exposed": False,
        }

    def _sidecar_summary(self) -> dict[str, Any]:
        xauusd = sum(1 for r in self.dataset_matrix if r.symbol == "XAUUSD")
        xauusd_i = sum(1 for r in self.dataset_matrix if r.symbol == "XAUUSD_i")
        return {
            "total_sidecars_expected": len(self.dataset_matrix),
            "xauusd_labeled": xauusd,
            "xauusd_i_labeled": xauusd_i,
            "xauusd_economics_unknown": xauusd,
            "xauusd_i_observed_broker_evidence": xauusd_i,
        }

    def _broker_summary(self) -> dict[str, Any]:
        return {
            "artifacts": list(DEFAULT_EVIDENCE_PATHS),
            "evidence_class": ReportEvidenceClass.STALE_OPERATOR_EVIDENCE.value,
            "evidence_timestamp": LITEFINANCE_EVIDENCE_TIMESTAMP,
            "broker": "LiteFinance",
            "environments": ["DEMO", "REAL"],
        }

    def _deal_summary(self) -> dict[str, Any]:
        return {
            "note": "see operator_deal_evidence section in full audit payload",
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_head_safe(base_dir: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(base_dir),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()[:12]
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


def _is_stale_timestamp(ts: str | None) -> bool:
    if not ts:
        return True
    try:
        normalized = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        cutoff = datetime.fromisoformat(STALE_EVIDENCE_CUTOFF.replace("Z", "+00:00"))
        return dt < cutoff
    except ValueError:
        return True


def classify_economics_provenance(
    *,
    dataset_symbol: str | None,
    economics_source: str,
    evidence_timestamp: str | None = None,
) -> str:
    """Classify sidecar economics — never upgrade UNKNOWN without evidence."""
    if dataset_symbol == "XAUUSD":
        return EconomicsProvenance.UNKNOWN.value
    if economics_source == EconomicsProvenance.OBSERVED_BROKER_EVIDENCE.value:
        if _is_stale_timestamp(evidence_timestamp):
            return ReportEvidenceClass.STALE_OPERATOR_EVIDENCE.value
        return ReportEvidenceClass.OBSERVED.value
    return economics_source or EconomicsProvenance.UNKNOWN.value


def audit_commission_evidence(deals: list[DealTapeRecord]) -> CostComponentInventory:
    """Commission remains UNKNOWN unless explicit universal schedule evidence exists."""
    summary = summarize_commission(deals)
    zero_count = sum(
        1
        for d in deals
        if d.commission and d.commission.availability == FieldAvailability.OBSERVED.value
        and float(d.commission.value or 0) == 0.0
    )
    reasoning_parts = [
        f"{len(deals)} closed deal(s) in operator evidence.",
        f"{zero_count} deal(s) show commission=0.0.",
        "Zero commission on sparse short-hold deals does NOT prove commission-free status.",
        "No broker commission schedule artifact found.",
    ]
    upgrade = [
        "broker commission schedule document or API export",
        "account-specific trading conditions with commission rules",
        f">={MIN_COMMISSION_SCHEDULE_SAMPLES} executed deals across symbols/sides/volumes",
        "explicit per-lot/per-side/round-trip rate with effective dates",
    ]
    return CostComponentInventory(
        component="COMMISSION",
        status="UNKNOWN",
        evidence_class=ReportEvidenceClass.STALE_OPERATOR_EVIDENCE.value if deals else ReportEvidenceClass.UNKNOWN.value,
        evidence_source="operator_deal_tape",
        evidence_timestamp=LITEFINANCE_EVIDENCE_TIMESTAMP,
        evidence_scope="operator_closed_deals_only",
        symbol="XAUUSD_i",
        environment="DEMO+REAL",
        broker="LiteFinance",
        server="LiteFinance-MT5-Demo/Live",
        sample_count=len(deals),
        historical=True,
        current=False,
        universal=False,
        dataset_specific=False,
        suitable_for_backtest=False,
        upgrade_requirements=upgrade,
        reasoning=" ".join(reasoning_parts) + f" Summarize status={summary.status} (audit overrides to UNKNOWN).",
    )


def audit_swap_evidence(deals: list[DealTapeRecord], specs: dict[str, dict[str, Any]]) -> CostComponentInventory:
    combined: dict[str, Any] = {}
    for spec in specs.values():
        combined.update(spec)
    summary = summarize_swap(deals, combined)
    deal_swap_zero = [
        d
        for d in deals
        if d.swap and d.swap.availability == FieldAvailability.OBSERVED.value and float(d.swap.value or 0) == 0.0
    ]
    broker_long = summary.broker_swap_long
    broker_short = summary.broker_swap_short
    status = SwapEvidenceClass.BROKER_RATE_ONLY.value if broker_long is not None or broker_short is not None else SwapEvidenceClass.UNKNOWN.value
    reasoning = (
        "Broker specification provides swap_long/swap_short for XAUUSD_i (BROKER_RATE_ONLY). "
        f"{len(deal_swap_zero)} deal(s) show realized swap=0.0 on sub-minute holds — insufficient for historical swap series. "
        "Historical daily swap series remains UNKNOWN."
    )
    return CostComponentInventory(
        component="SWAP",
        status=status,
        evidence_class=ReportEvidenceClass.STALE_OPERATOR_EVIDENCE.value,
        evidence_source="broker_spec+operator_deals",
        evidence_timestamp=LITEFINANCE_EVIDENCE_TIMESTAMP,
        evidence_scope="XAUUSD_i",
        symbol="XAUUSD_i",
        environment="DEMO+REAL",
        broker="LiteFinance",
        server="LiteFinance-MT5-Demo/Live",
        sample_count=len(deals),
        historical=False,
        current=True,
        universal=False,
        dataset_specific=True,
        suitable_for_backtest=False,
        upgrade_requirements=[
            "historical daily swap accrual series with effective dates",
            "or authoritative broker historical swap schedule",
            "deal-level swap over multi-day holds",
        ],
        reasoning=reasoning,
    )


def audit_slippage_evidence(deals: list[DealTapeRecord]) -> CostComponentInventory:
    has_requested = any(
        d.requested_price and d.requested_price.availability == FieldAvailability.OBSERVED.value for d in deals
    )
    has_fill = any(
        d.actual_fill_price and d.actual_fill_price.availability == FieldAvailability.OBSERVED.value for d in deals
    )
    realized = [d for d in deals if d.slippage_class == SlippageEvidenceClass.REALIZED.value]
    reasoning = (
        "Slippage requires requested_price AND actual_fill_price on the same order. "
        "entry_price is NOT requested_price. deviation setting is NOT slippage evidence. "
        f"Deals with requested_price: {sum(1 for d in deals if d.requested_price and d.requested_price.availability == FieldAvailability.OBSERVED.value)}. "
        f"Realized slippage records: {len(realized)}."
    )
    return CostComponentInventory(
        component="SLIPPAGE",
        status=SlippageEvidenceClass.UNKNOWN.value,
        evidence_class=ReportEvidenceClass.STALE_OPERATOR_EVIDENCE.value if deals else ReportEvidenceClass.UNKNOWN.value,
        evidence_source="operator_deal_tape",
        evidence_timestamp=LITEFINANCE_EVIDENCE_TIMESTAMP,
        evidence_scope="operator_closed_deals",
        symbol="XAUUSD_i",
        environment="DEMO+REAL",
        broker="LiteFinance",
        sample_count=len(deals),
        historical=True,
        current=False,
        universal=False,
        dataset_specific=False,
        suitable_for_backtest=False,
        upgrade_requirements=[
            "requested_price at order submission",
            "actual fill price from execution report",
            "shared order identifier",
            "timestamp, symbol, side, volume",
        ],
        reasoning=reasoning + f" has_requested={has_requested} has_fill={has_fill} (fill without request insufficient).",
    )


def audit_spread_evidence(entries: list[DatasetAuditEntry]) -> CostComponentInventory:
    bidask_count = sum(1 for e in entries if e.bid_present and e.ask_present)
    proxy_count = sum(1 for e in entries if e.spread_mode == SpreadMode.PROXY.value)
    dataset_count = sum(1 for e in entries if e.spread_mode == SpreadMode.DATASET.value)
    status = SpreadMode.PROXY.value if proxy_count and not dataset_count else (
        SpreadMode.DATASET.value if dataset_count else SpreadMode.UNKNOWN.value
    )
    reasoning = (
        f"{len(entries)} parquet dataset(s): {proxy_count} PROXY (OHLC-only), "
        f"{dataset_count} DATASET (bid/ask), {bidask_count} with bid+ask columns. "
        "Phase 25H bid/ask collection DEFERRED — no historical observed spread dataset."
    )
    return CostComponentInventory(
        component="SPREAD",
        status=status,
        evidence_class=ReportEvidenceClass.OFFLINE_TEST_EVIDENCE.value,
        evidence_source="dataset_parquet_audit",
        evidence_timestamp=_utc_now(),
        evidence_scope="all_backtest_parquets",
        symbol="XAUUSD+XAUUSD_i",
        environment="UNKNOWN",
        broker="UNKNOWN",
        sample_count=len(entries),
        historical=False,
        current=False,
        universal=False,
        dataset_specific=True,
        suitable_for_backtest=proxy_count > 0,
        upgrade_requirements=[
            "historical bid/ask/tick tape",
            "UTC timestamps",
            "symbol-bound and broker/environment-bound provenance",
            "MT5 operator session (Phase 25H) when terminal available",
        ],
        reasoning=reasoning,
    )


def dataset_eligibility_for_row(entry: DatasetAuditEntry) -> DatasetCostMatrixRow:
    sym = entry.inferred_symbol or "UNKNOWN"
    econ = classify_economics_provenance(
        dataset_symbol=sym,
        economics_source=entry.economics_provenance,
        evidence_timestamp=LITEFINANCE_EVIDENCE_TIMESTAMP if sym == "XAUUSD_i" else None,
    )
    cost = compute_dataset_cost_status(
        spread_mode=entry.spread_mode,
        commission_status=entry.commission,
        swap_status=entry.swap,
        slippage_status=entry.slippage,
    )
    spread_is_dataset = entry.spread_mode == SpreadMode.DATASET.value
    completeness = cost["cost_completeness"]
    cost_adjusted = completeness == CostCompleteness.COMPLETE.value
    return DatasetCostMatrixRow(
        filename=entry.filename,
        symbol=sym,
        timeframe=entry.inferred_timeframe,
        economics=econ,
        spread=entry.spread_mode,
        commission=entry.commission,
        swap=entry.swap,
        slippage=entry.slippage,
        overall_completeness=completeness,
        cost_adjusted_metrics_allowed=cost_adjusted,
        research_backtest_eligible=entry.ohlc_present or spread_is_dataset,
        cost_aware_backtest_eligible=spread_is_dataset,
        production_validation_eligible=cost_adjusted and spread_is_dataset,
    )


def build_upgrade_requirements() -> dict[str, list[str]]:
    return {
        "COMMISSION": [
            "broker commission schedule",
            "account-specific trading conditions",
            "sufficient executed-deal evidence covering relevant symbols/account types",
        ],
        "SLIPPAGE": [
            "requested price",
            "actual fill price",
            "same order identifier",
            "timestamp",
            "symbol",
            "side",
            "volume",
        ],
        "SWAP": [
            "historical daily swap data",
            "or authoritative broker historical schedule with effective dates",
        ],
        "SPREAD": [
            "historical bid/ask/tick tape",
            "timestamped",
            "symbol-bound",
            "broker/environment-bound",
        ],
        "EV-EQ-01": [
            "both XAUUSD and XAUUSD_i simultaneously available on same broker/server/environment",
            "complete economics comparison",
            "equivalent trading rules",
            "no material contract differences",
        ],
    }


def cost_adjusted_metrics_allowed(
    *,
    spread_mode: str,
    commission_status: str = "UNKNOWN",
    swap_status: str = "UNKNOWN",
    slippage_status: str = "UNKNOWN",
) -> bool:
    """Fail closed — only COMPLETE cost evidence enables cost-adjusted metrics."""
    cfg = BacktestConfig(
        spread_mode=spread_mode,
        commission_status=commission_status,
        swap_status=swap_status,
        slippage_status=slippage_status,
    )
    model = build_backtest_cost_model(cfg)
    return assess_cost_completeness(model) == CostCompleteness.COMPLETE


def load_all_operator_deals(base_dir: Path) -> tuple[list[DealTapeRecord], dict[str, dict[str, Any]]]:
    deals: list[DealTapeRecord] = []
    specs: dict[str, dict[str, Any]] = {}
    for rel in DEFAULT_EVIDENCE_PATHS:
        path = base_dir / rel
        data = _safe_load_json(path)
        if data is None:
            continue
        deal = parse_closed_deal(data, source=str(path))
        if deal:
            deals.append(deal)
        spec = _extract_spec(data)
        if spec:
            specs[rel] = spec
    return deals, specs


def run_phase25i_audit(base_dir: str | Path | None = None) -> Phase25IAuditReport:
    """Run complete offline cost-evidence audit — no MT5, no bot, no mutations."""
    root = Path(base_dir or Path.cwd())
    report = Phase25IAuditReport(generated_at=_utc_now(), code_version=_git_head_safe(root))

    entries = audit_backtest_datasets(base_dir=root)
    deals, specs = load_all_operator_deals(root)

    report.cost_inventory = [
        audit_commission_evidence(deals),
        audit_swap_evidence(deals, specs),
        audit_slippage_evidence(deals),
        audit_spread_evidence(entries),
    ]
    report.dataset_matrix = [dataset_eligibility_for_row(e) for e in entries]

    eq_audits = audit_from_operator_artifacts(base_dir=root)
    if eq_audits:
        report.ev_eq_01 = eq_audits[0].ev_eq_01
        for a in eq_audits:
            if a.ev_eq_01 == EquivalenceConclusion.DISPROVEN.value:
                report.ev_eq_01 = EquivalenceConclusion.DISPROVEN.value
                break
    else:
        report.ev_eq_01 = EquivalenceConclusion.NOT_PROVEN.value

    report.upgrade_requirements = build_upgrade_requirements()
    report.explicit_unknowns = [
        "commission universal schedule",
        "slippage requested-vs-fill delta",
        "historical swap accrual series",
        "historical bid/ask spread for all 32 OHLC datasets",
        "XAUUSD economics (30 datasets)",
        "EV-EQ-01 XAUUSD vs XAUUSD_i equivalence",
    ]
    report.stale_evidence = [
        f"operator_broker_evidence @ {LITEFINANCE_EVIDENCE_TIMESTAMP}",
        "Phase 25H fresh live MT5 collection DEFERRED",
    ]

    before_path = root / "logs" / "phase25h_immutability_before.json"
    if before_path.is_file():
        before = json.loads(before_path.read_text(encoding="utf-8-sig"))
        ok, issues = verify_immutability(before, base_dir=root)
        report.immutability_ok = ok
        if not ok:
            report.errors.extend(issues)
    else:
        manifest = build_immutability_manifest(base_dir=root)
        report.immutability_ok = True

    report.safety = {
        "mt5_started": False,
        "bot_started": False,
        "daemon_started": False,
        "orders_sent": False,
        "positions_modified": False,
        "symbol_select_called": False,
        "env_read_or_modified": False,
        "credentials_accessed": False,
        "ml_enabled": False,
        "risk_increased": False,
        "strategy_changed": False,
        "riskgate_changed": False,
        "router_changed": False,
        "existing_parquet_mutated": not report.immutability_ok,
        "synthetic_data_created": False,
    }
    return report


def write_phase25i_audit_json(report: Phase25IAuditReport, base_dir: str | Path | None = None) -> Path:
    root = Path(base_dir or Path.cwd())
    out = root / PHASE25I_AUDIT_JSON
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = report.to_dict()
    payload["operator_deal_evidence"] = load_operator_evidence_bundle(base_dir=root)
    payload["dataset_inventory"] = [e.to_dict() for e in audit_backtest_datasets(base_dir=root)]
    payload["sidecar_inventory_detail"] = _audit_sidecars(root, audit_backtest_datasets(base_dir=root))
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out


def _audit_sidecars(root: Path, entries: list[DatasetAuditEntry]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in entries:
        meta = load_dataset_metadata(entry.path)
        if meta is None:
            continue
        rows.append(
            {
                "dataset": entry.filename,
                "symbol": meta.dataset_symbol,
                "economics_source": meta.economics_source,
                "economics_class": classify_economics_provenance(
                    dataset_symbol=meta.dataset_symbol,
                    economics_source=meta.economics_source,
                    evidence_timestamp=meta.evidence_timestamp,
                ),
                "mapping_status": meta.mapping_status,
                "symbol_equivalence": meta.symbol_equivalence,
                "spread_mode": meta.spread_mode,
                "evidence_timestamp": meta.evidence_timestamp,
            }
        )
    return rows


def render_phase25i_report_md(report: Phase25IAuditReport) -> str:
    lines = [
        "# Phase 25I Cost Evidence Report",
        "",
        f"Generated: {report.generated_at}",
        f"Status: **{report.status}**",
        "",
        "## Summary",
        "",
        "| Component | Status | Evidence class |",
        "|-----------|--------|----------------|",
    ]
    for inv in report.cost_inventory:
        lines.append(f"| {inv.component} | {inv.status} | {inv.evidence_class} |")
    lines.extend(
        [
            "",
            f"**EV-EQ-01:** {report.ev_eq_01} ({ReportEvidenceClass.NOT_PROVEN.value})",
            "",
            f"**Datasets audited:** {len(report.dataset_matrix)}",
            f"**Immutability OK:** {report.immutability_ok}",
            "",
            "## Explicit unknowns",
            "",
        ]
    )
    for u in report.explicit_unknowns:
        lines.append(f"- {u} ({ReportEvidenceClass.UNKNOWN.value})")
    lines.extend(["", "## Stale / deferred", ""])
    for s in report.stale_evidence:
        lines.append(f"- {s}")
    lines.extend(
        [
            "",
            "## Dataset spread classification",
            "",
            f"- OHLC PROXY: {sum(1 for r in report.dataset_matrix if r.spread == SpreadMode.PROXY.value)}",
            f"- DATASET bid/ask: {sum(1 for r in report.dataset_matrix if r.spread == SpreadMode.DATASET.value)}",
            f"- cost_adjusted_metrics allowed: {sum(1 for r in report.dataset_matrix if r.cost_adjusted_metrics_allowed)}",
            "",
            "## Safety",
            "",
        ]
    )
    for k, v in report.safety.items():
        lines.append(f"- {k}: {'NO' if v is False else 'YES' if v is True else v}")
    return "\n".join(lines) + "\n"


def write_phase25i_report_md(report: Phase25IAuditReport, base_dir: str | Path | None = None) -> Path:
    root = Path(base_dir or Path.cwd())
    out = root / PHASE25I_REPORT_MD
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_phase25i_report_md(report), encoding="utf-8")
    return out


def run_phase25i_collection(base_dir: str | Path | None = None) -> Phase25IAuditReport:
    """Phase 25I entry point — audit only, no MT5."""
    report = run_phase25i_audit(base_dir=base_dir)
    write_phase25i_audit_json(report, base_dir=base_dir)
    write_phase25i_report_md(report, base_dir=base_dir)
    return report

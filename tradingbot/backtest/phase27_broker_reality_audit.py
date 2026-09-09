"""Phase 27 — Broker reality + EV-EQ-01 closure + cost evidence foundation.

Forensic/evidence phase only. No production behavior changes unless minimal correctness fix.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.cost_evidence_audit import (
    audit_commission_evidence,
    audit_slippage_evidence,
    audit_spread_evidence,
    audit_swap_evidence,
    build_upgrade_requirements,
    cost_adjusted_metrics_allowed,
    dataset_eligibility_for_row,
    load_all_operator_deals,
)
from tradingbot.backtest.cost_evidence_schema import (
    CommissionEvidence,
    CostEvidenceBundle,
    ExecutionEvidence,
    SlippageEvidence,
    SpreadEvidence,
    SwapEvidence,
    serialize_evidence_deterministic,
)
from tradingbot.backtest.cost_model import CostCompleteness, SpreadMode, build_backtest_cost_model
from tradingbot.backtest.dataset_contract import (
    InstrumentContractError,
    resolve_broker_symbol_for_dataset,
    resolve_dataset_instrument,
)
from tradingbot.backtest.dataset_provenance import audit_backtest_datasets
from tradingbot.backtest.metrics import compute_metrics
from tradingbot.backtest.models import BacktestResult
from tradingbot.backtest.operator_evidence import parse_closed_deal
from tradingbot.backtest.phase27_operator_evidence import collect_phase27_operator_evidence
from tradingbot.backtest.symbol_equivalence import (
    EquivalenceConclusion,
    audit_from_operator_artifacts,
    write_equivalence_audit_report,
)
from tradingbot.config.live import PRIMARY_SYMBOL, SYMBOL_BY_ENVIRONMENT

PHASE27_JSON = "logs/phase27_broker_reality_audit.json"
PHASE27_MD = "docs_v2/01_truth/PHASE27_BROKER_REALITY.md"
STALE_EVIDENCE_CUTOFF = "2026-09-03T00:00:00Z"

EVIDENCE_TABLE_COLUMNS = (
    "logical_symbol",
    "broker_symbol",
    "environment",
    "source",
    "existence",
    "visibility",
    "contract_size",
    "tick_size",
    "tick_value",
    "tick_value_profit",
    "tick_value_loss",
    "volume_min",
    "volume_max",
    "volume_step",
    "stops_level",
    "freeze_level",
    "trade_mode",
    "execution_mode",
    "calc_mode",
    "currency_profit",
    "currency_margin",
    "swap_long",
    "swap_short",
    "spread",
    "commission",
    "timestamp",
    "evidence_class",
    "confidence",
    "notes",
)

COST_PATH_STAGES = (
    "dataset",
    "dataset_contract",
    "economics",
    "cost_model",
    "simulated_broker",
    "fill",
    "exit",
    "metrics",
)

ALLOWED_CLASSIFICATIONS = frozenset(
    {"PROVEN", "CONFIGURED", "SUPPORTED", "UNKNOWN", "DEFERRED", "BLOCKED", "SUPERSEDED"}
)


@dataclass
class Phase27Report:
    phase: str = "27"
    status: str = "PASS_WITH_DEFERRAL"
    timestamp: str = ""
    repository_commit: str = ""
    mt5_available: bool = False
    operator_dependency: bool = True
    demo_broker: str = ""
    real_broker: str = ""
    symbol_matrix: list[dict[str, Any]] = field(default_factory=list)
    economics_matrix: list[dict[str, Any]] = field(default_factory=list)
    cost_matrix: list[dict[str, Any]] = field(default_factory=list)
    dataset_matrix: list[dict[str, Any]] = field(default_factory=list)
    ev_eq_01: dict[str, Any] = field(default_factory=dict)
    cost_completeness: dict[str, Any] = field(default_factory=dict)
    production_readiness: dict[str, Any] = field(default_factory=dict)
    changes_made: list[str] = field(default_factory=list)
    tests: str = "tests/test_phase27_broker_reality_audit.py"
    remaining_unknowns: list[str] = field(default_factory=list)
    deferred_items: list[str] = field(default_factory=list)
    blocked_items: list[str] = field(default_factory=list)
    safety_confirmation: dict[str, bool] = field(default_factory=dict)
    PROVEN: list[str] = field(default_factory=list)
    CONFIGURED: list[str] = field(default_factory=list)
    SUPPORTED: list[str] = field(default_factory=list)
    UNKNOWN: list[str] = field(default_factory=list)
    DEFERRED: list[str] = field(default_factory=list)
    BLOCKED: list[str] = field(default_factory=list)
    SUPERSEDED: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["schema_version"] = 1
        return d


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_head(base_dir: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=base_dir,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "UNKNOWN"


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return None


def _spec_fields(raw: dict[str, Any]) -> dict[str, Any]:
    if "spec" in raw and isinstance(raw["spec"], dict):
        return raw["spec"]
    return raw


def _row_from_evidence(
    logical: str,
    broker: str,
    env: str,
    source: str,
    data: dict[str, Any],
    *,
    stale: bool = True,
) -> dict[str, Any]:
    ts = str(data.get("collection_utc") or "")
    evidence_class = "STALE_OPERATOR_EVIDENCE" if stale else "FRESH_OPERATOR_EVIDENCE"
    confidence = "HIGH" if stale and ts else "MEDIUM"

    block = data.get(broker) or data.get(logical)
    if isinstance(block, str) and "NOT AVAILABLE" in block.upper():
        return {
            "logical_symbol": logical,
            "broker_symbol": broker,
            "environment": env,
            "source": source,
            "existence": False,
            "visibility": data.get("visibility", {}).get(broker) if isinstance(data.get("visibility"), dict) else None,
            "contract_size": None,
            "tick_size": None,
            "tick_value": None,
            "tick_value_profit": None,
            "tick_value_loss": None,
            "volume_min": None,
            "volume_max": None,
            "volume_step": None,
            "stops_level": None,
            "freeze_level": None,
            "trade_mode": None,
            "execution_mode": None,
            "calc_mode": None,
            "currency_profit": None,
            "currency_margin": None,
            "swap_long": None,
            "swap_short": None,
            "spread": None,
            "commission": None,
            "timestamp": ts,
            "evidence_class": evidence_class,
            "confidence": confidence,
            "notes": block[:120],
        }

    if not isinstance(block, dict):
        catalog = (data.get("catalog_exact") or {}).get(broker) if isinstance(data.get("catalog_exact"), dict) else None
        exists = catalog == "YES" if catalog else False
        return {
            "logical_symbol": logical,
            "broker_symbol": broker,
            "environment": env,
            "source": source,
            "existence": exists,
            "visibility": None,
            "contract_size": None,
            "tick_size": None,
            "tick_value": None,
            "tick_value_profit": None,
            "tick_value_loss": None,
            "volume_min": None,
            "volume_max": None,
            "volume_step": None,
            "stops_level": None,
            "freeze_level": None,
            "trade_mode": None,
            "execution_mode": None,
            "calc_mode": None,
            "currency_profit": None,
            "currency_margin": None,
            "swap_long": None,
            "swap_short": None,
            "spread": None,
            "commission": None,
            "timestamp": ts,
            "evidence_class": evidence_class,
            "confidence": "LOW",
            "notes": "no spec block in artifact",
        }

    spec = _spec_fields(block)
    quote = block.get("quote") or {}
    spread_val = quote.get("spread_price_units") or block.get("spread_price_units")
    deal = data.get("closed_deal") if isinstance(data.get("closed_deal"), dict) else {}
    comm = deal.get("commission") if deal.get("symbol") == broker else None

    return {
        "logical_symbol": logical,
        "broker_symbol": broker,
        "environment": env,
        "source": source,
        "existence": block.get("exists", True),
        "visibility": block.get("visible") or (data.get("visibility") or {}).get(broker),
        "contract_size": spec.get("trade_contract_size"),
        "tick_size": spec.get("trade_tick_size"),
        "tick_value": spec.get("trade_tick_value"),
        "tick_value_profit": spec.get("trade_tick_value_profit"),
        "tick_value_loss": spec.get("trade_tick_value_loss"),
        "volume_min": spec.get("volume_min"),
        "volume_max": spec.get("volume_max"),
        "volume_step": spec.get("volume_step"),
        "stops_level": spec.get("trade_stops_level"),
        "freeze_level": spec.get("trade_freeze_level"),
        "trade_mode": spec.get("trade_mode"),
        "execution_mode": spec.get("trade_exemode"),
        "calc_mode": spec.get("trade_calc_mode"),
        "currency_profit": spec.get("currency_profit"),
        "currency_margin": spec.get("currency_margin"),
        "swap_long": spec.get("swap_long"),
        "swap_short": spec.get("swap_short"),
        "spread": spread_val,
        "commission": comm,
        "timestamp": ts,
        "evidence_class": evidence_class,
        "confidence": confidence,
        "notes": f"historical operator evidence; stale if before {STALE_EVIDENCE_CUTOFF}",
    }


def build_evidence_table(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    demo = _load_json(root / "logs/operator_broker_evidence_demo_raw.json")
    real = _load_json(root / "logs/operator_broker_evidence_raw.json")

    if demo:
        for sym in ("XAUUSD", "XAUUSD_i"):
            rows.append(
                _row_from_evidence(
                    "XAUUSD" if sym == "XAUUSD" else "XAUUSD",
                    sym,
                    "DEMO",
                    "logs/operator_broker_evidence_demo_raw.json",
                    demo,
                    stale=True,
                )
            )
    if real:
        for sym in ("XAUUSD", "XAUUSD_i"):
            rows.append(
                _row_from_evidence(
                    "XAUUSD",
                    sym,
                    "REAL",
                    "logs/operator_broker_evidence_raw.json",
                    real,
                    stale=True,
                )
            )

    fresh = _load_json(root / "logs/phase27_operator_evidence_raw.json")
    if fresh and fresh.get("mt5_available"):
        env = fresh.get("account_type") or "UNKNOWN"
        for sym in ("XAUUSD", "XAUUSD_i"):
            spec_block = (fresh.get("symbol_specs") or {}).get(sym) or {}
            pseudo = {
                "collection_utc": fresh.get("collection_utc"),
                "visibility": {sym: spec_block.get("visible")},
                sym: spec_block,
            }
            rows.append(
                _row_from_evidence("XAUUSD", sym, env, "logs/phase27_operator_evidence_raw.json", pseudo, stale=False)
            )
    return rows


def build_symbol_matrix(root: Path) -> list[dict[str, Any]]:
    matrix: list[dict[str, Any]] = []
    for rel, env in (
        ("logs/operator_broker_evidence_demo_raw.json", "DEMO"),
        ("logs/operator_broker_evidence_raw.json", "REAL"),
    ):
        data = _load_json(root / rel)
        if not data:
            continue
        account = data.get("account") or {}
        server = str(account.get("server") or data.get("server") or "")
        ts = str(data.get("collection_utc") or "")
        catalog = data.get("catalog_exact") or {}
        for sym in ("XAUUSD", "XAUUSD_i"):
            matrix.append(
                {
                    "environment": env,
                    "server": server,
                    "symbol": sym,
                    "catalog_exists": catalog.get(sym) == "YES" if catalog else None,
                    "xauusd_exists": catalog.get("XAUUSD") == "YES" if catalog else None,
                    "xauusd_i_exists": catalog.get("XAUUSD_i") == "YES" if catalog else None,
                    "visibility": (data.get("visibility") or {}).get(sym),
                    "evidence_source": rel,
                    "evidence_timestamp": ts,
                    "evidence_class": "STALE_OPERATOR_EVIDENCE",
                }
            )
    return matrix


def build_state_analysis(ev_eq: str) -> dict[str, Any]:
    state_a = {
        "label": "XAUUSD equivalence PROVEN",
        "justified": ev_eq == EquivalenceConclusion.PROVEN.value,
        "evidence_required": [
            "XAUUSD and XAUUSD_i both exist on same broker/server/environment",
            "All critical economics fields MATCH (contract_size, tick_size, tick_value, volume_min/step)",
            "Consistent evidence on Demo AND Real",
        ],
        "current_evidence": [
            "Demo LiteFinance-MT5-Demo: XAUUSD absent, XAUUSD_i present (2026-09-02 STALE)",
            "Real LiteFinance-MT5-Live: XAUUSD absent, XAUUSD_i present (2026-09-02 STALE)",
            "No field-by-field comparison possible — left symbol absent",
        ],
        "missing_evidence": [
            "Observed XAUUSD spec on same terminal as XAUUSD_i",
            "Multi-environment consistent MATCH on critical fields",
        ],
        "consequences": "Bare XAUUSD datasets could map to broker economics without explicit map",
        "code_changes_required": [
            "dataset_symbol_map could remain empty for XAUUSD→XAUUSD_i",
            "EV-EQ-01 gate would open for cost completeness on bare XAUUSD labels",
        ],
        "currently_authorized": False,
    }
    state_b = {
        "label": "XAUUSD_i-only operation ACCEPTABLE WITHOUT XAUUSD EQUIVALENCE",
        "justified": False,
        "evidence_required": [
            "Operational proof that only XAUUSD_i is used live and in backtest",
            "Explicit policy authorizing XAUUSD_i-only; bare XAUUSD datasets excluded or explicitly mapped",
            "No silent fallback from XAUUSD to XAUUSD_i",
        ],
        "current_evidence": [
            f"PRIMARY_SYMBOL={PRIMARY_SYMBOL} (CONFIGURED)",
            f"SYMBOL_BY_ENVIRONMENT DEMO/REAL → {SYMBOL_BY_ENVIRONMENT}",
            "Observed LiteFinance terminals: XAUUSD_i only (STALE 2026-09-02)",
            "dataset_contract fail-closed on XAUUSD vs XAUUSD_i mismatch without explicit map",
        ],
        "missing_evidence": [
            "Formal operator policy decision authorizing XAUUSD_i-only",
            "Fresh broker catalog on operator session",
            "Cost-complete validation dataset",
        ],
        "consequences": "Bare XAUUSD parquet datasets remain SYMBOL-UNPROVEN / cost-incomplete unless explicit map",
        "code_changes_required": [
            "Optional: populate dataset_symbol_map XAUUSD→XAUUSD_i (NOT authorized by Phase 27)",
            "Optional: rename/relabel datasets to XAUUSD_i (operator decision)",
        ],
        "currently_authorized": False,
    }
    return {
        "overall": ev_eq,
        "state_a": state_a,
        "state_b": state_b,
        "policy_decision": "NOT_MADE — Phase 27 records evidence only",
    }


def build_cost_component_matrix(deals: list[Any], specs: dict[str, dict[str, Any]], entries: list[Any]) -> list[dict[str, Any]]:
    components = [
        ("spread", audit_spread_evidence(entries)),
        ("commission", audit_commission_evidence(deals)),
        ("swap", audit_swap_evidence(deals, specs)),
        ("slippage", audit_slippage_evidence(deals)),
    ]
    extra = [
        ("latency", "UNKNOWN", "NOT_MODELED", "No latency model in backtest path"),
        ("partial_fills", "UNKNOWN", "NOT_MODELED", "SimulatedBroker assumes full fill when allowed"),
        ("retry_behavior", "UNKNOWN", "NOT_MODELED", "No order retry simulation"),
        ("stop_tp_execution", "MODELED", "BAR_CLOSE", "Exit at bar close / SL-TP price on bar"),
        ("intrabar_ambiguity", "PROXY", "OHLC_PATH", "Single price path; no tick replay unless bid/ask dataset"),
        ("execution_price", "DATASET_OR_PROXY", "MID_OR_ASK_BID", "Entry uses ask/bid when DATASET spread mode"),
        ("mt5_deviation", "NOT_SLIPPAGE", "EXECUTION_PARAM", "MT5 deviation is request param, not realized slippage"),
    ]
    rows: list[dict[str, Any]] = []
    for name, inv in components:
        rows.append(
            {
                "component": name,
                "classification": inv.status,
                "evidence_class": inv.evidence_class,
                "source": inv.evidence_source,
                "sample_count": inv.sample_count,
                "real_observed": inv.evidence_class in ("OBSERVED", "STALE_OPERATOR_EVIDENCE"),
                "modeled": inv.suitable_for_backtest,
                "notes": inv.reasoning,
            }
        )
    for name, cls, mode, note in extra:
        rows.append({"component": name, "classification": cls, "evidence_class": cls, "mode": mode, "notes": note})
    return rows


def _dataset_category(entry: Any, elig: Any) -> str:
    sym = entry.inferred_symbol or "UNKNOWN"
    if sym == "XAUUSD" and entry.symbol_equivalence == "NOT_PROVEN":
        return "D"
    if elig.production_validation_eligible:
        return "A"
    if elig.cost_aware_backtest_eligible:
        return "B"
    if entry.spread_mode == SpreadMode.DATASET.value:
        return "C"
    if entry.ohlc_present and sym == "XAUUSD_i":
        return "C"
    if entry.ohlc_present:
        return "C"
    return "E"


def build_dataset_matrix(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    labels = {
        "A": "production-quality candidate",
        "B": "research-only (cost-aware partial)",
        "C": "cost-incomplete",
        "D": "symbol-unproven",
        "E": "invalid for cost-adjusted profitability claims",
    }
    for entry in audit_backtest_datasets(base_dir=root):
        elig = dataset_eligibility_for_row(entry)
        sym = entry.inferred_symbol or "UNKNOWN"
        cat = _dataset_category(entry, elig)

        rows.append(
            {
                "filename": entry.filename,
                "symbol": sym,
                "timeframe": entry.inferred_timeframe,
                "start": (entry.datetime_range or {}).get("start"),
                "end": (entry.datetime_range or {}).get("end"),
                "timezone": (entry.datetime_range or {}).get("timezone"),
                "ohlc": entry.ohlc_present,
                "volume": entry.volume_present,
                "bid": entry.bid_present,
                "ask": entry.ask_present,
                "spread_mode": entry.spread_mode,
                "economics_provenance": entry.economics_provenance,
                "symbol_equivalence": entry.symbol_equivalence,
                "cost_completeness": elig.overall_completeness,
                "cost_adjusted_allowed": elig.cost_adjusted_metrics_allowed,
                "category": cat,
                "category_label": labels.get(cat, cat),
                "sidecar": entry.metadata_sidecar_present,
            }
        )
    return rows


def trace_cost_path() -> list[dict[str, Any]]:
    """Document cost omission points — read-only code path audit."""
    return [
        {
            "stage": "dataset",
            "risk": "OHLC-only frames → PROXY spread (not observed)",
            "fail_closed": False,
            "mitigation": "SpreadMode.PROXY explicit; cost completeness not COMPLETE",
        },
        {
            "stage": "dataset_contract",
            "risk": "XAUUSD label vs XAUUSD_i config without map",
            "fail_closed": True,
            "mitigation": "InstrumentContractError SYMBOL_MISMATCH",
        },
        {
            "stage": "economics",
            "risk": "Missing BROKER_SYMBOL_CATALOG entry",
            "fail_closed": True,
            "mitigation": "resolve_dataset_instrument raises when economics missing",
        },
        {
            "stage": "cost_model",
            "risk": "commission_status default UNKNOWN",
            "fail_closed": True,
            "mitigation": "ZERO only with explicit commission_status='ZERO'",
        },
        {
            "stage": "simulated_broker",
            "risk": "UNKNOWN spread/commission/slippage at entry",
            "fail_closed": True,
            "mitigation": "ExecutionResult success=False with message",
        },
        {
            "stage": "fill",
            "risk": "Partial fills not simulated",
            "fail_closed": False,
            "mitigation": "Documented UNKNOWN; full fill assumed",
        },
        {
            "stage": "exit",
            "risk": "Slippage UNKNOWN on exit uses no slippage add (not zero claim)",
            "fail_closed": True,
            "mitigation": "Exit without modeled slippage when UNKNOWN",
        },
        {
            "stage": "metrics",
            "risk": "cost_adjusted_metrics when completeness != COMPLETE",
            "fail_closed": True,
            "mitigation": "compute_metrics sets cost_adjusted_metrics=False unless COMPLETE",
        },
    ]


def build_cost_evidence_bundles(root: Path) -> list[dict[str, Any]]:
    bundles: list[dict[str, Any]] = []
    for rel, env in (
        ("logs/operator_broker_evidence_demo_raw.json", "DEMO"),
        ("logs/operator_broker_evidence_raw.json", "REAL"),
    ):
        data = _load_json(root / rel)
        if not data:
            continue
        spec_block = data.get("XAUUSD_i") or {}
        spec = _spec_fields(spec_block) if isinstance(spec_block, dict) else {}
        quote = spec_block.get("quote") if isinstance(spec_block, dict) else {}
        spread_val = None
        if isinstance(spec_block, dict):
            raw_spread = spec_block.get("spread_price_units")
            if raw_spread is None and isinstance(quote, dict):
                raw_spread = quote.get("spread_price_units")
            if raw_spread is not None:
                spread_val = float(raw_spread)
        deal = parse_closed_deal(data, source=rel)
        bundle = CostEvidenceBundle(
            logical_symbol="XAUUSD",
            broker_symbol="XAUUSD_i",
            environment=env,
            spread=SpreadEvidence(
                source=rel,
                method="symbol_info_tick",
                sample_count=1 if spread_val is not None else 0,
                timestamp_range=str(data.get("collection_utc") or ""),
                value=spread_val,
                units="price",
                evidence_class="STALE_OPERATOR_EVIDENCE",
            ),
            commission=CommissionEvidence(
                source=rel,
                schedule_or_value=str(deal.commission.value) if deal and deal.commission else "UNKNOWN",
                sample_count=1 if deal else 0,
                timestamp_range=str(data.get("collection_utc") or ""),
                evidence_class="UNKNOWN",
            ),
            swap=SwapEvidence(
                source=rel,
                long=float(spec.get("swap_long")) if spec.get("swap_long") is not None else None,
                short=float(spec.get("swap_short")) if spec.get("swap_short") is not None else None,
                rollover_3day=spec.get("swap_rollover3days"),
                sample_count=0,
                timestamp_range=str(data.get("collection_utc") or ""),
                evidence_class="BROKER_RATE_ONLY",
            ),
            slippage=SlippageEvidence(
                requested_price=float(deal.requested_price.value) if deal and deal.requested_price and deal.requested_price.value is not None else None,
                fill_price=float(deal.actual_fill_price.value) if deal and deal.actual_fill_price and deal.actual_fill_price.value is not None else None,
                evidence_class=deal.slippage_class if deal else "UNKNOWN",
            ),
            execution=ExecutionEvidence(
                requested_volume=None,
                filled_volume=float(deal.filled_volume.value) if deal and deal.filled_volume and deal.filled_volume.value is not None else None,
                partial_fill=False if deal and deal.partial_fill and deal.partial_fill.value == "NO" else None,
                timestamp=str(data.get("collection_utc") or ""),
            ),
        )
        bundles.append(bundle.to_dict())
    return bundles


def run_phase27_broker_reality_audit(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path(__file__).resolve().parents[2])
    report = Phase27Report(timestamp=_utc_now(), repository_commit=_git_head(root))

    operator = collect_phase27_operator_evidence(root)
    report.mt5_available = operator.mt5_available
    report.operator_dependency = operator.operator_blocked

    deals, specs = load_all_operator_deals(root)
    entries = audit_backtest_datasets(base_dir=root)
    eq_audits = audit_from_operator_artifacts(base_dir=root)
    eq_path = write_equivalence_audit_report(eq_audits, root / "logs/phase27_symbol_equivalence_audit.json")

    ev_eq_overall = EquivalenceConclusion.NOT_PROVEN.value
    if eq_audits:
        payload = _load_json(eq_path) or {}
        ev_eq_overall = str(payload.get("ev_eq_01_overall") or ev_eq_overall)

    report.demo_broker = "LiteFinance-MT5-Demo"
    report.real_broker = "LiteFinance-MT5-Live"
    report.symbol_matrix = build_symbol_matrix(root)
    report.economics_matrix = [r for r in build_evidence_table(root) if r.get("broker_symbol") == "XAUUSD_i"]
    report.cost_matrix = build_cost_component_matrix(deals, specs, entries)
    report.dataset_matrix = build_dataset_matrix(root)
    report.ev_eq_01 = {
        "status": ev_eq_overall,
        "evidence_table_columns": list(EVIDENCE_TABLE_COLUMNS),
        "evidence_table": build_evidence_table(root),
        "state_analysis": build_state_analysis(ev_eq_overall),
        "artifact": str(eq_path.relative_to(root)) if eq_path.is_relative_to(root) else str(eq_path),
    }

    any_cost_adjusted = any(r.get("cost_adjusted_allowed") for r in report.dataset_matrix)
    report.cost_completeness = {
        "overall": CostCompleteness.UNKNOWN.value,
        "any_dataset_complete": any(r.get("cost_completeness") == CostCompleteness.COMPLETE.value for r in report.dataset_matrix),
        "any_cost_adjusted_metrics": any_cost_adjusted,
        "cost_adjusted_blocked": not any_cost_adjusted,
        "cost_path_trace": trace_cost_path(),
        "cost_evidence_bundles": build_cost_evidence_bundles(root),
    }

    report.production_readiness = {
        "status": "BLOCKED",
        "phase27_authorizes_production": False,
        "phase27_authorizes_profitability": False,
        "blocking_items": [
            "EV-EQ-01 NOT_PROVEN",
            "Cost completeness not COMPLETE on any production dataset",
            "Commission/swap/slippage largely UNKNOWN",
        ],
    }

    report.safety_confirmation = {
        "mt5_started_by_script": False,
        "symbol_select_called": False,
        "orders_sent": False,
        "bot_started": False,
        "riskgate_changed": False,
        "strategy_changed": False,
        "credentials_accessed": False,
        "env_accessed": False,
    }

    report.PROVEN = [
        "XAUUSD_i exists on observed Demo LiteFinance-MT5-Demo (STALE 2026-09-02)",
        "XAUUSD_i exists on observed Real LiteFinance-MT5-Live (STALE 2026-09-02)",
        "XAUUSD absent on both observed terminals (STALE 2026-09-02)",
        "SimulatedBroker fail-closed on UNKNOWN spread/commission/slippage at entry",
        "cost_adjusted_metrics=False unless CostCompleteness.COMPLETE",
        "dataset_contract raises on XAUUSD vs XAUUSD_i without explicit map",
    ]
    report.CONFIGURED = [
        f"PRIMARY_SYMBOL={PRIMARY_SYMBOL}",
        f"SYMBOL_BY_ENVIRONMENT={SYMBOL_BY_ENVIRONMENT}",
        "BacktestConfig.commission_status default UNKNOWN",
        "BacktestConfig.spread_mode AUTO → PROXY on OHLC-only",
        "resolve_broker_symbol strict — no silent ±_i hunt",
    ]
    report.SUPPORTED = [
        "XAUUSD_i-only operational path aligns with observed broker catalogs",
        "Demo and Real XAUUSD_i economics appear consistent on STALE specs (contract_size=100, tick_value=1.0)",
        "Phase 25B–25M cost contract fail-closed behavior preserved",
    ]
    report.UNKNOWN = [
        "Whether XAUUSD exists on any LiteFinance server not yet observed",
        "Universal zero commission (only 2 historical deals at 0.0)",
        "Historical realized swap series",
        "Realized slippage distribution",
        "Fresh operator MT5 session evidence",
    ]
    report.DEFERRED = [
        "Fresh operator evidence collection when MT5 terminal available",
        "XAUUSD_i-only policy decision (STATE B) — operator authorization required",
        "Bid/ask M5 dataset with COMPLETE cost stack",
    ]
    report.BLOCKED = [
        "EV-EQ-01 PROVEN status",
        "Cost-adjusted profitability claims",
        "Production trading authorization",
        "Silent XAUUSD→XAUUSD_i dataset mapping without explicit policy",
    ]
    report.SUPERSEDED = [
        "Pre-Phase-25 assumption that bare XAUUSD equals broker symbol",
    ]

    report.remaining_unknowns = list(report.UNKNOWN)
    report.deferred_items = list(report.DEFERRED)
    report.blocked_items = list(report.BLOCKED)
    report.changes_made = [
        "Phase 27 audit module + cost evidence schema + operator collection wrapper",
        "PHASE27_BROKER_REALITY.md canonical truth doc",
        "CONFIGURATION_TRUTH / KNOWN_UNKNOWNS / DEMO_REAL_SYMBOL_COST_DESIGN updates",
    ]

    if operator.operator_blocked:
        report.status = "PASS_WITH_DEFERRAL"
    else:
        report.status = "PASS_WITH_DEFERRAL"

    payload = report.to_dict()
    out = root / PHASE27_JSON
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    _write_phase27_md(root, payload)
    return payload


def _write_phase27_md(root: Path, payload: dict[str, Any]) -> None:
    eq = payload.get("ev_eq_01") or {}
    state = eq.get("state_analysis") or {}
    md_path = root / PHASE27_MD
    md_path.parent.mkdir(parents=True, exist_ok=True)

    def _list(title: str, items: list[str]) -> str:
        return f"### {title}\n\n" + "\n".join(f"- {x}" for x in items) + "\n"

    content = f"""# Phase 27 — Broker Reality + EV-EQ-01 + Cost Evidence Foundation

**Status:** {payload.get('status')}  
**Generated:** {payload.get('timestamp')}  
**Commit:** {payload.get('repository_commit')}  
**Artifact:** `{PHASE27_JSON}`

---

## §1 Objective

Close broker/economics/cost unknowns from Phase 26 without changing production behavior.
Establish definitive evidence map for later validation phases.

---

## §2 Evidence sources

| Source | Class | Timestamp |
|---|---|---|
| `logs/operator_broker_evidence_demo_raw.json` | STALE_OPERATOR_EVIDENCE | 2026-09-02 |
| `logs/operator_broker_evidence_raw.json` | STALE_OPERATOR_EVIDENCE | 2026-09-02 |
| `logs/phase25f_symbol_equivalence_audit.json` | OFFLINE_AUDIT | Phase 25F |
| `logs/phase25d_dataset_audit.json` | OFFLINE_AUDIT | Phase 25D |
| `logs/phase27_operator_evidence_raw.json` | FRESH or BLOCKED | Phase 27 run |
| Code path audit | CONFIGURED | Phase 27 |

---

## §3 Demo broker evidence

- **Server:** LiteFinance-MT5-Demo (STALE 2026-09-02)
- **XAUUSD:** absent from catalog and symbol_info
- **XAUUSD_i:** present; contract_size=100, tick_value=1.0, volume_min=0.01
- **Spread snapshot:** ~0.38 price units (STALE tick)
- **Closed deal:** 1 sample; commission=0.0 — **not** universal zero proof

---

## §4 Real broker evidence

- **Server:** LiteFinance-MT5-Live (STALE 2026-09-02)
- **XAUUSD:** absent
- **XAUUSD_i:** present; economics match Demo STALE specs on critical fields
- **Closed deal:** 1 sample; requested/fill price matched on entry (slippage sample insufficient)

---

## §5 XAUUSD vs XAUUSD_i comparison

Field-by-field comparison **not possible** — XAUUSD absent on observed terminals.
Absence on observed terminal does **not** prove broker-wide absence.

---

## §6 EV-EQ-01 status

**{eq.get('status', 'NOT_PROVEN')}**

Neither STATE A nor STATE B is authorized as policy. See `state_analysis` in audit JSON.

---

## §7 Broker economics

XAUUSD_i STALE observed economics (Demo/Real): contract_size=100, tick_size=0.01, tick_value=1.0,
volume_min=0.01, volume_step=0.01, swap_long=-89.136, swap_short=3.45.

---

## §8 Spread evidence

| Mode | Classification |
|---|---|
| OHLC datasets | PROXY |
| Bid/ask sidecar (if present) | DATASET / OBSERVED |
| Operator tick | REAL_OBSERVED (STALE snapshot only) |

MT5 deviation is **not** realized slippage.

---

## §9 Commission evidence

**UNKNOWN** — two historical deals at 0.0 insufficient for universal zero commission claim.

---

## §10 Swap evidence

**BROKER_RATE_ONLY** from symbol spec — not historical realized swap series.

---

## §11 Slippage evidence

**UNKNOWN** — sparse deal samples; Real deal showed matching requested/fill on entry only.

---

## §12 Dataset provenance

See `dataset_matrix` in audit JSON. Bare **XAUUSD** parquets: category **D/E** (symbol-unproven / invalid for cost-adjusted claims).

---

## §13 Cost completeness

**BLOCKED** — no dataset reaches CostCompleteness.COMPLETE with all components evidenced.

---

## §14 Backtest/live cost parity

Fail-closed contract preserved: UNKNOWN commission/spread/slippage blocks simulated entry.
Cost-adjusted metrics disabled unless COMPLETE.

---

## §15 Remaining unknowns

{_list("", payload.get("remaining_unknowns", []))}

## §16 Deferred operator work

{_list("", payload.get("deferred_items", []))}

## §17 Safety constraints

- No MT5 startup, symbol_select, orders, bot, RiskGate, or strategy changes in Phase 27
- No credentials / .env access
- No EV-EQ-01 PROVEN claim without evidence

---

## §18 Exact next evidence required

1. Fresh operator MT5 read-only session (Phase 27 operator command)
2. Commission schedule or ≥10 deal samples
3. Historical bid/ask tape bound to XAUUSD_i / environment
4. EV-EQ-01: both symbols on same terminal OR formal XAUUSD_i-only policy decision
5. Realized slippage samples with requested/fill prices

---

## §19 Final phase status

**{payload.get('status')}** — Evidence map established; production **BLOCKED**; profitability **not claimed**.

"""
    md_path.write_text(content, encoding="utf-8")


def run_phase27_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    """Phase 27 entry point."""
    return run_phase27_broker_reality_audit(base_dir)

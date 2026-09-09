"""Phase 26P — Canonical truth consolidation & Phase-26 closure audit."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.adapters.risk_gate import detect_account_tier
from tradingbot.backtest.config import BacktestConfig

PHASE26P_JSON = "logs/phase26p_closure_audit.json"
PHASE26_CLOSURE_MD = "docs_v2/01_truth/PHASE26_CLOSURE.md"

ALLOWED_TRUTH_STATUSES = frozenset(
    {"PROVEN", "CONFIGURED", "SUPPORTED", "UNKNOWN", "DEFERRED", "BLOCKED", "SUPERSEDED"}
)

MANDATORY_TRUTH_AREAS = (
    "CURRENT STRATEGY",
    "SIGNAL GENERATION",
    "SESSION FILTER",
    "HTF ALIGNMENT",
    "ATR FILTER",
    "META-LABELER",
    "RISK GATE",
    "LOT SIZING",
    "BROKER ECONOMICS",
    "SYMBOL MAPPING",
    "BACKTEST/LIVE PARITY",
    "SPREAD MODEL",
    "COMMISSION MODEL",
    "SWAP MODEL",
    "SLIPPAGE MODEL",
    "EXECUTION MODEL",
    "FORMING-BAR MODEL",
    "POSITION MANAGEMENT",
    "DATASET PROVENANCE",
    "COST COMPLETENESS",
    "EV-EQ-01",
    "ZERO-TRADE ATTRIBUTION",
    "PROFITABILITY",
    "WALK-FORWARD VALIDATION",
    "MONTE CARLO VALIDATION",
    "PARAMETER STABILITY",
    "CROSS-SYMBOL VALIDATION",
    "PRODUCTION READINESS",
)

PHASE_DEFINITIONS: list[dict[str, Any]] = [
    {
        "phase": "26A",
        "label": "Validation readiness",
        "status": "PASS_WITH_DEFERRAL",
        "purpose": "Strategy/backtest defensibility inventory without strategy changes",
        "evidence_type": "static code + artifact audit",
        "artifacts": [
            "logs/phase26_validation_readiness_report.json",
            "logs/phase26_performance_claims_audit.json",
            "logs/phase26_backtest_live_parity.json",
            "logs/phase26_validation_matrix.json",
        ],
        "tests": "tests/test_phase26_validation_audit.py",
        "runtime": "artifact-only",
        "production_changes": False,
        "key_conclusion": "Logic-only backtests valid under PROXY; cost-adjusted validation BLOCKED",
        "deferred": ["Cost-adjusted performance claims", "EV-EQ-01"],
    },
    {
        "phase": "26B",
        "label": "Controlled validation",
        "status": "PASS_WITH_DEFERRAL",
        "purpose": "Frozen-config BacktestEngine run on XAUUSD_M5_183d tail",
        "evidence_type": "backtest engine (RESEARCH_ONLY)",
        "artifacts": [
            "logs/phase26b_final_validation_report.json",
            "logs/phase26b_recovery_report.json",
            "logs/phase26b_baseline_results.json",
        ],
        "tests": "tests/test_phase26b_controlled_validation.py",
        "runtime": "backtest executed (26B scope)",
        "production_changes": False,
        "key_conclusion": "0 trades on 2500-bar tail; robustness D — LOGICALLY WEAK",
        "deferred": ["Cost-adjusted expectancy", "EV-EQ-01"],
    },
    {
        "phase": "26C",
        "label": "Zero-signal audit",
        "status": "PASS_WITH_DEFERRAL",
        "purpose": "Lightweight gate trace; funnel bottlenecks without backtest rerun",
        "evidence_type": "artifact + gate trace",
        "artifacts": ["logs/phase26c_zero_signal_audit.json"],
        "tests": "tests/test_phase26c_zero_signal_audit.py",
        "runtime": "lightweight",
        "production_changes": False,
        "key_conclusion": "F — MULTIPLE BOTTLENECKS (reclaim filter + journal disconnect)",
        "deferred": [],
    },
    {
        "phase": "26D",
        "label": "Kernel signal trace",
        "status": "PASS_WITH_DEFERRAL",
        "purpose": "19-candidate pipeline trace; RiskGate gate attribution",
        "evidence_type": "per-candidate trace",
        "artifacts": ["logs/phase26d_kernel_signal_trace.json"],
        "tests": "tests/test_phase26d_kernel_signal_trace.py",
        "runtime": "lightweight",
        "production_changes": False,
        "key_conclusion": "19 candidates reach RiskGate; 0 ALLOWED; meta/ATR/lot sizing reject",
        "deferred": [],
    },
    {
        "phase": "26E",
        "label": "RiskGate rejection audit",
        "status": "PASS_WITH_DEFERRAL",
        "purpose": "19-candidate RiskGate read-only gate trace",
        "evidence_type": "read-only trace",
        "artifacts": ["logs/phase26e_riskgate_audit.json"],
        "tests": "tests/test_phase26e_riskgate_audit.py",
        "runtime": "lightweight",
        "production_changes": False,
        "key_conclusion": "F — MULTIPLE INDEPENDENT CAUSES; economics lookup issue noted pre-26F",
        "deferred": [],
    },
    {
        "phase": "26F",
        "label": "RiskGate alias fix audit",
        "status": "PASS_WITH_DEFERRAL",
        "purpose": "Verify resolve_broker_symbol before economics lookup",
        "evidence_type": "19-candidate replay",
        "artifacts": ["logs/phase26f_riskgate_correctness.json"],
        "tests": "tests/test_phase26f_riskgate_correctness.py",
        "runtime": "lightweight",
        "production_changes": "26F code fix (alias); closure records fix only",
        "key_conclusion": "Alias fix correct; 0/19 ALLOWED unchanged",
        "deferred": [],
    },
    {
        "phase": "26G",
        "label": "RiskGate counterfactual",
        "status": "PASS_WITH_DEFERRAL",
        "purpose": "Gate attribution counterfactuals on 19 candidates",
        "evidence_type": "audit-only counterfactual",
        "artifacts": ["logs/phase26g_riskgate_counterfactual.json"],
        "tests": "tests/test_phase26g_riskgate_counterfactual.py",
        "runtime": "lightweight",
        "production_changes": False,
        "key_conclusion": "Baseline LOT=3 META=10 ATR=6 ALLOWED=0; sequential stack",
        "deferred": [],
    },
    {
        "phase": "26H",
        "label": "Counterfactual consistency",
        "status": "PASS_WITH_DEFERRAL",
        "purpose": "Validate 26G accounting; sequential not conjunction",
        "evidence_type": "artifact cross-check",
        "artifacts": ["logs/phase26h_counterfactual_consistency.json"],
        "tests": "tests/test_phase26h_counterfactual_consistency.py",
        "runtime": "lightweight",
        "production_changes": False,
        "key_conclusion": "26G sequential accounting consistent",
        "deferred": [],
    },
    {
        "phase": "26I",
        "label": "Full-tail attribution",
        "status": "PASS_WITH_DEFERRAL",
        "purpose": "2500→19→0 funnel without backtest rerun",
        "evidence_type": "artifact-only funnel",
        "artifacts": [
            "logs/phase26i_full_tail_attribution.json",
            "logs/phase26i_candidate_set_consistency.json",
        ],
        "tests": "tests/test_phase26i_full_tail_attribution.py",
        "runtime": "~3.9s (8 tests)",
        "production_changes": False,
        "key_conclusion": "Upstream session/sweep/reclaim dominant; 19→0 RiskGate stack",
        "deferred": [],
    },
    {
        "phase": "26J",
        "label": "Decision-path reconciliation",
        "status": "PASS_WITH_DEFERRAL",
        "purpose": "Reconcile 26B vs 26C–26I without full engine walk",
        "evidence_type": "artifact cross-check + signal scan",
        "artifacts": [
            "logs/phase26j_decision_path_reconciliation.json",
            "logs/phase26j_candidate_reconciliation.json",
        ],
        "tests": "tests/test_phase26j_decision_path_reconciliation.py",
        "runtime": "~94s (10 tests)",
        "production_changes": False,
        "key_conclusion": "B — STRONGLY SUPPORTED BUT NOT FORMALLY PROVEN",
        "deferred": ["Full simultaneous engine walk (→26K)"],
    },
    {
        "phase": "26K",
        "label": "Full-engine reconciliation",
        "status": "DEFERRED — TOO EXPENSIVE",
        "purpose": "Close 26J B-gap with simultaneous 2500-bar kernel walk",
        "evidence_type": "runtime probe only",
        "artifacts": ["logs/phase26k_full_engine_reconciliation.json"],
        "tests": "tests/test_phase26k_full_engine_reconciliation.py",
        "runtime": "~45 min estimated; NOT executed",
        "production_changes": False,
        "key_conclusion": "Full walk deferred; 26J B-level remains authoritative",
        "deferred": ["Full kernel bar walk (~45 min)"],
    },
    {
        "phase": "26L",
        "label": "RiskGate policy audit",
        "status": "PASS_WITH_DEFERRAL",
        "purpose": "Static lot/META/ATR policy coherence",
        "evidence_type": "static / artifact-only",
        "artifacts": ["logs/phase26l_riskgate_policy_audit.json"],
        "tests": "tests/test_phase26l_riskgate_policy_audit.py",
        "runtime": "~4.6s (10 tests)",
        "production_changes": False,
        "key_conclusion": "B — COHERENT BUT EXTREMELY RESTRICTIVE",
        "deferred": ["Operator policy review (→26M)"],
    },
    {
        "phase": "26M",
        "label": "Operator risk-budget review",
        "status": "PASS_WITH_DEFERRAL",
        "purpose": "Document/policy audit for $1000/0.5%/0.01-lot intent",
        "evidence_type": "documentation audit",
        "artifacts": ["logs/phase26m_operator_risk_budget_audit.json"],
        "tests": "tests/test_phase26m_operator_risk_budget_audit.py",
        "runtime": "~4.7s (10 tests)",
        "production_changes": False,
        "key_conclusion": "0.5% risk documented; account-size intent UNKNOWN; no policy change",
        "deferred": ["Operator account-size declaration"],
    },
    {
        "phase": "26N",
        "label": "Documentation contradiction cleanup",
        "status": "PASS",
        "purpose": "Correct stale docs_v2 pre-25B M1/1% claims",
        "evidence_type": "documentation audit",
        "artifacts": ["logs/phase26n_documentation_contradiction_cleanup.json"],
        "tests": "tests/test_phase26n_documentation_contradiction_cleanup.py",
        "runtime": "~3.9s (10 tests)",
        "production_changes": False,
        "key_conclusion": "docs_v2 parity claims corrected; historical preserved",
        "deferred": [],
    },
    {
        "phase": "26O",
        "label": "Legacy docs truth sweep",
        "status": "PASS",
        "purpose": "Legacy docs/ stale-claim sweep",
        "evidence_type": "documentation audit",
        "artifacts": ["logs/phase26o_legacy_docs_truth_sweep.json"],
        "tests": "tests/test_phase26o_legacy_docs_truth_sweep.py",
        "runtime": "~4.4s (10 tests)",
        "production_changes": False,
        "key_conclusion": "No legacy current-state 1%/M1 claims; clarifications added",
        "deferred": ["architecture_atlas generated assets"],
    },
]

TRUTH_MATRIX: list[dict[str, str]] = [
    {"area": "CURRENT STRATEGY", "status": "CONFIGURED", "evidence": "CONFIGURATION_TRUTH.md; phase26_validation_readiness_report.json", "limitation": "PA gold_ny_sweep M5 only on default live path"},
    {"area": "SIGNAL GENERATION", "status": "SUPPORTED", "evidence": "phase26j_decision_path_reconciliation.json (19-candidate scan)", "limitation": "B-level; not full-engine proven for all bars"},
    {"area": "SESSION FILTER", "status": "CONFIGURED", "evidence": "pa_symbol_tf_presets.py; CONFIGURATION_TRUTH NY 15–16", "limitation": "Operator session bypass flags UNKNOWN effective"},
    {"area": "HTF ALIGNMENT", "status": "CONFIGURED", "evidence": "M5 preset REQUIRE_HTF_ALIGNMENT_M5=False", "limitation": "H4 fetched but not gating M5 entries"},
    {"area": "ATR FILTER", "status": "PROVEN", "evidence": "phase26g baseline ATR=6 rejects; risk_gate check_market_filters", "limitation": "Scope: 19 traced candidates on fixed tail"},
    {"area": "META-LABELER", "status": "PROVEN", "evidence": "phase26g baseline META=10 rejects; meta_labeler ready", "limitation": "Scope: 19 traced candidates; not live drift proven"},
    {"area": "RISK GATE", "status": "PROVEN", "evidence": "risk_gate.py final authority; 26D–26H traces", "limitation": "Policy appropriateness not validated"},
    {"area": "LOT SIZING", "status": "CONFIGURED", "evidence": "broker_economics floor-down; 26L/26F VOLUME_BELOW_MIN", "limitation": "Live tick_value parity UNKNOWN"},
    {"area": "BROKER ECONOMICS", "status": "CONFIGURED", "evidence": "OFFLINE_INSTRUMENT_CATALOG XAUUSD_i; Phase 25 operator evidence", "limitation": "Live broker catalog not continuously verified"},
    {"area": "SYMBOL MAPPING", "status": "CONFIGURED", "evidence": "resolve_broker_symbol; PRIMARY_SYMBOL=XAUUSD_i", "limitation": "XAUUSD↔XAUUSD_i economic equivalence NOT_PROVEN"},
    {"area": "BACKTEST/LIVE PARITY", "status": "SUPPORTED", "evidence": "Phase 25B/26N: M5 + 0.005 aligned", "limitation": "Costs, execution, symbol economics gaps remain"},
    {"area": "SPREAD MODEL", "status": "CONFIGURED", "evidence": "BacktestConfig spread_mode AUTO/PROXY; 26B PROXY", "limitation": "Cost-adjusted metrics BLOCKED without class-A tape"},
    {"area": "COMMISSION MODEL", "status": "UNKNOWN", "evidence": "BacktestConfig.commission_status UNKNOWN", "limitation": "No operator commission schedule collected"},
    {"area": "SWAP MODEL", "status": "UNKNOWN", "evidence": "BacktestConfig.swap_status UNKNOWN", "limitation": "Not modeled on default live path"},
    {"area": "SLIPPAGE MODEL", "status": "CONFIGURED", "evidence": "BacktestConfig.slippage_status MODELED_PROXY", "limitation": "Not validated against live fills"},
    {"area": "EXECUTION MODEL", "status": "CONFIGURED", "evidence": "Backtest sim fill vs Mt5ExecutionAdapter", "limitation": "Bar-close sim ≠ live tick execution"},
    {"area": "FORMING-BAR MODEL", "status": "PROVEN", "evidence": "phase26j forming-bar reconciliation PASS", "limitation": "Scope: 2500-bar tail only"},
    {"area": "POSITION MANAGEMENT", "status": "CONFIGURED", "evidence": "position_logic shared; Mt5PositionManager", "limitation": "Live exit PnL sync NOT PROVEN in audits"},
    {"area": "DATASET PROVENANCE", "status": "SUPPORTED", "evidence": "Phase 25D sidecars; 26B dataset metadata", "limitation": "Parquet label XAUUSD vs instrument XAUUSD_i map required"},
    {"area": "COST COMPLETENESS", "status": "BLOCKED", "evidence": "phase26_validation_readiness; 26A cost-adjusted BLOCKED", "limitation": "Cannot authorize cost-adjusted production metrics"},
    {"area": "EV-EQ-01", "status": "BLOCKED", "evidence": "phase26g/26b/26m ev_eq_01 NOT_PROVEN", "limitation": "Demo/Real XAUUSD_i economics equivalence unproven"},
    {"area": "ZERO-TRADE ATTRIBUTION", "status": "SUPPORTED", "evidence": "phase26j final_zero_trade_claim B-level", "limitation": "Not A-level full-engine proof (26K deferred)"},
    {"area": "PROFITABILITY", "status": "UNKNOWN", "evidence": "26B 0 trades; 26A blocks cost-adjusted claims", "limitation": "Not assessed on observed tail"},
    {"area": "WALK-FORWARD VALIDATION", "status": "DEFERRED", "evidence": "phase26b_walkforward_results.json; D — LOGICALLY WEAK", "limitation": "Not defensible for production authorization"},
    {"area": "MONTE CARLO VALIDATION", "status": "UNKNOWN", "evidence": "Not part of Phase 26 forensic scope", "limitation": "No Phase 26 artifact establishes MC validity"},
    {"area": "PARAMETER STABILITY", "status": "UNKNOWN", "evidence": "phase26b_parameter_sensitivity.json exists", "limitation": "Not elevated to production evidence"},
    {"area": "CROSS-SYMBOL VALIDATION", "status": "UNKNOWN", "evidence": "Gold-only scope", "limitation": "Not applicable / not tested"},
    {"area": "PRODUCTION READINESS", "status": "BLOCKED", "evidence": "PRODUCTION_READINESS_AUDIT.md BLOCKED; Phase 26 series", "limitation": "Phase 26 does not approve real-money trading"},
]


@dataclass
class Phase26PClosure:
    status: str = "PASS_WITH_DEFERRAL"
    generated_at: str = ""
    production_behavior_changed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": 1, "phase": "26P", **asdict(self)}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _artifact_exists(root: Path, rel: str) -> bool:
    return (root / rel).is_file()


def _load_json_field(root: Path, rel: str, *keys: str, default: Any = None) -> Any:
    path = root / rel
    if not path.is_file():
        return default
    data = json.loads(path.read_text(encoding="utf-8"))
    cur: Any = data
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k, default)
    return cur


def _build_phase_matrix(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in PHASE_DEFINITIONS:
        artifacts = spec["artifacts"]
        missing = [a for a in artifacts if not _artifact_exists(root, a)]
        rows.append(
            {
                **spec,
                "artifacts_present": all(not missing for _ in [0]) if not missing else False,
                "missing_artifacts": missing,
            }
        )
    return rows


def _closure_markdown(root: Path, payload: dict[str, Any]) -> str:
    phase_rows = payload["phase_matrix"]
    truth_rows = payload["truth_matrix"]

    def _table_phase() -> str:
        lines = [
            "| Phase | Status | Purpose | Evidence | Key Result | Deferred |",
            "|---|---|---|---|---|---|",
        ]
        for r in phase_rows:
            deferred = "; ".join(r.get("deferred") or []) or "—"
            arts = ", ".join(f"`{a}`" for a in r["artifacts"][:2])
            if len(r["artifacts"]) > 2:
                arts += ", …"
            lines.append(
                f"| {r['phase']} | {r['status']} | {r['purpose']} | {arts} | {r['key_conclusion']} | {deferred} |"
            )
        return "\n".join(lines)

    def _table_truth() -> str:
        lines = [
            "| Area | Status | Evidence | Important limitation |",
            "|---|---|---|---|",
        ]
        for r in truth_rows:
            lines.append(f"| {r['area']} | {r['status']} | {r['evidence']} | {r['limitation']} |")
        return "\n".join(lines)

    proven = payload["proven"]
    configured = payload["configured"]
    unknown = payload["unknown"]
    deferred = payload["deferred"]
    blocked = payload["blocked"]

    return f"""# Phase 26 Closure

**Status:** {payload['status']}  
**Generated:** {payload['generated_at']}  
**Epistemic-Role:** Phase-26 decision-memory layer. Does not replace `CONFIGURATION_TRUTH.md` or code.  
**Method:** Consolidates Phase 26A–26O artifacts; no experiments rerun.

---

## 1. Closure Status

**Overall:** {payload['status']}

Phase 26 forensic validation is **closed at B-level zero-trade attribution** with **production readiness BLOCKED**, **EV-EQ-01 NOT_PROVEN**, and **no authorized policy changes**.

---

## 2. Phase Matrix

{_table_phase()}

---

## 3. Current Truth Matrix

{_table_truth()}

---

## 4. Proven

{chr(10).join(f'- {x}' for x in proven)}

---

## 5. Configured but Not Validated

{chr(10).join(f'- {x}' for x in configured)}

---

## 6. Unknown

{chr(10).join(f'- {x}' for x in unknown)}

---

## 7. Deferred / Blocked

**Deferred**

{chr(10).join(f'- {x}' for x in deferred)}

**Blocked**

{chr(10).join(f'- {x}' for x in blocked)}

---

## 8. Zero-Trade Closure

| Topic | Status |
|---|---|
| 19-candidate set | **PROVEN** identical across 26D/26G/26I/26J artifacts |
| RiskGate rejections (19) | **PROVEN** baseline LOT=3, META=10, ATR=6, ALLOWED=0 (26G/26H) |
| 2500-tail funnel | **SUPPORTED** artifact funnel 2500→19→0 (26I); upstream session/sweep/reclaim dominant |
| Full end-to-end engine walk | **DEFERRED** (26K ~45 min; not executed) |
| Overall evidence level | **SUPPORTED — B-level** (`phase26j` final_zero_trade_claim) |

Do **not** claim the entire 2500-bar engine run mathematically proved zero trades unless a complete run artifact exists.

---

## 9. Broker/Cost Closure

| Item | Status |
|---|---|
| Symbol equivalence XAUUSD ↔ XAUUSD_i | **NOT_PROVEN** (EV-EQ-01) |
| EV-EQ-01 | **NOT_PROVEN** |
| Spread | **CONFIGURED** PROXY/DATASET; class-A tape **BLOCKED** |
| Commission | **UNKNOWN** |
| Swap | **UNKNOWN** |
| Slippage | **CONFIGURED** MODELED_PROXY only |
| Cost completeness | **BLOCKED** for production authorization |

Observed LiteFinance terminals showed `XAUUSD_i`; bare `XAUUSD` absence from catalogs does not prove broker-wide behavior.

---

## 10. Production Readiness

**BLOCKED** — Phase 26 establishes forensic coherence, not real-money authorization.

Authoritative reference: `docs_v2/01_truth/PRODUCTION_READINESS_AUDIT.md` (historical BLOCKED verdict preserved).

---

## 11. Next Required Evidence

{chr(10).join(f'- {x}' for x in payload['next_required_evidence'])}

---

## Authoritative document map

| Topic | Owner doc |
|---|---|
| Configuration truth | `docs_v2/01_truth/CONFIGURATION_TRUTH.md` |
| Architecture | `docs_v2/02_architecture/SYSTEM_ARCHITECTURE.md` |
| Strategy | `docs_v2/04_strategy/PRICE_ACTION_LIVE_SPEC.md` |
| Risk / RiskGate | `docs_v2/05_risk/RISKGATE_SPEC.md`, `RISK.md` |
| Broker / economics | `docs_v2/01_truth/OPERATOR_BROKER_EVIDENCE_COLLECTION.md` |
| Unknowns | `docs_v2/01_truth/KNOWN_ISSUES.md` |
| Production readiness | `docs_v2/01_truth/PRODUCTION_READINESS_AUDIT.md` |

Closure artifact: `logs/phase26p_closure_audit.json`
"""


def run_phase26p_closure_audit(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path(__file__).resolve().parents[2])
    cfg = BacktestConfig()
    phase_matrix = _build_phase_matrix(root)

    missing_any = any(not row["artifacts_present"] for row in phase_matrix if row["phase"] != "26P")
    j_claim = _load_json_field(root, "logs/phase26j_decision_path_reconciliation.json", "final_zero_trade_claim")
    ev_eq = _load_json_field(root, "logs/phase26g_riskgate_counterfactual.json", "ev_eq_01", default="NOT_PROVEN")

    proven = [
        "RiskGate is final entry authority on kernel path (code + 26D traces)",
        "19-candidate cursor set identical across 26D/26G/26I/26J",
        "RiskGate baseline on 19 candidates: LOT=3, META=10, ATR=6, ALLOWED=0 (26G/26H)",
        "Forming-bar closed-path alignment on traced tail (26J PASS)",
        "26F alias economics lookup fix correctness (0/19 ALLOWED unchanged)",
    ]
    configured = [
        f"BacktestConfig.risk_per_trade={cfg.risk_per_trade} (0.5%)",
        f"BacktestConfig.timeframe={cfg.timeframe}",
        f"$1000 equity tier={detect_account_tier(1000.0).value} (not MICRO)",
        "PA M5 gold_ny_sweep active on default live path",
        "Floor-down lot normalization fail-closed below volume_min (26L)",
        "XAUUSD → XAUUSD_i symbol resolution (equivalence not proven)",
    ]
    supported = [
        "Zero-trade attribution B — STRONGLY SUPPORTED BUT NOT FORMALLY PROVEN (26J)",
        "2500-bar tail funnel 2500→19→0 artifact-only (26I)",
        "RiskGate stack coherent but extremely restrictive (26L)",
        "Backtest/live M5 + 0.005 parity post Phase 25B (26N)",
    ]
    unknown = [
        "Operator intended live/production account balance (26M)",
        "Minimum viable account size at 0.5% risk with PA stops",
        "Live broker tick_value / contract_size continuous verification",
        "Profitability on observed 2500-bar tail",
        "Parameter stability / Monte Carlo production validity",
    ]
    deferred_items = [
        "Phase 26K full simultaneous kernel walk (~45 min estimated)",
        "Operator account-size / risk-budget policy declaration",
        "Phase 25H–25M MT5 broker evidence when operator session unavailable",
        "Walk-forward as production-grade evidence (26B D — LOGICALLY WEAK)",
    ]
    blocked_items = [
        "EV-EQ-01 symbol economic equivalence",
        "Cost-adjusted validation and cost completeness",
        "Production readiness / real-money authorization",
        "Cost-aware metric eligibility",
    ]
    superseded = [
        "docs_v2 pre-25B BacktestConfig M1 default (26N superseded markers)",
        "docs_v2 pre-25B backtest risk 1% claim (26N superseded markers)",
        "Phase 26L colloquial micro-account wording for $1000 (26N → SMALL tier)",
    ]

    status = "PASS_WITH_DEFERRAL" if missing_any or j_claim else "PASS"
    if missing_any:
        status = "PASS_WITH_DEFERRAL"

    report = Phase26PClosure(
        status=status,
        generated_at=datetime.now(timezone.utc).isoformat(),
    ).to_dict()

    report.update(
        {
            "objective": "Consolidate Phase 26A–26O into a single decision-memory closure state.",
            "phase_matrix": phase_matrix,
            "truth_matrix": TRUTH_MATRIX,
            "proven": proven,
            "configured": configured,
            "supported": supported,
            "unknown": unknown,
            "deferred": deferred_items,
            "blocked": blocked_items,
            "superseded": superseded,
            "zero_trade": {
                "candidate_set_19": "PROVEN — identical cursors across 26D/26G/26I/26J",
                "riskgate_rejections": "PROVEN — LOT=3 META=10 ATR=6 ALLOWED=0 on 19 candidates (26G/26H)",
                "full_tail_status": "SUPPORTED — 2500→19→0 artifact funnel (26I); not full-engine walk",
                "evidence_level": str(j_claim or "B — STRONGLY SUPPORTED BUT NOT FORMALLY PROVEN"),
                "full_engine_walk": "DEFERRED — 26K not executed (~45 min)",
            },
            "broker_cost": {
                "symbol_equivalence": "NOT_PROVEN — XAUUSD ↔ XAUUSD_i",
                "ev_eq_01": str(ev_eq),
                "spread": "CONFIGURED PROXY/DATASET; class-A tape BLOCKED",
                "commission": "UNKNOWN",
                "swap": "UNKNOWN",
                "slippage": "CONFIGURED MODELED_PROXY",
                "cost_completeness": "BLOCKED",
            },
            "production_readiness": {
                "status": "BLOCKED",
                "blocking_items": blocked_items,
                "phase26_authorizes_production": False,
            },
            "operator_dependency": [
                "Operator .env effective values",
                "MT5 attach for broker catalog refresh (Phase 25H–25M)",
                "Account-size / risk-budget policy declaration",
                "Class-A round-trip cost tape",
            ],
            "next_required_evidence": [
                "EV-EQ-01 resolution or explicit written acceptance of XAUUSD_i-only economics",
                "Class-A spread/commission/swap evidence for cost-adjusted metrics",
                "Optional: Phase 26K full-engine walk if maintenance budget allows",
                "Operator declaration of intended account balance (if policy review continues)",
            ],
            "code_truth_snapshot": {
                "BacktestConfig.risk_per_trade": cfg.risk_per_trade,
                "BacktestConfig.timeframe": cfg.timeframe,
                "equity_1000_tier": detect_account_tier(1000.0).value,
                "PRIMARY_SYMBOL": "XAUUSD_i",
            },
            "authoritative_documents": {
                "configuration": "docs_v2/01_truth/CONFIGURATION_TRUTH.md",
                "architecture": "docs_v2/02_architecture/SYSTEM_ARCHITECTURE.md",
                "strategy": "docs_v2/04_strategy/PRICE_ACTION_LIVE_SPEC.md",
                "risk": "docs_v2/05_risk/RISKGATE_SPEC.md",
                "broker_economics": "docs_v2/01_truth/OPERATOR_BROKER_EVIDENCE_COLLECTION.md",
                "unknowns": "docs_v2/01_truth/KNOWN_ISSUES.md",
                "production_readiness": "docs_v2/01_truth/PRODUCTION_READINESS_AUDIT.md",
                "phase26_closure": PHASE26_CLOSURE_MD,
            },
            "safety": {
                "MT5_CONNECTED": False,
                "BOT_STARTED": False,
                "ORDERS_SENT": False,
                "PRODUCTION_CODE_CHANGED": False,
                "CONFIGURATION_CHANGED": False,
                "BACKTEST_EXECUTED": False,
                "FULL_ENGINE_EXECUTED": False,
                "ENV_ACCESSED": False,
                "CREDENTIALS_ACCESSED": False,
            },
            "production_behavior_changed": False,
            "final_decision": status,
        }
    )

    _write_json(root / PHASE26P_JSON, report)
    (root / PHASE26_CLOSURE_MD).write_text(_closure_markdown(root, report), encoding="utf-8")
    return report


def run_phase26p_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    return run_phase26p_closure_audit(base_dir)

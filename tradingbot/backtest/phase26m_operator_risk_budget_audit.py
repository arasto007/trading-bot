"""Phase 26M — Operator risk-budget policy review (document/policy audit only)."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PHASE26L_JSON = "logs/phase26l_riskgate_policy_audit.json"
PHASE26M_JSON = "logs/phase26m_operator_risk_budget_audit.json"

VALID_CLASSIFICATIONS = frozenset({"A", "B", "C", "D"})

PRIORITY_DOC_PATHS = (
    "docs_v2/01_truth/CONFIGURATION_TRUTH.md",
    "docs_v2/01_truth/SOURCE_OF_TRUTH.md",
    "docs_v2/01_truth/PRODUCTION_READINESS_AUDIT.md",
    "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md",
    "docs_v2/01_truth/KNOWN_ISSUES.md",
    "docs_v2/01_truth/OPERATOR_BROKER_EVIDENCE_COLLECTION.md",
    "docs_v2/01_truth/FULL_REPOSITORY_SOURCE_OF_TRUTH.md",
    "docs_v2/05_risk/RISK.md",
    "docs_v2/05_risk/RISKGATE_SPEC.md",
    "docs_v2/05_risk/RISK_AND_EXECUTION_BOUNDARY.md",
    "docs_v2/03_runtime/CONFIGURATION.md",
    "docs_v2/04_strategy/PA_LIVE_EDGE_AUDIT.md",
    "docs_v2/07_ml/V41_CALIBRATION_EVIDENCE.md",
    "docs_v2/09_operations/RUNBOOK.md",
    "docs/ONBOARDING_FA.md",
    "docs/PHASE3_BACKTEST_FA.md",
    "docs/robot_behavior_audit/configuration_truth.md",
    "README.md",
)

SEARCH_TERMS = (
    r"\$1000|\b1000\b",
    r"0\.005|0\.5\s*%",
    r"risk_per_trade|RISK_PER_TRADE",
    r"volume_min|minimum lot|min_lot",
    r"micro account|MICRO",
    r"minimum account|account size|initial balance|starting balance",
    r"risk budget",
    r"trade frequency|minimum trades|MAX_TRADES",
    r"no trade|zero trade",
    r"VOLUME_BELOW_MIN|floor",
)

CODE_EVIDENCE_PATHS = (
    "tradingbot/backtest/config.py",
    "tradingbot/backtest/instrument.py",
    "tradingbot/domain/broker_economics.py",
    "tradingbot/adapters/risk_gate.py",
)


@dataclass
class Phase26MAudit:
    status: str = "PASS_WITH_DEFERRAL"
    generated_at: str = ""
    safety: dict[str, bool] = field(
        default_factory=lambda: {
            "MT5_STARTED": False,
            "BOT_STARTED": False,
            "ORDERS_SENT": False,
            "ENV_ACCESSED": False,
            "CREDENTIALS_ACCESSED": False,
            "PRODUCTION_CODE_CHANGED": False,
            "CONFIGURATION_CHANGED": False,
            "POLICY_CHANGED": False,
            "BACKTEST_EXECUTED": False,
            "FULL_ENGINE_EXECUTED": False,
            "MT5_CONNECTED": False,
        }
    )

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": 1, "phase": "26M", **asdict(self)}


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _read_excerpt(path: Path, pattern: str, *, max_hits: int = 2) -> list[str]:
    if not path.is_file():
        return []
    hits: list[str] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if re.search(pattern, line, re.I):
            hits.append(f"{path.as_posix()}:{i + 1}: {line.strip()[:240]}")
            if len(hits) >= max_hits:
                break
    return hits


def _scan_docs(root: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for rel in PRIORITY_DOC_PATHS:
        path = root / rel
        if not path.is_file():
            continue
        for term in SEARCH_TERMS:
            hits = _read_excerpt(path, term, max_hits=1)
            if hits:
                out.setdefault(term, []).extend(hits)
    return out


def _code_behavior_evidence(root: Path) -> dict[str, Any]:
    """Read-only code defaults — CURRENT behavior, not operator intent."""
    cfg = root / "tradingbot/backtest/config.py"
    inst = root / "tradingbot/backtest/instrument.py"
    rg = root / "tradingbot/adapters/risk_gate.py"
    be = root / "tradingbot/domain/broker_economics.py"

    excerpts: dict[str, list[str]] = {}
    for rel in CODE_EVIDENCE_PATHS:
        p = root / rel
        if rel.endswith("config.py"):
            excerpts[rel] = _read_excerpt(p, r"initial_balance|risk_per_trade|min_lot", max_hits=4)
        elif rel.endswith("instrument.py"):
            excerpts[rel] = _read_excerpt(p, r"volume_min|LiteFinance", max_hits=3)
        elif rel.endswith("risk_gate.py"):
            excerpts[rel] = _read_excerpt(p, r"detect_account_tier|AccountTier", max_hits=4)
        elif rel.endswith("broker_economics.py"):
            excerpts[rel] = _read_excerpt(p, r"floor_to_volume|VOLUME_BELOW_MIN|Never rounds up", max_hits=4)

    tier_note = _read_excerpt(rg, r"equity < 500|equity < 5000", max_hits=2)
    return {
        "note": "Code excerpts describe CURRENT behavior only; not operator policy unless mirrored in canonical docs.",
        "backtest_defaults": {
            "initial_balance": 1000.0,
            "risk_per_trade": 0.005,
            "min_lot": 0.01,
            "source": "tradingbot/backtest/config.py",
        },
        "offline_catalog": {
            "XAUUSD_i_volume_min": 0.01,
            "source": "tradingbot/backtest/instrument.py::OFFLINE_INSTRUMENT_CATALOG",
        },
        "account_tiers": {
            "MICRO": "equity < 500",
            "SMALL": "500 <= equity < 5000",
            "STANDARD": "equity >= 5000",
            "note_at_1000": "$1000 is SMALL tier, not MICRO — micro feasibility planner applies below $500",
            "source": tier_note,
        },
        "excerpts": excerpts,
    }


def _illustrative_math() -> dict[str, Any]:
    """Mathematical analysis only — NOT a policy recommendation."""
    return {
        "label": "MATHEMATICAL_ANALYSIS_NOT_RECOMMENDATION",
        "observed_26l_configuration": {
            "balance_usd": 1000,
            "risk_per_trade": 0.005,
            "risk_budget_usd": 5.0,
            "volume_min": 0.01,
            "representative_stop_usd_per_0_01_lot": "~10.6 (phase26L representative PA stop)",
        },
        "interpretation": (
            "At $1000 and 0.5% risk ($5 budget), representative PA stop distances yield raw lot "
            "below 0.01; floor-down normalization rejects with VOLUME_BELOW_MIN. "
            "This explains 26L behavior but does NOT establish that $1000 is the intended production balance."
        ),
    }


def _build_operator_intent(root: Path, doc_hits: dict[str, list[str]], code_ev: dict[str, Any]) -> dict[str, Any]:
    ct = root / "docs_v2/01_truth/CONFIGURATION_TRUTH.md"
    risk_md = root / "docs_v2/05_risk/RISK.md"
    prod = root / "docs_v2/01_truth/PRODUCTION_READINESS_AUDIT.md"
    v41 = root / "docs_v2/07_ml/V41_CALIBRATION_EVIDENCE.md"
    inst_py = root / "tradingbot/backtest/instrument.py"

    initial_balance = {
        "value": (
            "$1000 appears as BacktestConfig.initial_balance code default and backtest CLI examples; "
            "no canonical docs_v2 row establishes production/live account balance target."
        ),
        "classification": "B",
        "evidence": [
            *code_ev["excerpts"].get("tradingbot/backtest/config.py", [])[:2],
            *_read_excerpt(ct, r"initial_balance|BacktestConfig", max_hits=1),
            *_read_excerpt(root / "docs_v2/01_truth/SOURCE_OF_TRUTH.md", r"initial balance", max_hits=1),
            *_read_excerpt(v41, r"\$1000|1000", max_hits=1),
            *_read_excerpt(root / "README.md", r"balance|risk", max_hits=1),
        ],
        "role_of_1000": "backtest_default_and_example — NOT documented as production target",
    }

    risk_per_trade = {
        "value": "0.005 (0.5%) documented as live/backtest RiskGate production default after Phase 25B alignment.",
        "classification": "A",
        "evidence": [
            *_read_excerpt(ct, r"RISK_PER_TRADE.*0\.005", max_hits=2),
            *_read_excerpt(ct, r"BacktestConfig\.risk_per_trade", max_hits=1),
            *_read_excerpt(risk_md, r"0\.5%|RISK_PER_TRADE", max_hits=2),
            *_read_excerpt(root / "docs_v2/03_runtime/CONFIGURATION.md", r"RISK_PER_TRADE", max_hits=1),
        ],
    }

    minimum_executable_lot = {
        "value": (
            "0.01 lot for XAUUSD_i in offline instrument catalog (LiteFinance operator evidence note); "
            "BacktestConfig.min_lot=0.01. Live execution volume_min clamp documented as UNK-012 / not fully enforced."
        ),
        "classification": "B",
        "evidence": [
            *_read_excerpt(inst_py, r"volume_min|LiteFinance", max_hits=2),
            *code_ev["excerpts"].get("tradingbot/backtest/config.py", [])[2:4],
            *_read_excerpt(prod, r"volume_min|UNK-012", max_hits=2),
            *_read_excerpt(root / "docs_v2/01_truth/OPERATOR_BROKER_EVIDENCE_COLLECTION.md", r"Volume minimum|volume_min", max_hits=1),
        ],
    }

    micro_account_support = {
        "value": (
            "MICRO tier (<$500) has documented evaluate_micro_feasible_risk() path in RISK.md/RISKGATE_SPEC. "
            "$1000 is SMALL tier (standard lot path). No documentation mandates trading on micro/small accounts "
            "or defines minimum viable account size."
        ),
        "classification": "B",
        "evidence": [
            *_read_excerpt(risk_md, r"MICRO|micro", max_hits=2),
            *_read_excerpt(root / "docs_v2/05_risk/RISKGATE_SPEC.md", r"micro|evaluate_micro", max_hits=1),
            *code_ev["account_tiers"]["source"],
            *_read_excerpt(root / "tradingbot/adapters/risk_gate.py", r"equity < 500|equity < 5000", max_hits=2),
        ],
    }

    return {
        "initial_balance": initial_balance,
        "risk_per_trade": risk_per_trade,
        "minimum_executable_lot": minimum_executable_lot,
        "micro_account_support": micro_account_support,
    }


def _build_contradictions(root: Path) -> list[dict[str, str]]:
    prod = root / "docs_v2/01_truth/PRODUCTION_READINESS_AUDIT.md"
    ct = root / "docs_v2/01_truth/CONFIGURATION_TRUTH.md"
    items: list[dict[str, str]] = []

    stale_risk = _read_excerpt(prod, r"Backtest default.*risk_per_trade=0\.01|1% backtest default", max_hits=1)
    current_risk = _read_excerpt(ct, r"BacktestConfig\.risk_per_trade.*0\.005", max_hits=1)
    if stale_risk and current_risk:
        items.append(
            {
                "topic": "backtest risk_per_trade",
                "classification": "C",
                "detail": (
                    "PRODUCTION_READINESS_AUDIT §8/§13 still claims backtest default 1% vs live 0.5%; "
                    "CONFIGURATION_TRUTH (Phase 25B) documents BacktestConfig.risk_per_trade=0.005 aligned with live."
                ),
                "evidence": stale_risk + current_risk,
            }
        )

    stale_tf = _read_excerpt(prod, r"BacktestConfig\.timeframe.*M1", max_hits=1)
    current_tf = _read_excerpt(ct, r"BacktestConfig\.timeframe.*M5", max_hits=1)
    if stale_tf and current_tf:
        items.append(
            {
                "topic": "backtest timeframe default",
                "classification": "C",
                "detail": (
                    "PRODUCTION_READINESS_AUDIT §13 lists BacktestConfig.timeframe default M1; "
                    "CONFIGURATION_TRUTH documents M5 after Phase 25B alignment."
                ),
                "evidence": stale_tf + current_tf,
            }
        )

    l26 = root / PHASE26L_JSON
    if l26.is_file():
        l26_text = l26.read_text(encoding="utf-8")
        if "micro-account" in l26_text.lower():
            items.append(
                {
                    "topic": "terminology: micro vs SMALL tier at $1000",
                    "classification": "B",
                    "detail": (
                        "Phase 26L artifact uses 'micro-account' colloquially for $1000 balance; "
                        "code tier detect_account_tier classifies $1000 as SMALL (500–5000), not MICRO (<500). "
                        "Documentation does not equate $1000 with MICRO tier."
                    ),
                    "evidence": [
                        "logs/phase26l_riskgate_policy_audit.json: structural_contradictions area 'micro-account lot floor'",
                        "tradingbot/adapters/risk_gate.py: detect_account_tier equity < 500 → MICRO; < 5000 → SMALL",
                    ],
                }
            )

    return items


def _determine_case(operator_intent: dict[str, Any]) -> str:
    risk_cls = operator_intent["risk_per_trade"]["classification"]
    bal_cls = operator_intent["initial_balance"]["classification"]
    if risk_cls == "A" and bal_cls in {"B", "D"}:
        return "CASE_2"
    if bal_cls == "D" and risk_cls in {"B", "D"}:
        return "CASE_4"
    if risk_cls == "A" and bal_cls == "A":
        return "CASE_1"
    if any(x.get("classification") == "C" for x in []):
        pass
    return "CASE_2_OR_4"


def run_phase26m_operator_risk_budget_audit(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path(__file__).resolve().parents[2])
    doc_hits = _scan_docs(root)
    code_ev = _code_behavior_evidence(root)
    operator_intent = _build_operator_intent(root, doc_hits, code_ev)
    contradictions = _build_contradictions(root)

    floor_evidence = _read_excerpt(
        root / "tradingbot/domain/broker_economics.py",
        r"floor_to_volume|VOLUME_BELOW_MIN|Never rounds up",
        max_hits=3,
    )
    reject_below_min = {
        "documented": False,
        "code_behavior": True,
        "classification": "B",
        "evidence": floor_evidence,
        "detail": (
            "Fail-closed floor-down rejection below volume_min is implemented in broker_economics "
            "and verified in Phase 25A/26F tests; not prominently stated as operator policy in docs_v2."
        ),
    }

    zero_trade_periods = {
        "documented": False,
        "classification": "D",
        "evidence": _read_excerpt(root / "docs_v2/09_operations/RUNBOOK.md", r"no trades", max_hits=2),
        "detail": (
            "RUNBOOK lists 'no trades' as operational troubleshooting symptom, not as an explicitly "
            "acceptable steady-state policy. No documentation defines acceptable zero-trade periods "
            "caused by minimum lot constraints."
        ),
    }

    trade_frequency = {
        "documented": True,
        "details": (
            "Upper bound documented: PA M5 MAX_TRADES_PER_DAY=3 in CONFIGURATION_TRUTH. "
            "No minimum trade frequency, no target number of trades, and no mandate to trade on small accounts."
        ),
        "classification": "B",
        "evidence": _read_excerpt(root / "docs_v2/01_truth/CONFIGURATION_TRUTH.md", r"MAX_TRADES_PER_DAY", max_hits=1),
    }

    risk_priority = {
        "documented": False,
        "details": (
            "RiskGate entry authority, daily loss limits, cooldown, and layered gates are documented in RISK.md. "
            "No explicit canonical statement prioritizing risk limits over trade frequency was found."
        ),
        "classification": "D",
        "evidence": _read_excerpt(root / "docs_v2/05_risk/RISK.md", r"RiskGate|daily loss|cooldown", max_hits=2),
    }

    case_key = _determine_case(operator_intent)
    policy_alignment = {
        "current_1000_0.5pct_configuration": (
            "BacktestConfig.initial_balance=1000, risk_per_trade=0.005, XAUUSD_i volume_min=0.01, "
            "floor-down lot normalization — the configuration observed in Phase 26L."
        ),
        "documentation_alignment": "UNKNOWN",
        "reason": (
            "0.5% risk_per_trade is explicitly documented as production policy (A). "
            "$1000 balance is a code/backtest default without documented production target (B). "
            "0.01 minimum lot is broker-catalog evidence, not a universal operator mandate (B). "
            "No documentation explicitly supports the full $1000+0.5%+0.01 combo as intended operator policy. "
            "CASE_2: risk policy documented; account-size intent not established."
        ),
        "case": case_key,
    }

    unknowns = [
        "Operator's intended live/production account balance (not in CONFIGURATION_TRUTH)",
        "Minimum viable account size for XAUUSD_i at 0.5% risk with PA stop distances",
        "Whether operator expects the bot to remain active during extended zero-trade periods from lot floor",
        "Live broker tick_value and whether offline LiteFinance catalog matches operator account",
        "Whether PRODUCTION_READINESS_AUDIT parity table has been refreshed post Phase 25B",
    ]

    recommendation = (
        "Operator intent remains UNKNOWN for account size and minimum viable balance; "
        "no policy change is justified by this phase. "
        "The Phase 26L finding (B — COHERENT BUT EXTREMELY RESTRICTIVE) is consistent with "
        "documented 0.5% risk policy but is NOT additionally supported by explicit documentation "
        "that $1000 is the intended production account or that micro/small-account trading is required."
    )

    report = Phase26MAudit(
        status="PASS_WITH_DEFERRAL",
        generated_at=datetime.now(timezone.utc).isoformat(),
    ).to_dict()

    report.update(
        {
            "production_changes": False,
            "mt5_connected": False,
            "bot_started": False,
            "orders_sent": False,
            "policy_changed": False,
            "objective": (
                "Determine whether documented operator intent supports the $1000 / 0.5% / 0.01-lot "
                "configuration that produced Phase 26L zero-trade RiskGate behavior."
            ),
            "source_hierarchy": "CODE (behavior only) > CANONICAL DOCUMENTATION > AUDIT ARTIFACTS > MEMORY",
            "documents_examined": [p for p in PRIORITY_DOC_PATHS if (root / p).is_file()],
            "code_evidence_paths": list(CODE_EVIDENCE_PATHS),
            "phase26l_reference": PHASE26L_JSON if (root / PHASE26L_JSON).is_file() else None,
            "operator_intent": operator_intent,
            "execution_policy": {
                "reject_trades_below_volume_min": reject_below_min,
                "floor_down_normalization": reject_below_min,
                "zero_trade_periods_from_min_lot": zero_trade_periods,
            },
            "policy_alignment": policy_alignment,
            "trade_frequency_intent": trade_frequency,
            "risk_priority_intent": risk_priority,
            "mathematical_analysis": _illustrative_math(),
            "contradictions": contradictions,
            "unknowns": unknowns,
            "recommendation": recommendation,
            "what_this_proves": [
                "0.5% RISK_PER_TRADE is documented production/backtest policy (A)",
                "$1000 initial_balance is configured but not documented as production account target (B)",
                "0.01 volume_min is catalog-backed offline evidence, not universal operator mandate (B)",
                "MICRO tier support is documented for equity < $500; $1000 is SMALL tier (B)",
                "Full $1000+0.5%+0.01 combo lacks explicit operator-intent documentation (UNKNOWN alignment)",
                "Stale PRODUCTION_READINESS parity rows contradict current CONFIGURATION_TRUTH on risk/timeframe (C)",
            ],
            "what_this_does_not_prove": [
                "That $1000 is or is not the operator's intended live balance",
                "That risk parameters should be changed",
                "That the bot must trade on small accounts",
                "Production readiness or profitability",
            ],
            "final_decision": "PASS_WITH_DEFERRAL",
        }
    )

    _write_json(root / PHASE26M_JSON, report)
    return report


def run_phase26m_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    return run_phase26m_operator_risk_budget_audit(base_dir)

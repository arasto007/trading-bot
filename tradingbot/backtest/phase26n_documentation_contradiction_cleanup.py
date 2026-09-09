"""Phase 26N — Documentation contradiction cleanup audit (doc-only)."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.adapters.risk_gate import detect_account_tier
from tradingbot.backtest.config import BacktestConfig

PHASE26M_JSON = "logs/phase26m_operator_risk_budget_audit.json"
PHASE26N_JSON = "logs/phase26n_documentation_contradiction_cleanup.json"

CANONICAL_DOC_PATHS = (
    "docs_v2/01_truth/CONFIGURATION_TRUTH.md",
    "docs_v2/01_truth/PRODUCTION_READINESS_AUDIT.md",
    "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md",
    "docs_v2/01_truth/FULL_REPOSITORY_SOURCE_OF_TRUTH.md",
    "docs_v2/03_runtime/CONFIGURATION.md",
    "docs_v2/03_runtime/STARTUP_AND_SHUTDOWN.md",
    "docs_v2/05_risk/RISK.md",
    "docs_v2/04_strategy/PA_LIVE_EDGE_AUDIT.md",
)

STALE_RISK_PATTERN = re.compile(
    r"(?<!Superseded)(?<!was )(?<!pre-25B )(?<!pre-Phase-25B )"
    r"Backtest default `risk_per_trade=0\.01`|1% backtest default",
    re.I,
)
STALE_TF_PATTERN = re.compile(
    r"(?<!was )(?<!pre-25B )(?<!pre-Phase-25B )(?<!Superseded: was )"
    r"`BacktestConfig\.timeframe` default \*\*M1\*\*|BacktestConfig\.timeframe=\"M1\"|default TF \*\*M1\*\*",
    re.I,
)
SUPERSEDED_MARKER = re.compile(r"Superseded|was M1|was 1%|pre-25B|pre-Phase-25B|RESOLVED", re.I)


@dataclass
class Phase26NAudit:
    status: str = "PASS_WITH_DEFERRAL"
    generated_at: str = ""
    production_behavior_changed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": 1, "phase": "26N", **asdict(self)}


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _read_lines(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def _find_stale_lines(root: Path, pattern: re.Pattern[str], paths: tuple[str, ...]) -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    for rel in paths:
        for i, line in enumerate(_read_lines(root / rel), start=1):
            if pattern.search(line) and not SUPERSEDED_MARKER.search(line):
                hits.append({"file": rel, "line": str(i), "text": line.strip()[:240]})
    return hits


def _code_backtest_defaults() -> dict[str, Any]:
    cfg = BacktestConfig()
    return {
        "risk_per_trade": cfg.risk_per_trade,
        "timeframe": cfg.timeframe,
        "source": "tradingbot/backtest/config.py::BacktestConfig",
    }


def _tier_terminology() -> dict[str, Any]:
    tier_1000 = detect_account_tier(1000.0).value
    return {
        "micro_boundary": "equity < 500 → AccountTier.MICRO",
        "small_boundary": "500 <= equity < 5000 → AccountTier.SMALL",
        "standard_boundary": "equity >= 5000 → AccountTier.STANDARD",
        "equity_1000_tier": tier_1000,
        "source": "tradingbot/adapters/risk_gate.py::detect_account_tier",
    }


def run_phase26n_documentation_contradiction_cleanup(
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(base_dir or Path(__file__).resolve().parents[2])
    code = _code_backtest_defaults()
    tier = _tier_terminology()

    stale_risk_docs_pre = [
        "docs_v2/01_truth/PRODUCTION_READINESS_AUDIT.md §8, §13 (pre-26N)",
        "docs_v2/01_truth/PRODUCTION_READINESS_AUDIT.md P1-009 (pre-26N)",
    ]
    stale_tf_docs_pre = [
        "docs_v2/01_truth/PRODUCTION_READINESS_AUDIT.md §11, §13 (pre-26N)",
        "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md §13 (pre-26N)",
        "docs_v2/01_truth/FULL_REPOSITORY_SOURCE_OF_TRUTH.md §1, §3.3, discrepancy table (pre-26N)",
        "docs_v2/04_strategy/PA_LIVE_EDGE_AUDIT.md §1, parity table, findings (pre-26N)",
        "docs_v2/03_runtime/STARTUP_AND_SHUTDOWN.md (pre-26N)",
    ]

    corrections = {
        "risk_per_trade": [
            "PRODUCTION_READINESS_AUDIT.md §8: added Superseded block; current 0.005 via Phase 25B",
            "PRODUCTION_READINESS_AUDIT.md §13: sizing row updated to 0.5% / RESOLVED",
            "PRODUCTION_READINESS_AUDIT.md P1-009: PARTIALLY RESOLVED (costs still uncosted)",
        ],
        "backtest_timeframe": [
            "PRODUCTION_READINESS_AUDIT.md §11 M1 row: Superseded note; current M5",
            "PRODUCTION_READINESS_AUDIT.md §13: TF row RESOLVED (M5)",
            "PROJECT_SOURCE_OF_TRUTH.md §13: M1 contradiction updated to M5 aligned",
            "FULL_REPOSITORY_SOURCE_OF_TRUTH.md §1, §3.3, discrepancy table: M5 current",
            "PA_LIVE_EDGE_AUDIT.md: parity table + findings RESOLVED",
            "STARTUP_AND_SHUTDOWN.md: --backtest default TF M5",
        ],
        "account_tier_terminology": [
            "CONFIGURATION_TRUTH.md Phase 26L row: micro-account → SMALL-tier ($1000)",
            "phase26l_riskgate_policy_audit.py: micro-account strings → SMALL-tier ($1000, not MICRO)",
        ],
    }

    remaining_stale_risk = _find_stale_lines(root, STALE_RISK_PATTERN, CANONICAL_DOC_PATHS)
    remaining_stale_tf = _find_stale_lines(root, STALE_TF_PATTERN, CANONICAL_DOC_PATHS)

    terminology_issues = [
        {
            "issue": "Phase 26L/26M used 'micro-account' for $1000 balance",
            "substance": "wording only — tier code classifies $1000 as SMALL, not MICRO",
            "severity": "B",
            "corrected_in": corrections["account_tier_terminology"],
        }
    ]

    contradictions_remaining: list[dict[str, str]] = []
    for hit in remaining_stale_risk:
        contradictions_remaining.append(
            {"topic": "risk_per_trade stale current-state claim", "severity": "C", **hit}
        )
    for hit in remaining_stale_tf:
        contradictions_remaining.append(
            {"topic": "backtest timeframe stale current-state claim", "severity": "C", **hit}
        )

    unknowns = [
        "Legacy docs/ tree may still contain pre-25B M1/1% references (outside docs_v2 canonical scope)",
        "logs/phase26l_riskgate_policy_audit.json not regenerated — may retain pre-26N wording until re-collection",
        "PRODUCTION_READINESS_AUDIT remains a 2026-09-02 historical artifact; other sections may age independently",
    ]

    report = Phase26NAudit(
        status="PASS_WITH_DEFERRAL" if contradictions_remaining else "PASS",
        generated_at=datetime.now(timezone.utc).isoformat(),
    ).to_dict()

    report.update(
        {
            "objective": (
                "Resolve Phase 26M C-level documentation contradictions for backtest risk/timeframe "
                "and B-level MICRO/SMALL terminology without changing production behavior."
            ),
            "source_hierarchy": "CODE > CANONICAL DOCUMENTATION > AUDIT ARTIFACTS",
            "risk_per_trade": {
                "current_code_value": code["risk_per_trade"],
                "current_truth": (
                    "BacktestConfig.risk_per_trade = 0.005 (0.5%), aligned with live RISK_PER_TRADE "
                    "per CONFIGURATION_TRUTH.md Phase 25B."
                ),
                "stale_documents": stale_risk_docs_pre,
                "historical_documents": [
                    "PRODUCTION_READINESS_AUDIT.md §8 Superseded block preserves pre-25B 0.01 (1%) audit claim",
                ],
                "corrections_applied": corrections["risk_per_trade"],
            },
            "backtest_timeframe": {
                "current_code_value": code["timeframe"],
                "current_truth": (
                    "BacktestConfig.timeframe = M5, aligned with live PA M5 per CONFIGURATION_TRUTH.md Phase 25B."
                ),
                "stale_documents": stale_tf_docs_pre,
                "historical_documents": [
                    "PRODUCTION_READINESS_AUDIT.md §11/§13 preserve 'was M1 at audit time' markers",
                    "FULL_REPOSITORY_SOURCE_OF_TRUTH discrepancy table notes 'Was C (M1) pre-Phase-25B'",
                ],
                "corrections_applied": corrections["backtest_timeframe"],
            },
            "account_tier_terminology": {
                **tier,
                "terminology_issues": terminology_issues,
                "corrections_applied": corrections["account_tier_terminology"],
            },
            "contradictions_remaining": contradictions_remaining,
            "unknowns": unknowns,
            "production_behavior_changed": False,
            "safety": {
                "MT5_CONNECTED": False,
                "BOT_STARTED": False,
                "ORDERS_SENT": False,
                "PRODUCTION_CODE_CHANGED": False,
                "CONFIGURATION_CHANGED": False,
                "BACKTEST_EXECUTED": False,
                "FULL_ENGINE_EXECUTED": False,
            },
            "documents_examined": [p for p in CANONICAL_DOC_PATHS if (root / p).is_file()],
            "phase26m_reference": PHASE26M_JSON if (root / PHASE26M_JSON).is_file() else None,
            "final_decision": "PASS_WITH_DEFERRAL" if contradictions_remaining else "PASS",
        }
    )

    _write_json(root / PHASE26N_JSON, report)
    return report


def run_phase26n_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    return run_phase26n_documentation_contradiction_cleanup(base_dir)

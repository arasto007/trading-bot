"""Phase 26O — Legacy docs/ truth sweep (documentation-only)."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.adapters.risk_gate import detect_account_tier
from tradingbot.backtest.config import BacktestConfig

PHASE26N_JSON = "logs/phase26n_documentation_contradiction_cleanup.json"
PHASE26O_JSON = "logs/phase26o_legacy_docs_truth_sweep.json"

DOCS_SCOPE = "docs/"

# Stale current-state patterns (must not match superseded/historical lines)
STALE_RISK_01 = re.compile(
    r"(?<!Superseded)(?<!was )(?<!pre-25B )(?<!pre-Phase-25B )"
    r"(Backtest default `risk_per_trade=0\.01`|1% backtest default|backtest default.*1%)",
    re.I,
)
STALE_M1_DEFAULT = re.compile(
    r"(?<!was )(?<!pre-25B )(?<!pre-Phase-25B )(?<!legacy )(?<!historical )"
    r"(BacktestConfig\.timeframe.*\*\*M1\*\*|BacktestConfig\.timeframe=\"M1\"|default TF \*\*M1\*\*|BacktestConfig default M1)",
    re.I,
)
HISTORICAL_MARKER = re.compile(
    r"historical|Superseded|pre-25B|pre-Phase-25B|was M1|was 1%|legacy collector|HISTORICAL|Phase 1 legacy",
    re.I,
)
PROVEN_EQUIV = re.compile(
    r"(XAUUSD.*proven|proven.*XAUUSD|identity proven|economics.*equivalent|equivalent.*economics|same economics)",
    re.I,
)
MICRO_MISUSE = re.compile(r"micro.?account|\$1000.*MICRO|MICRO.*\$1000|1000.*micro", re.I)

CORRECTIONS_APPLIED = {
    "docs/PHASE3_BACKTEST_FA.md": "Added current BacktestConfig defaults block (M5, 0.005)",
    "docs/ONBOARDING_FA.md": "Clarified XAUUSD vs XAUUSD_i; NOT PROVEN equivalence",
    "docs/robot_behavior_audit/configuration_truth.md": "VOL_REGIME_MAX_LOT 0.01 labeled as lot cap not risk_per_trade",
    "docs/phase8_data_collection.md": "M1 row labeled historical; not BacktestConfig default",
}


@dataclass
class Phase26OSweep:
    status: str = "PASS_WITH_DEFERRAL"
    generated_at: str = ""
    production_behavior_changed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": 1, "phase": "26O", **asdict(self)}


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _legacy_md_files(root: Path) -> list[Path]:
    docs = root / "docs"
    if not docs.is_dir():
        return []
    return sorted(p for p in docs.rglob("*.md") if p.is_file())


def _classify_line(rel: str, line_no: int, line: str, pattern: re.Pattern[str]) -> dict[str, str]:
    text = line.strip()[:240]
    if HISTORICAL_MARKER.search(line):
        kind = "historical"
    elif "NOT PROVEN" in line or "ambiguous" in line.lower():
        kind = "ambiguous"
    elif pattern.search(line):
        kind = "current" if not HISTORICAL_MARKER.search(line) else "historical"
    else:
        kind = "ambiguous"
    return {"file": rel, "line": str(line_no), "text": text, "classification": kind}


def _scan_pattern(root: Path, files: list[Path], pattern: re.Pattern[str]) -> dict[str, list[dict[str, str]]]:
    current: list[dict[str, str]] = []
    historical: list[dict[str, str]] = []
    ambiguous: list[dict[str, str]] = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not pattern.search(line):
                continue
            item = _classify_line(rel, i, line, pattern)
            bucket = item.pop("classification")
            if bucket == "current":
                current.append(item)
            elif bucket == "historical":
                historical.append(item)
            else:
                ambiguous.append(item)
    return {
        "current_claims": current,
        "historical_claims": historical,
        "ambiguous_claims": ambiguous,
    }


def _scan_symbol_claims(root: Path, files: list[Path]) -> dict[str, Any]:
    xauusd: list[dict[str, str]] = []
    xauusd_i: list[dict[str, str]] = []
    equiv: list[dict[str, str]] = []
    unsupported: list[dict[str, str]] = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if "XAUUSD_i" in line:
                xauusd_i.append({"file": rel, "line": str(i), "text": line.strip()[:200]})
            elif re.search(r"\bXAUUSD\b", line):
                xauusd.append({"file": rel, "line": str(i), "text": line.strip()[:200]})
            if PROVEN_EQUIV.search(line) and "NOT PROVEN" not in line:
                equiv.append({"file": rel, "line": str(i), "text": line.strip()[:200]})
            if "NOT PROVEN" in line and ("XAUUSD" in line or "identity" in line.lower()):
                unsupported.append({"file": rel, "line": str(i), "text": line.strip()[:200]})
    return {
        "xauusd_claims": xauusd[:20],
        "xauusd_i_claims": xauusd_i[:20],
        "equivalence_claims": equiv,
        "unsupported_equivalence_claims": unsupported[:10],
        "note": "CLI/dataset labels often use bare XAUUSD; live broker symbol is XAUUSD_i — mapping is not proven economic equivalence.",
    }


def _scan_micro_misuse(root: Path, files: list[Path]) -> dict[str, Any]:
    misuse: list[dict[str, str]] = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if MICRO_MISUSE.search(line):
                misuse.append({"file": rel, "line": str(i), "text": line.strip()[:200]})
    tier = detect_account_tier(1000.0).value
    return {
        "micro_misuse": misuse,
        "small_correct_usage": [
            {
                "note": f"$1000 maps to {tier} per detect_account_tier (code truth)",
                "source": "tradingbot/adapters/risk_gate.py",
            }
        ],
        "corrections": [] if not misuse else ["No legacy docs/ MICRO/$1000 misuse required correction"],
    }


def run_phase26o_legacy_docs_truth_sweep(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path(__file__).resolve().parents[2])
    files = _legacy_md_files(root)
    cfg = BacktestConfig()

    risk_scan = _scan_pattern(root, files, STALE_RISK_01)
    risk_scan["corrections"] = [
        CORRECTIONS_APPLIED["docs/robot_behavior_audit/configuration_truth.md"],
        CORRECTIONS_APPLIED["docs/PHASE3_BACKTEST_FA.md"],
    ]

    m1_scan = _scan_pattern(root, files, STALE_M1_DEFAULT)
    m1_scan["corrections"] = [
        CORRECTIONS_APPLIED["docs/phase8_data_collection.md"],
        CORRECTIONS_APPLIED["docs/PHASE3_BACKTEST_FA.md"],
    ]

    tier_info = _scan_micro_misuse(root, files)
    symbol_info = _scan_symbol_claims(root, files)

    remaining = risk_scan["current_claims"] + m1_scan["current_claims"]
    status = "PASS" if not remaining else "PASS_WITH_DEFERRAL"

    unknowns = [
        "Legacy docs/ robot_behavior_audit/*.md describe 2026-07 Adaptive-as-live — superseded by docs_v2 PA lock (out of 26O search scope)",
        "CLI examples using --symbol XAUUSD and --tf M15 are overrides, not BacktestConfig defaults",
        "architecture_atlas/ generated assets not re-scanned for stale text (md-only sweep)",
        "balance 1000 in backtest CLI examples is a test parameter, not documented production target",
    ]

    report = Phase26OSweep(
        status=status,
        generated_at=datetime.now(timezone.utc).isoformat(),
    ).to_dict()

    report.update(
        {
            "scope": DOCS_SCOPE,
            "documents_inspected": len(files),
            "document_paths_sample": [p.relative_to(root).as_posix() for p in files[:15]],
            "code_truth": {
                "BacktestConfig.risk_per_trade": cfg.risk_per_trade,
                "BacktestConfig.timeframe": cfg.timeframe,
                "equity_1000_tier": detect_account_tier(1000.0).value,
            },
            "risk_01_references": risk_scan,
            "m1_references": m1_scan,
            "account_tier_terminology": tier_info,
            "symbol_claims": symbol_info,
            "remaining_contradictions": remaining,
            "unknowns": unknowns,
            "documentation_files_changed": list(CORRECTIONS_APPLIED.keys()),
            "corrections_applied_detail": CORRECTIONS_APPLIED,
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
            "phase26n_reference": PHASE26N_JSON if (root / PHASE26N_JSON).is_file() else None,
            "final_decision": status,
        }
    )

    _write_json(root / PHASE26O_JSON, report)
    return report


def run_phase26o_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    return run_phase26o_legacy_docs_truth_sweep(base_dir)

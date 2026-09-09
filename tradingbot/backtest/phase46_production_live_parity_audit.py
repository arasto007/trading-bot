"""Phase 46 — production / live-parity audit (static, research-only).

Does not start the bot, read .env, trade, or import live.py (that module
reads optional env overrides on import).
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json

PHASE = "46"
PHASE46_JSON = "logs/phase46_production_live_parity_audit.json"
PHASE46_MD = "docs_v2/02_research/PHASE46_PRODUCTION_LIVE_PARITY_AUDIT.md"
PHASE46_BLOCKERS_MD = "docs_v2/02_research/PHASE44_46_BLOCKER_MATRIX.md"
PHASE40_JSON = "logs/phase40_full_horizon_validation.json"
PHASE43_JSON = "logs/phase43_broker_cost_execution_validation.json"
PHASE44_JSON = "logs/phase44_executable_backtest_readiness.json"
PHASE45_JSON = "logs/phase45_event_oos_regime_robustness.json"
BLOCKED = "BLOCKED"
UNKNOWN = "UNKNOWN"
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "parity",
    "contradictions",
    "production_readiness",
    "final_gate",
    "verdict",
    "production_safety",
    "artifacts",
)


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
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return UNKNOWN


def _contains(root: Path, rel: str, token: str) -> bool:
    path = root / rel
    if not path.is_file():
        return False
    return token in path.read_text(encoding="utf-8", errors="replace")


def run_phase46_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p43 = _safe_load_json(root / PHASE43_JSON) or {}
    p44 = _safe_load_json(root / PHASE44_JSON) or {}
    p45 = _safe_load_json(root / PHASE45_JSON) or {}

    forming_bar = _contains(root, "tradingbot/domain/ohlcv.py", "def exclude_forming_bar")
    pa_strategy = _contains(root, "engine/strategies/price_action_strategy.py", "class PriceActionStrategy")
    pa_lock = _contains(root, "tradingbot/services/pa_production_lock.py", "pa_production")
    risk_gate = _contains(root, "tradingbot/adapters/risk_gate.py", "class RiskGate")
    kill = _contains(root, "tradingbot/services/kill_switch.py", "kill")
    exec_mod = _contains(root, "tradingbot/adapters/mt5_execution.py", "order_send")
    journal = (root / "data/trade_journal.db").is_file()
    live_env_symbol = _contains(root, "tradingbot/config/live.py", "TRADINGBOT_REAL_SYMBOL")
    primary_i = _contains(root, "tradingbot/config/live.py", 'PRIMARY_SYMBOL = "XAUUSD_i"')
    broker_refuse = _contains(root, "tradingbot/backtest/broker.py", 'message="commission UNKNOWN"')
    dotenv = (root / "tradingbot/config/dotenv_loader.py").is_file()

    contradictions = [
        {
            "id": "CX-REAL-SYMBOL",
            "status": "CONTRADICTED / NOT_PROVEN",
            "claim_a": "Operator package: REAL gold name = XAUUSD",
            "claim_b": "CODE PRIMARY_SYMBOL = XAUUSD_i; OBSERVED REAL catalog = XAUUSD_i; XAUUSD NOT_OBSERVED",
            "resolution": "NOT silently reconciled. EV-EQ-01 remains NOT_PROVEN.",
        },
        {
            "id": "UNK-COMMISSION",
            "status": "UNKNOWN",
            "claim_a": "Official ECN metals $5/lot; CLASSIC commission None",
            "claim_b": "Account product UNKNOWN; 30 deal zeros OBSERVED_ZERO_NOT_PROVEN",
            "resolution": "Neither schedule applied.",
        },
        {
            "id": "UNK-REAL-SYMBOL-ENV",
            "status": "UNKNOWN",
            "claim_a": "live.py has TRADINGBOT_REAL_SYMBOL override path",
            "claim_b": "This audit did not read .env",
            "resolution": "Operator-effective symbol remains UNKNOWN for env override.",
        },
    ]

    parity = {
        "DATA_PARITY": {
            "status": "PARTIAL",
            "symbol": "research tape XAUUSD_i M5 OHLC; live PRIMARY_SYMBOL cited as XAUUSD_i in code",
            "timeframe": "M5",
            "ohlc": "OBSERVED on frozen Phase 38/40 tape",
            "bid_ask": "PARTIAL sidecar / eval tape PROXY",
            "spread": "PARTIAL",
            "tick_volume": UNKNOWN,
            "timezone": "UTC on research parquet",
            "gaps": "not re-audited this phase",
        },
        "SIGNAL_PARITY": {
            "status": "PARTIAL",
            "strategy_path": "PriceActionStrategy / gold_ny_sweep (CODE present)",
            "forming_bar_excluded": forming_bar,
            "pa_lock_present": pa_lock,
            "lookahead_control": "exclude_forming_bar present" if forming_bar else UNKNOWN,
            "event_grouping": "Phase 40 mechanical events reused",
            "parameters_changed": False,
        },
        "RISK_PARITY": {
            "status": "PARTIAL",
            "riskgate_class_present": risk_gate,
            "phase40_allowed": ((p40.get("executable") or {}).get("allowed")),
            "phase40_rejected": ((p40.get("executable") or {}).get("rejected")),
            "fills": ((p40.get("executable") or {}).get("executed_simulated_trades")),
            "kill_switch_present": kill,
            "riskgate_modified_this_phase": False,
        },
        "EXECUTION_PARITY": {
            "status": "FAIL",
            "live_order_send_exists": exec_mod,
            "request_fill_pairs": (p43.get("request_fill") or {}).get("pairs"),
            "simulated_broker_refuses_unknown_commission": broker_refuse,
            "phase44_simulated_broker_invoked": ((p44.get("executable") or {}).get("simulated_broker_invoked")),
            "deviation_treated_as_slippage": False,
        },
        "BROKER_PARITY": {
            "status": "FAIL",
            "symbol_mapping": (p43.get("symbol") or {}).get("SYMBOL_MAPPING"),
            "commission": (p43.get("commission") or {}).get("status"),
            "swap": (p43.get("swap") or {}).get("HISTORICAL_SWAP"),
            "account_product": (p43.get("account_product") or {}).get("ACCOUNT_PRODUCT_STATUS"),
        },
        "CONFIG_PARITY": {
            "status": "PARTIAL",
            "code_primary_symbol_xauusd_i": primary_i,
            "real_symbol_env_path_exists": live_env_symbol,
            "env_read": False,
            "dotenv_loader_exists": dotenv,
            "dead_or_stale_flags": "historical HTA/ML paths remain in repo; not reclassified here",
        },
        "OBSERVABILITY": {
            "status": "PARTIAL",
            "trade_journal_present": journal,
            "phase_artifacts": True,
            "xauusd_i_request_fill_pairs": 0,
            "reproducibility": "Phase 40 JSON + JSONL frozen; fingerprint preserved",
        },
    }

    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "phase40_scan_rerun": False,
        "env_accessed": False,
        "parity": parity,
        "contradictions": contradictions,
        "production_readiness": "NOT_READY",
        "PRODUCTION_READINESS": "NOT_READY",
        "final_gate": BLOCKED,
        "FINAL_GATE": BLOCKED,
        "verdict": {
            "overall": "INSUFFICIENT_EVIDENCE",
            "ready_for_live": False,
            "profitability_verdict": "NOT_ISSUED",
            "robustness": (p45.get("robustness_verdict") or UNKNOWN),
        },
        "production_safety": {
            "TRADING": "NOT_PERFORMED",
            "ORDERS": 0,
            "BOT": "NOT_STARTED",
            "DAEMON": "NOT_STARTED",
            "ML": "NOT_ACTIVATED",
            "RISK_GATE": "NOT_MODIFIED",
            "STRATEGY": "NOT_MODIFIED",
            "EXECUTION_ROUTER": "NOT_MODIFIED",
            "ENV": "NOT_READ",
            "PHASE40_RESCAN": "NO",
            "production_changes": "NONE",
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE46_JSON, "md": PHASE46_MD, "blockers_md": PHASE46_BLOCKERS_MD},
    }
    (root / PHASE46_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE46_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    md = [
        "# Phase 46 — Production / Live-Parity Audit",
        "",
        f"**STATUS:** `{payload['status']}`",
        f"**PRODUCTION_READINESS:** `{payload['production_readiness']}`",
        f"**FINAL_GATE:** `{BLOCKED}`",
        "",
        "Static CODE audit. `.env` was not read. Bot was not started. `live.py` was not imported.",
        "",
        "## Parity",
        "",
        f"- DATA: `{parity['DATA_PARITY']['status']}`",
        f"- SIGNAL: `{parity['SIGNAL_PARITY']['status']}`",
        f"- RISK: `{parity['RISK_PARITY']['status']}`",
        f"- EXECUTION: `{parity['EXECUTION_PARITY']['status']}`",
        f"- BROKER: `{parity['BROKER_PARITY']['status']}`",
        f"- CONFIG: `{parity['CONFIG_PARITY']['status']}`",
        f"- OBSERVABILITY: `{parity['OBSERVABILITY']['status']}`",
        "",
        "## Unresolved contradictions",
        "",
    ]
    for cx in contradictions:
        md.append(f"- `{cx['id']}` ({cx['status']}): {cx['resolution']}")
    md += [
        "",
        "Do not declare READY_FOR_LIVE.",
        "",
        "STOP AFTER PHASE 46. DO NOT OPTIMIZE. DO NOT TRADE.",
        "",
    ]
    (root / PHASE46_MD).write_text("\n".join(md), encoding="utf-8")
    blockers = [
        "# Phase 44–46 — Blocker Matrix",
        "",
        "**FINAL_GATE:** `BLOCKED`",
        "",
        "| Blocker | Status | Phase | Close without trading? |",
        "|---|---|---|---|",
        "| Commission VERIFIED_SCHEDULE | OPEN / UNKNOWN | 43–44 | Yes — cabinet/contract |",
        "| Executable evaluation | BLOCKED | 44 | After commission |",
        "| Request/fill pairs | 0 | 42–46 | Telemetry yes; trading no |",
        "| Historical Bid/Ask on eval tape | PARTIAL | 42–46 | Yes if history exists |",
        "| Historical swap | UNKNOWN | 42–45 | Yes if series exists |",
        "| EV-EQ-01 / XAUUSD mapping | NOT_PROVEN | 42–46 | Yes — catalog/docs |",
        "| Cost-aware robustness | MODELED / not validated | 45 | After executable |",
        "| RAW time stability | FRAGILE | 45 | Analysis only |",
        "| Production readiness | NOT_READY | 46 | After costs + parity |",
        "| Operator .env REAL symbol | UNKNOWN (not read) | 46 | Sanitized dump; do not read .env here |",
        "",
        "No Phase 41–43 blocker was closed in 44–46.",
        "",
    ]
    (root / PHASE46_BLOCKERS_MD).write_text("\n".join(blockers), encoding="utf-8")
    _patch_truth(root, payload)
    return payload


def _patch_truth(root: Path, payload: dict[str, Any]) -> None:
    line = (
        "Phases 44–46 (`docs_v2/02_research/PHASE44_EXECUTABLE_BACKTEST_READINESS.md`, "
        "`PHASE45_EVENT_OOS_REGIME_ROBUSTNESS.md`, `PHASE46_PRODUCTION_LIVE_PARITY_AUDIT.md`) "
        "are research-only executable-readiness, robustness, and live-parity layers. "
        "They do not authorize live trading, overwrite the frozen M5 snapshot, optimize, or start Phase 47."
    )
    src = root / "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md"
    text = src.read_text(encoding="utf-8")
    if line not in text:
        marker = "Phase 43 (`docs_v2/02_research/PHASE43_BROKER_COST_EXECUTION_VALIDATION.md`)"
        idx = text.find(marker)
        if idx != -1:
            end = text.find("\n\n", idx)
            text = (text[:end] + "\n\n" + line + text[end:]) if end != -1 else text.rstrip() + "\n\n" + line + "\n"
            src.write_text(text, encoding="utf-8")
    cfg = root / "docs_v2/01_truth/CONFIGURATION_TRUTH.md"
    ctext = cfg.read_text(encoding="utf-8")
    rows = (
        "| Phase 44 executable readiness | `run_phase44_collection()` | n/a | RESEARCH; fail-closed; no bot/orders/.env | "
        f"**{payload.get('status')}**; executable BLOCKED |\n"
        "| Phase 45 event/OOS robustness | `run_phase45_collection()` | n/a | RESEARCH; frozen Phase 40 only | "
        "**PASS**; no optimization |\n"
        "| Phase 46 live-parity audit | `run_phase46_collection()` | n/a | RESEARCH/AUDIT; no .env | "
        f"**{payload.get('status')}**; NOT_READY |"
    )
    if "Phase 44 executable readiness" not in ctext:
        ctext = ctext.replace("| PA M5 `MIN_CONFIDENCE`", rows + "\n| PA M5 `MIN_CONFIDENCE`")
        cfg.write_text(ctext, encoding="utf-8")
    bnd = root / "docs_v2/01_truth/PRODUCTION_RESEARCH_BOUNDARY.md"
    btext = bnd.read_text(encoding="utf-8")
    extra = (
        "`tradingbot/backtest/phase44_executable_backtest_readiness.py` — **RESEARCH_ONLY** fail-closed executable gate.\n"
        "`tradingbot/backtest/phase45_event_oos_regime_robustness.py` — **RESEARCH_ONLY** frozen-tape robustness.\n"
        "`tradingbot/backtest/phase46_production_live_parity_audit.py` — **RESEARCH_ONLY** live-parity audit; does not import live.py.\n"
    )
    needle = (
        "`tradingbot/backtest/phase43_broker_cost_execution_validation.py` — **RESEARCH_ONLY** "
        "account-specific cost/identity/telemetry; attach-if-running; does not overwrite Phase 28 M5.\n"
    )
    if "phase44_executable_backtest_readiness.py" not in btext and needle in btext:
        bnd.write_text(btext.replace(needle, needle + extra), encoding="utf-8")
    ku = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    ktext = ku.read_text(encoding="utf-8")
    ktext = ktext.replace("| Phase 44 started | **NO** |", "| Phase 44 started | **YES** |")
    block = f"""

## Executable readiness / robustness / parity (Phases 44–46)

| Claim | Status |
|---|---|
| Phase 44 executable ready | **False / BLOCKED** |
| Phase 45 robustness | **FRAGILE** (RAW); cost-aware MODELED |
| Phase 46 production readiness | **NOT_READY** |
| Commission | **UNKNOWN** |
| FINAL_GATE | **{payload.get("final_gate")}** |
| Phase 47 started | **NO** |
"""
    if "## Executable readiness / robustness / parity (Phases 44–46)" not in ktext:
        ku.write_text(ktext.rstrip() + block, encoding="utf-8")
    else:
        ku.write_text(ktext, encoding="utf-8")


if __name__ == "__main__":
    out = run_phase46_collection(Path("."))
    print("READY", out.get("production_readiness"), "GATE", out.get("final_gate"))

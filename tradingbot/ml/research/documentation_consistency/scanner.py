"""Scan canonical documentation and code invariants (offline)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]

CANONICAL_ENTRY = ROOT / "docs_v2" / "01_truth" / "PROJECT_SOURCE_OF_TRUTH.md"

CANONICAL_REL = [
    "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md",
    "docs_v2/01_truth/CURRENT_RUNTIME_STATE.md",
    "docs_v2/01_truth/CONFIGURATION_TRUTH.md",
    "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md",
    "docs_v2/01_truth/PRODUCTION_RESEARCH_BOUNDARY.md",
    "docs_v2/01_truth/DOCUMENTATION_SYSTEM_AUDIT.md",
    "docs_v2/02_architecture/SYSTEM_ARCHITECTURE.md",
    "docs_v2/02_architecture/DATA_FLOW.md",
    "docs_v2/02_architecture/COMPONENT_BOUNDARIES.md",
    "docs_v2/03_runtime/LIVE_RUNTIME_PATH.md",
    "docs_v2/03_runtime/STARTUP_AND_SHUTDOWN.md",
    "docs_v2/03_runtime/EXECUTION_FLOW.md",
    "docs_v2/04_strategy/ACTIVE_STRATEGIES.md",
    "docs_v2/04_strategy/PRICE_ACTION_LIVE_SPEC.md",
    "docs_v2/05_risk/RISKGATE_SPEC.md",
    "docs_v2/05_risk/RISK_AND_EXECUTION_BOUNDARY.md",
    "docs_v2/06_data/DATA_PIPELINE.md",
    "docs_v2/06_data/DATA_CONTRACTS.md",
    "docs_v2/07_ml/ML_SYSTEM_STATE.md",
    "docs_v2/07_ml/MODEL_REGISTRY.md",
    "docs_v2/07_ml/CALIBRATION_STATE.md",
    "docs_v2/99_change_control/DOCUMENTATION_UPDATE_PROTOCOL.md",
]

REQUIRED_ENTRY_PHRASES = (
    "XAUUSD_i",
    "PA_PRODUCTION_LOCK",
    "evaluate_m5_london_sweep",
    "USE_ML_KERNEL",
    "Canonical-Entry:** true",
)

V41_BUNDLE = "a433fa410604b17ad195ec80469c86bca47b3df718f4072b2c5d1dc2b153eb6b"


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def scan_canonical_files() -> dict[str, Any]:
    missing = [rel for rel in CANONICAL_REL if not (ROOT / rel).is_file()]
    return {"missing": missing, "ok": not missing}


def scan_canonical_entry() -> dict[str, Any]:
    if not CANONICAL_ENTRY.is_file():
        return {"ok": False, "reason": "missing_entry"}
    text = CANONICAL_ENTRY.read_text(encoding="utf-8")
    missing_phrases = [p for p in REQUIRED_ENTRY_PHRASES if p not in text]
    entry_true = text.count("Canonical-Entry:** true") + text.count("**Canonical-Entry:** true")
    others = []
    for rel in CANONICAL_REL:
        if rel.endswith("PROJECT_SOURCE_OF_TRUTH.md"):
            continue
        body = _read(rel)
        if re.search(r"Canonical-Entry:\s*\*\*\s*true", body, re.I) or "Canonical-Entry:** true" in body:
            others.append(rel)
    return {
        "ok": not missing_phrases and not others,
        "missing_phrases": missing_phrases,
        "duplicate_entries": others,
        "entry_true_markers": entry_true,
    }


def scan_code_invariants() -> dict[str, Any]:
    from tradingbot.config.live import LIVE_TRADING_CONFIG, PRIMARY_SYMBOL
    from tradingbot.config.strategies import ACTIVE_STRATEGIES
    from tradingbot.ml.confidence_engine.engine_calibrator import (
        TREND_MODEL_ID,
        engine_calibration_factor,
    )
    from tradingbot.ml.integration.config import is_ml_kernel_enabled
    from tradingbot.ml.integration.kernel_adapter import PIPELINE_TIMEOUT_MS
    from tradingbot.ml.phase15a.config import TREND_ENGINE_ID, TREND_ENGINE_V41_ID
    from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id

    v41_factor, v41_reason = engine_calibration_factor(
        engine=TREND_ENGINE_V41_ID, regime="TREND", regime_strength=1.0
    )
    return {
        "PRIMARY_SYMBOL": PRIMARY_SYMBOL,
        "PA_PRODUCTION_LOCK": bool(LIVE_TRADING_CONFIG.get("PA_PRODUCTION_LOCK")),
        "MULTI_ENGINE_ROUTER_ENABLED": bool(LIVE_TRADING_CONFIG.get("MULTI_ENGINE_ROUTER_ENABLED")),
        "USE_ML_KERNEL_process": is_ml_kernel_enabled(),
        "PIPELINE_TIMEOUT_MS": PIPELINE_TIMEOUT_MS,
        "TREND_MODEL_ID": TREND_MODEL_ID,
        "TREND_ENGINE_ID": TREND_ENGINE_ID,
        "TREND_ENGINE_V41_ID": TREND_ENGINE_V41_ID,
        "resolve_active_trend_engine_id": resolve_active_trend_engine_id(),
        "v41_calibration_factor": v41_factor,
        "v41_calibration_reason": v41_reason,
        "active_strategies_true": [k for k, v in ACTIVE_STRATEGIES.items() if v],
    }


def scan_v41_bundle() -> dict[str, Any]:
    from tradingbot.ml.phase15a.config import trend_rf_bundle_root

    chk = trend_rf_bundle_root(version="v41") / "checksum.json"
    data = json.loads(chk.read_text(encoding="utf-8")) if chk.is_file() else {}
    sha = data.get("bundle_sha256")
    return {"present": chk.is_file(), "bundle_sha256": sha, "unchanged": sha == V41_BUNDLE}


def scan_factory_not_importing_research() -> dict[str, Any]:
    text = (ROOT / "tradingbot" / "application" / "bootstrap.py").read_text(encoding="utf-8")
    banned = (
        "ml.research.v41_isolated",
        "ml.research.pa_live_audit",
        "ml.research.full_repo_audit",
        "ml.research.documentation_consistency",
    )
    hits = [b for b in banned if b in text]
    return {"ok": not hits, "hits": hits}


def scan_contradiction_registry() -> dict[str, Any]:
    path = ROOT / "docs_v2" / "01_truth" / "KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    ids = re.findall(r"^### (CX-\d+)", text, flags=re.M)
    return {"ok": path.is_file() and len(ids) >= 10, "ids": ids}


def run_scan() -> dict[str, Any]:
    files = scan_canonical_files()
    entry = scan_canonical_entry()
    invariants = scan_code_invariants()
    bundle = scan_v41_bundle()
    research = scan_factory_not_importing_research()
    cx = scan_contradiction_registry()
    failures: list[str] = []
    if not files["ok"]:
        failures.append(f"missing_canonical:{files['missing']}")
    if not entry["ok"]:
        failures.append(f"entry:{entry}")
    if invariants["PRIMARY_SYMBOL"] != "XAUUSD_i":
        failures.append("symbol")
    if invariants["PA_PRODUCTION_LOCK"] is not True:
        failures.append("pa_lock")
    cfg_src = (ROOT / "tradingbot" / "ml" / "integration" / "config.py").read_text(encoding="utf-8")
    if "if not is_ml_kernel_env_set():" not in cfg_src or '_env_bool("USE_ML_KERNEL", False)' not in cfg_src:
        failures.append("ml_kernel_default_logic")
    if invariants["TREND_MODEL_ID"] != "trend_rf_v40":
        failures.append("trend_model_id")
    if float(invariants["v41_calibration_factor"]) != 1.0:
        failures.append("v41_factor")
    if invariants["PIPELINE_TIMEOUT_MS"] != 500.0:
        failures.append("timeout")
    if invariants["active_strategies_true"] != ["priceaction"]:
        failures.append("strategies")
    if not bundle.get("unchanged"):
        failures.append("v41_bundle")
    if not research["ok"]:
        failures.append("research_import")
    if not cx["ok"]:
        failures.append("contradictions")
    return {
        "ok": not failures,
        "failures": failures,
        "files": files,
        "entry": entry,
        "invariants": invariants,
        "v41_bundle": bundle,
        "research_isolation": research,
        "contradictions": cx,
    }

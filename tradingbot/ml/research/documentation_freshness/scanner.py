"""Offline documentation freshness scanner. Does not rewrite documentation.

Canonical snapshot writes require an explicit allow_canonical flag.
Tests must pass a fixture snapshot path and must not mutate the canonical file.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
SNAPSHOT = ROOT / "data" / "ml" / "reports" / "documentation_freshness" / "snapshot.json"

WATCHED = [
    "tradingbot/ml/integration/factory.py",
    "tradingbot/ml/phase15a/config.py",
    "tradingbot/config/live.py",
    "tradingbot/ml/integration/kernel_adapter.py",
    "tradingbot/adapters/risk_gate.py",
    "tradingbot/adapters/mt5_execution.py",
    "tradingbot/ml/confidence_engine/engine_calibrator.py",
    "tradingbot/ml/confidence_engine/calibration_policy.py",
    "tradingbot/ml/shadow/shadow_gate.py",
    "tradingbot/adapters/multi_engine_router.py",
    "tradingbot/services/pa_production_lock.py",
    "engine/strategies/price_action_strategy.py",
    "tradingbot/config/pa_symbol_tf_presets.py",
    "tradingbot/config/strategies.py",
    "tradingbot/config/dotenv_loader.py",
    "tradingbot/config/engine_settings.py",
    "tradingbot/domain/gold_strategies/m5_london_sweep.py",
    "tradingbot/domain/gold_strategies/router.py",
    "tradingbot/domain/pa_hardening.py",
    "tradingbot/domain/ohlcv.py",
    "tradingbot/pipeline/signal_stage.py",
    "tradingbot/adapters/legacy_strategy_registry.py",
    "tradingbot/adapters/mt5_market_data.py",
    "tradingbot/ml/risk_intelligence/risk_types.py",
    "tradingbot/services/kill_switch.py",
    "scripts/start_bot.py",
    "scripts/start_live_daemon.ps1",
    "scripts/run_live_watchdog.py",
    "tradingbot/application/bootstrap.py",
    "tradingbot/application/live_runner.py",
    "tradingbot/ml/integration/config.py",
    "tradingbot/__main__.py",
    "start/START_BOT.bat",
    "start/_load_env.bat",
]

WATCH_REASONS = {
    "tradingbot/ml/integration/factory.py": "Live strategy selection branch order.",
    "tradingbot/ml/phase15a/config.py": "TREND_MODEL_ID / v40 vs v41 identifiers.",
    "tradingbot/config/live.py": "PRIMARY_SYMBOL, PA lock, router, TIMEFRAMES.",
    "tradingbot/ml/integration/kernel_adapter.py": "PIPELINE_TIMEOUT_MS on ML path.",
    "tradingbot/adapters/risk_gate.py": "Mandatory RiskGate.evaluate and spread 999.",
    "tradingbot/adapters/mt5_execution.py": "Dry-run / paper / live order_send.",
    "tradingbot/ml/confidence_engine/engine_calibrator.py": "v41 factor 1.0 else-branch.",
    "tradingbot/ml/confidence_engine/calibration_policy.py": "ML calibration constants.",
    "tradingbot/ml/shadow/shadow_gate.py": "ML live gate when kernel used.",
    "tradingbot/adapters/multi_engine_router.py": "PA vs VOL/Adaptive select vs probe.",
    "tradingbot/services/pa_production_lock.py": "Lock and Adaptive/VOL defeat.",
    "engine/strategies/price_action_strategy.py": "Live PA signal generation.",
    "tradingbot/config/pa_symbol_tf_presets.py": "gold_ny_sweep / NY hours.",
    "tradingbot/config/strategies.py": "ACTIVE_STRATEGIES priceaction-only.",
    "tradingbot/config/dotenv_loader.py": "Env fill-if-missing (values UNKNOWN).",
    "tradingbot/config/engine_settings.py": "Credential fallbacks (CX-016); secrets not documented.",
    "tradingbot/domain/gold_strategies/m5_london_sweep.py": "Live PA evaluator / SL-TP.",
    "tradingbot/domain/gold_strategies/router.py": "evaluate_gold_setup dispatch.",
    "tradingbot/domain/pa_hardening.py": "apply_setup_hardening can drop setups.",
    "tradingbot/domain/ohlcv.py": "exclude_forming_bar.",
    "tradingbot/pipeline/signal_stage.py": "Call site of exclude_forming_bar.",
    "tradingbot/adapters/legacy_strategy_registry.py": "Router inner PA hop.",
    "tradingbot/adapters/mt5_market_data.py": "Live bar source.",
    "tradingbot/ml/risk_intelligence/risk_types.py": "factory import; v40 quality factor key.",
    "tradingbot/services/kill_switch.py": "Can abort live loop.",
    "scripts/start_bot.py": "Windows start after BAT.",
    "scripts/start_live_daemon.ps1": "Daemon-if-unset flags.",
    "scripts/run_live_watchdog.py": "Supervises --loop --execute.",
    "tradingbot/application/bootstrap.py": "build_kernel_live wiring.",
    "tradingbot/application/live_runner.py": "Live loop / freeze / shutdown.",
    "tradingbot/ml/integration/config.py": "is_ml_kernel_enabled default off.",
    "tradingbot/__main__.py": "CLI --loop --execute; --tf M15 vs live M5.",
    "start/START_BOT.bat": "Documented default Windows entry.",
    "start/_load_env.bat": "Loads .env into cmd; values UNKNOWN.",
}

DO_NOT_WATCH = [
    {
        "path": "tradingbot/domain/gold_strategies/m5_scalp.py",
        "reason": "Not selected on default london_sweep live path; dispatch is in watched router.py.",
        "class": "UNUSED-ON-DEFAULT-LIVE",
    },
    {
        "path": "tradingbot/domain/gold_strategies/m15_intraday.py",
        "reason": "Not looped when get_live_config forces 5m.",
        "class": "UNUSED-ON-DEFAULT-LIVE",
    },
    {
        "path": "tradingbot/domain/gold_strategies/h4_swing.py",
        "reason": "Not looped on default live M5.",
        "class": "UNUSED-ON-DEFAULT-LIVE",
    },
    {
        "path": "tradingbot/ml/research/**",
        "reason": "Research auditors must not enter build_kernel_live.",
        "class": "RESEARCH_ONLY",
    },
]

CANONICAL_DOCS = [
    "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md",
    "docs_v2/01_truth/CHATGPT_BOOTSTRAP.md",
    "docs_v2/01_truth/CURRENT_RUNTIME_STATE.md",
    "docs_v2/01_truth/CONFIGURATION_TRUTH.md",
    "docs_v2/04_strategy/PRICE_ACTION_LIVE_SPEC.md",
    "docs_v2/05_risk/RISKGATE_SPEC.md",
    "docs_v2/07_ml/ML_SYSTEM_STATE.md",
    "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md",
    "docs_v2/99_change_control/DOCUMENTATION_UPDATE_PROTOCOL.md",
    "docs_v2/99_change_control/DOCUMENTATION_IMPACT_MAP.md",
    "docs_v2/01_truth/DOCUMENT_OWNERSHIP_MATRIX.md",
    "docs_v2/01_truth/KNOWLEDGE_CONTRACT.md",
]

ALLOWED_BASELINE_KINDS = frozenset(
    {"canonical", "test_fixture", "explicit_regeneration"}
)

CODE_PATH = re.compile(r"(?:tradingbot|engine|scripts|start)/[A-Za-z0-9_./-]+\.(?:py|ps1|bat)")
DOC_PATH = re.compile(r"docs_v2/[A-Za-z0-9_./-]+\.md")
SYMBOL_REF = re.compile(
    r"`((?:tradingbot|engine|scripts)/[A-Za-z0-9_./-]+\.py)::([A-Za-z_][A-Za-z0-9_]*)`"
)


def _sha(rel: str, *, root: Path = ROOT) -> str | None:
    p = root / rel
    if not p.is_file():
        return None
    return hashlib.sha256(p.read_bytes()).hexdigest()


def current_evidence_revision(
    *,
    watched: list[str] | None = None,
    root: Path = ROOT,
) -> dict[str, str]:
    out: dict[str, str] = {}
    for rel in watched or WATCHED:
        digest = _sha(rel, root=root)
        if digest:
            out[rel] = digest
    return out


def write_snapshot(
    *,
    path: Path | None = None,
    verified_at: str = "2026-09-01",
    baseline_kind: str = "test_fixture",
    allow_canonical: bool = False,
    watched: list[str] | None = None,
    canonical_docs: list[str] | None = None,
    root: Path | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Write a freshness snapshot.

    Canonical path writes require allow_canonical=True and must not use
    baseline_kind='test_fixture'. Pytest must pass a fixture path.
    """
    if baseline_kind not in ALLOWED_BASELINE_KINDS:
        raise ValueError(f"baseline_kind must be one of {sorted(ALLOWED_BASELINE_KINDS)}")
    root = root or ROOT
    dest = path or SNAPSHOT
    canonical = dest.resolve() == SNAPSHOT.resolve()
    if canonical and not allow_canonical:
        raise RuntimeError(
            "Refusing to overwrite canonical freshness snapshot without allow_canonical=True"
        )
    if canonical and baseline_kind == "test_fixture":
        raise RuntimeError("Canonical snapshot cannot be baseline_kind=test_fixture")
    docs = list(canonical_docs if canonical_docs is not None else CANONICAL_DOCS)
    doc_rev = {rel: digest for rel in docs if (digest := _sha(rel, root=root))}
    payload = {
        "verified_at": verified_at,
        "stale_if_code_revision_changes": True,
        "baseline_kind": baseline_kind,
        "evidence_revision": current_evidence_revision(watched=watched, root=root),
        "documentation_revision": doc_rev,
        "canonical_docs": docs,
        "note": note
        or (
            "Working-tree SHA-256 of watched production files at documentation verification."
        ),
    }
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def _load_snapshot(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _bump(status: str, new: str) -> str:
    rank = {"PASS": 0, "UNKNOWN": 1, "STALE": 2, "CONTRADICTED": 3, "BROKEN": 4}
    if rank[new] > rank[status]:
        return new
    return status


def scan_freshness(
    *,
    snapshot_path: Path | None = None,
    watched: list[str] | None = None,
    canonical_docs: list[str] | None = None,
    root: Path | None = None,
    check_docs: bool = True,
) -> dict[str, Any]:
    root = root or ROOT
    watched = list(watched or WATCHED)
    canonical_docs = list(canonical_docs or CANONICAL_DOCS)
    snap_path = snapshot_path or SNAPSHOT
    findings: list[dict[str, Any]] = []
    status = "PASS"

    def bump(new: str) -> None:
        nonlocal status
        status = _bump(status, new)

    missing_watched = [rel for rel in watched if not (root / rel).is_file()]
    if missing_watched:
        findings.append(
            {"id": "missing_watched_source", "files": missing_watched, "status": "BROKEN"}
        )
        bump("BROKEN")

    if check_docs:
        entry_true: list[str] = []
        docs_root = root / "docs_v2"
        if docs_root.is_dir():
            for p in docs_root.rglob("*.md"):
                text = p.read_text(encoding="utf-8")
                if "Canonical-Entry:** true" in text:
                    entry_true.append(p.relative_to(root).as_posix())
        if len(entry_true) == 0:
            findings.append({"id": "no_canonical_entry", "status": "BROKEN"})
            bump("BROKEN")
        elif len(entry_true) > 1:
            findings.append(
                {"id": "duplicate_canonical_entry", "files": entry_true, "status": "CONTRADICTED"}
            )
            bump("CONTRADICTED")

        missing_docs = [rel for rel in canonical_docs if not (root / rel).is_file()]
        if missing_docs:
            findings.append({"id": "missing_canonical_docs", "files": missing_docs, "status": "BROKEN"})
            bump("BROKEN")

        broken_docs: list[str] = []
        broken_code: list[str] = []
        missing_symbols: list[str] = []
        missing_status: list[str] = []
        missing_verified: list[str] = []
        corpus_parts: list[str] = []
        for rel in canonical_docs:
            path = root / rel
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            corpus_parts.append(text)
            if "**Status:**" not in text and "- **Status:**" not in text:
                missing_status.append(rel)
            if not re.search(r"Last verified.{0,8}(\d{4}-\d{2}-\d{2})", text, re.I):
                missing_verified.append(rel)
            for doc in DOC_PATH.findall(text):
                if not (root / doc).is_file():
                    broken_docs.append(f"{rel} -> {doc}")
            for code in CODE_PATH.findall(text):
                if not (root / code).is_file():
                    broken_code.append(f"{rel} -> {code}")
            for code, sym in SYMBOL_REF.findall(text):
                src = root / code
                if src.is_file() and sym not in src.read_text(encoding="utf-8", errors="replace"):
                    missing_symbols.append(f"{rel} -> {code}::{sym}")

        if broken_docs or broken_code:
            findings.append(
                {"id": "broken_references", "docs": broken_docs, "code": broken_code, "status": "BROKEN"}
            )
            bump("BROKEN")
        if missing_symbols:
            findings.append({"id": "missing_symbols", "items": missing_symbols, "status": "BROKEN"})
            bump("BROKEN")
        if missing_status:
            findings.append({"id": "missing_status", "files": missing_status, "status": "STALE"})
            bump("STALE")
        if missing_verified:
            findings.append({"id": "missing_verified_at", "files": missing_verified, "status": "STALE"})
            bump("STALE")

        corpus = "\n".join(corpus_parts)
        if "XAUUSD_i" not in corpus or "999" not in corpus or "gold_ny_sweep" not in corpus:
            findings.append({"id": "missing_high_impact_claims", "status": "BROKEN"})
            bump("BROKEN")

        if "london_sweep" in corpus and "NY 15" in corpus:
            findings.append(
                {
                    "id": "london_vs_ny_named",
                    "status": "CONTRADICTED",
                    "note": "Named contradiction; documented as CX-001 — not a verifier failure if registry exists.",
                }
            )

        pa = root / "docs_v2/04_strategy/PRICE_ACTION_LIVE_SPEC.md"
        boot = root / "docs_v2/01_truth/CHATGPT_BOOTSTRAP.md"
        entry = root / "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md"
        if pa.is_file() and boot.is_file():
            pa_text = pa.read_text(encoding="utf-8")
            boot_text = boot.read_text(encoding="utf-8")
            if "gold_ny_sweep" in pa_text and "gold_ny_sweep" not in boot_text:
                findings.append({"id": "preset_divergence", "status": "CONTRADICTED"})
                bump("CONTRADICTED")
            if entry.is_file() and "XAUUSD_i" in boot_text and "XAUUSD_i" not in entry.read_text(
                encoding="utf-8"
            ):
                findings.append({"id": "symbol_divergence", "status": "CONTRADICTED"})
                bump("CONTRADICTED")
    else:
        entry_true = []
        corpus = ""

    snap = _load_snapshot(snap_path)
    if snap is None:
        findings.append({"id": "no_snapshot", "status": "UNKNOWN"})
        bump("UNKNOWN")
    else:
        current = current_evidence_revision(watched=watched, root=root)
        snap_rev = snap.get("evidence_revision") or {}
        stale_files = [rel for rel, digest in current.items() if snap_rev.get(rel) != digest]
        new_watched = [rel for rel in current if rel not in snap_rev]
        if new_watched and not stale_files:
            stale_files = new_watched
        if stale_files:
            findings.append({"id": "code_revision_changed", "files": stale_files, "status": "STALE"})
            bump("STALE")
        snap_docs = snap.get("documentation_revision") or {}
        if snap_docs:
            doc_current = {
                rel: digest
                for rel in canonical_docs
                if (digest := _sha(rel, root=root))
            }
            changed_docs = [rel for rel, digest in doc_current.items() if snap_docs.get(rel) != digest]
            if changed_docs:
                findings.append(
                    {
                        "id": "documentation_changed",
                        "files": changed_docs,
                        "status": "WARN",
                        "note": "Canonical docs differ from snapshot documentation_revision; not the same as code STALE.",
                    }
                )
        deleted = [
            rel
            for rel in snap_rev
            if rel in watched and not (root / rel).is_file()
        ]
        if deleted:
            findings.append({"id": "deleted_watched_source", "files": deleted, "status": "BROKEN"})
            bump("BROKEN")

    return {
        "status": status,
        "canonical_entry_files": entry_true if check_docs else [],
        "findings": findings,
        "high_impact_present": {
            "XAUUSD_i": "XAUUSD_i" in corpus,
            "999": "999" in corpus,
            "gold_ny_sweep": "gold_ny_sweep" in corpus,
            "USE_ML_KERNEL": "USE_ML_KERNEL" in corpus,
        }
        if check_docs
        else {},
        "snapshot_path": str(snap_path),
        "stale_if_code_revision_changes": True,
        "watched_count": len(watched),
        "missing_watched": missing_watched,
    }

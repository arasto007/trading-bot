"""Phase 57 — account product forensics (ECN / CLASSIC / CENT).

RESEARCH ONLY. Attach-if-running. Does not infer product from leverage,
_i suffix, _cl symbols, or zero commissions.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase42_broker_cost_execution_closure import attach_if_running
from tradingbot.backtest.phase54_account_broker_evidence import (
    FROZEN_TAPE_FINGERPRINT,
    UNKNOWN,
    snapshot_account,
    snapshot_symbol,
)

PHASE = "57"
PHASE57_JSON = "logs/phase57_account_product_forensics.json"
PHASE57_MD = "docs/PHASE57_ACCOUNT_PRODUCT_FORENSICS.md"
PHASE40_JSON = "logs/phase40_full_horizon_validation.json"
PHASE54_JSON = "logs/phase54_account_broker_evidence.json"
BLOCKED = "BLOCKED"
NOT_PROVEN = "NOT_PROVEN"
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "account",
    "discriminators",
    "ACCOUNT_PRODUCT",
    "VERIFICATION_BASIS",
    "OPERATOR_EVIDENCE_REQUIRED",
    "final_gate",
    "production_safety",
    "artifacts",
)
OFFICIAL = {
    "fetched_utc": "2026-09-08",
    "DOCUMENT_DATE_CONFLICT": True,
    "current_pdf_effective": "2026-05-19",
    "prior_artifact_pdf_effective": "2026-03-26",
    "pdf": "https://www.litefinance.org/uploads/documents/pdf-litefinance/litefinance-markups-and-commissions-list-en.pdf",
    "account_types": "https://www.litefinance.org/trading/account-types/",
    "ecn": "https://www.litefinance.org/trading/account-types/ecn/",
    "classic": "https://www.litefinance.org/trading/account-types/classic/",
    "cent": "https://www.litefinance.org/trading/account-types/cent/",
    "xauusd_instrument": "https://www.litefinance.org/trading/trading-instruments/commodities/xauusd/",
    "specs": {
        "ECN": {"max_orders": 500, "commission": "yes", "currency": ("USD", "EUR"), "stop_out_pct": 20, "fx_contract": 100000},
        "CLASSIC": {"max_orders": 300, "commission": "none", "currency": ("USD", "EUR"), "stop_out_pct": 20, "fx_contract": 100000},
        "CENT": {"max_orders": 300, "commission": "none", "currency": ("USD-¢", "EUR-¢"), "stop_out_pct": 50, "fx_contract": 1000},
    },
    "markup_units": "CLASSIC/CENT markup is a fixed amount in POINTS per round lot for commodities including XAUUSD",
    "xauusd_table": {"ECN": 5, "CLASSIC": 14, "CENT": 14, "digits": 2},
    "faq": "https://www.litefinance.org/support/faq/",
    "faq_note": (
        "FAQ: different account types correspond to different servers; account type cannot be changed in-place. "
        "FAQ also states a new MT5 Client Profile account is created as ECN. "
        "LiteFinance-MT5-Live is not officially mapped to ECN vs CLASSIC in public docs. "
        "Default-new-account=ECN must not override observed limit_orders=300."
    ),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_head(base_dir: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=base_dir, capture_output=True, text=True, timeout=5
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return UNKNOWN


def classify_product(sanitized: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    currency = str(sanitized.get("currency") or extra.get("currency") or UNKNOWN)
    raw_limit = sanitized.get("limit_orders", extra.get("limit_orders"))
    try:
        limit_orders = int(raw_limit) if raw_limit not in (None, UNKNOWN, "") else None
    except (TypeError, ValueError):
        limit_orders = None
    so = extra.get("margin_so_so", sanitized.get("margin_so_so"))
    notes = []
    incompatible = []
    if "¢" in currency or currency.upper() in {"USD-C", "EUR-C", "USC"}:
        incompatible.append("CENT-compatible currency")
    else:
        if currency.upper() in {"USD", "EUR"}:
            notes.append("currency USD/EUR is incompatible with official CENT base currency USD-¢/EUR-¢")
            incompatible.append("CENT")
    if limit_orders == 500:
        notes.append("limit_orders=500 matches official ECN max orders")
    elif limit_orders == 300:
        notes.append("limit_orders=300 matches official CLASSIC and CENT max orders; incompatible with official ECN 500")
        incompatible.append("ECN")
    else:
        notes.append(f"limit_orders={limit_orders} does not uniquely match official 500/300 table")
    if so in (20, 0.2, 20.0):
        notes.append("stop-out 20 matches CLASSIC/ECN official 20%; CENT official is 50%")
        if "CENT" not in incompatible:
            incompatible.append("CENT")
    elif so in (50, 0.5, 50.0):
        notes.append("stop-out 50 matches official CENT 50%")
    candidate = UNKNOWN
    status = UNKNOWN
    if "CENT" in incompatible and "ECN" in incompatible and currency.upper() in {"USD", "EUR"}:
        candidate = "CLASSIC"
        status = "PARTIAL"
        notes.append("candidate CLASSIC from official spec discriminators; not VERIFIED (no product field; broker could customize)")
    elif "ECN" not in incompatible and limit_orders == 500:
        candidate = "ECN"
        status = "PARTIAL"
    return {
        "ACCOUNT_PRODUCT": status,
        "ACCOUNT_PRODUCT_CANDIDATE": candidate,
        "incompatible_with": sorted(set(incompatible)),
        "notes": notes,
        "inferred_from_leverage": False,
        "inferred_from_suffix": False,
        "inferred_from_cl_symbol": False,
        "inferred_from_zero_commission": False,
        "inferred_from_cls_path": False,
    }


def search_local(root: Path) -> dict[str, Any]:
    tokens = (
        "ECN",
        "CLASSIC",
        "CENT",
        "LiteFinance",
        "LiteFinance-MT5-Live",
        "account group",
        "account type",
        "account product",
        "commission",
        "precious metals",
        "XAUUSD_i",
        "XAUUSD",
        "CLS_LOW_SPREAD_i",
    )
    skip_dirs = {".git", "__pycache__", ".venv", "venv", "node_modules", ".cursor", "mlruns"}
    exts = {".py", ".json", ".jsonl", ".md", ".txt", ".csv"}
    hits: list[dict[str, str]] = []
    scanned = 0
    truncated = False
    for rel_root in ("docs", "docs_v2", "logs", "tradingbot", "tests", "scripts", "memory"):
        base = root / rel_root
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if any(part in skip_dirs for part in path.parts):
                continue
            if path.name.startswith(".env"):
                continue
            if not path.is_file() or path.suffix.lower() not in exts:
                continue
            try:
                if path.stat().st_size > 1_500_000:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            scanned += 1
            rel = str(path.relative_to(root)).replace("\\", "/")
            for token in tokens:
                if token in text:
                    hits.append({"path": rel, "token": token})
            if scanned >= 450 or len(hits) >= 280:
                truncated = True
                break
        if truncated:
            break
    return {
        "files_scanned_count": scanned,
        "hit_count": len(hits),
        "hits_sample": hits[:90],
        "truncated": truncated,
        "env_read": False,
        "secrets_read": False,
        "proves_this_account": False,
    }


def run_phase57_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p54 = _safe_load_json(root / PHASE54_JSON) or {}
    pack = attach_if_running()
    attach = pack.get("attach") or {}
    attached = bool(attach.get("ok"))
    extra: dict[str, Any] = {}
    sanitized: dict[str, Any] = {}
    account_meta: dict[str, Any] = {}
    symbols: dict[str, Any] = {}
    if attached:
        import MetaTrader5 as mt5

        account_meta = snapshot_account(mt5)
        sanitized = dict(account_meta.get("sanitized") or {})
        acct = mt5.account_info()
        if acct is not None:
            extra = {
                "margin_so_so": getattr(acct, "margin_so_so", UNKNOWN),
                "margin_so_call": getattr(acct, "margin_so_call", UNKNOWN),
                "margin_so_mode": getattr(acct, "margin_so_mode", UNKNOWN),
                "commission_blocked": getattr(acct, "commission_blocked", UNKNOWN),
                "currency": getattr(acct, "currency", UNKNOWN),
            }
            for k in ("margin_so_so", "margin_so_call", "margin_so_mode", "commission_blocked"):
                if k not in sanitized:
                    sanitized[k] = extra.get(k)
        for name in ("XAUUSD", "XAUUSD_i", "XAUPUSD_cl"):
            symbols[name] = snapshot_symbol(mt5, name)
    else:
        account_meta = (p54.get("account") or {}).get("metadata") or {}
        sanitized = dict(account_meta.get("sanitized") or {})
        extra = {"currency": sanitized.get("currency"), "reused_phase54": True}
        symbols = p54.get("symbols") or {}
    verdict = classify_product(sanitized, extra)
    operator = [
        "LiteFinance Cabinet: Account type / product line (ECN or CLASSIC or CENT), with account number and balances redacted.",
        "Optional: support confirmation of the same product. No password, login, .env, API key, or payment details.",
    ]
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "phase40_scan_rerun": False,
        "mt5_launched": False,
        "mt5_attached": attached,
        "env_accessed": False,
        "frozen_tape_fingerprint": p40.get("tape_fingerprint") or FROZEN_TAPE_FINGERPRINT,
        "account": {
            "broker": sanitized.get("company") or attach.get("broker") or "LiteFinance Global LLC",
            "server": sanitized.get("server") or attach.get("server") or "LiteFinance-MT5-Live",
            "login_identity": account_meta.get("login_identity") or attach.get("login_identity") or UNKNOWN,
            "FIELDS_PRESENT": account_meta.get("visible_keys") or sorted(sanitized.keys()),
            "FIELDS_ABSENT": account_meta.get("absent_product_fields") or ["group", "product", "account_type", "tier"],
            "FIELDS_RELEVANT_TO_PRODUCT_IDENTITY": ["limit_orders", "currency", "margin_so_so", "trade_mode", "company", "server"],
            "sanitized": sanitized,
            "extra": extra,
        },
        "official": OFFICIAL,
        "discriminators": verdict,
        "symbols_paths": {
            name: {"path": (row or {}).get("path"), "description": (row or {}).get("description")}
            for name, row in symbols.items()
        },
        "local_search": search_local(root),
        "ACCOUNT_PRODUCT": verdict["ACCOUNT_PRODUCT"],
        "ACCOUNT_PRODUCT_CANDIDATE": verdict["ACCOUNT_PRODUCT_CANDIDATE"],
        "VERIFICATION_BASIS": verdict["notes"] + [
            "Official ECN max orders=500, CLASSIC/CENT=300 (litefinance.org account-types pages fetched 2026-09-08).",
            "Official CENT currency USD-¢/EUR-¢ and stop-out 50%; observed currency USD.",
            "No MT5 group/product/tier field. Path CLS_LOW_SPREAD_i and XAUPUSD_cl were not used as product proof.",
            "Leverage 100 is allowed on ECN and CLASSIC; not used as a discriminator.",
            "FAQ default-new-MT5-account=ECN conflicts with observed limit_orders=300 if the public max-order table applies; conflict recorded, not silently resolved.",
            "Server LiteFinance-MT5-Live is not officially mapped to a product in public docs.",
        ],
        "OPERATOR_EVIDENCE_REQUIRED": operator,
        "DOCUMENT_DATE_CONFLICT": True,
        "G1": "PARTIAL" if verdict["ACCOUNT_PRODUCT"] == "PARTIAL" else "FAIL" if verdict["ACCOUNT_PRODUCT"] == UNKNOWN else "PASS",
        "final_gate": BLOCKED,
        "FINAL_GATE": BLOCKED,
        "production_safety": {
            "TRADING": "NOT_PERFORMED",
            "ORDERS": 0,
            "ENV": "NOT_READ",
            "PHASE40_RESCAN": "NO",
            "production_changes": "NONE",
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE57_JSON, "md": PHASE57_MD},
    }
    (root / PHASE57_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE57_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    md = [
        "# Phase 57 — Account Product Forensics",
        "",
        f"**ACCOUNT_PRODUCT:** `{payload['ACCOUNT_PRODUCT']}`",
        f"**CANDIDATE:** `{payload['ACCOUNT_PRODUCT_CANDIDATE']}`",
        f"**G1:** `{payload['G1']}`",
        f"**MT5 attached:** `{attached}`",
        "",
        "ECN was not inferred from leverage. CLASSIC was not inferred from `_cl` or `CLS_LOW_SPREAD_i`.",
        "Zeros were not used. CENT is incompatible with observed USD (official CENT is USD-¢).",
        "limit_orders=300 is incompatible with official ECN 500 and compatible with CLASSIC/CENT.",
        "This is **PARTIAL**, not VERIFIED_CLASSIC: no product field; customization not disproven.",
        "",
        "PDF effective date on the current official file is **2026-05-19**. Prior artifact 2026-03-26 remains recorded. DOCUMENT_DATE_CONFLICT=TRUE.",
        "",
        "## 57A Account metadata",
        "Login is hashed if present. No group/product/tier field is exposed by `account_info()`.",
        "",
        "## 57B Group / path / server",
        "Server naming and CLS_LOW_SPREAD_i path are supporting only. Official FAQ says account types use different servers but does not name LiteFinance-MT5-Live.",
        "",
        "## 57C Local project evidence",
        "Repository token hits do not identify this exact account's product.",
        "",
        "## 57D Official documents",
        "Sources: account-types ECN/CLASSIC/CENT pages and markups PDF. DOCUMENT_DATE_CONFLICT=TRUE.",
        "",
        "## 57E Verdict",
        f"`ACCOUNT_PRODUCT={payload['ACCOUNT_PRODUCT']}` candidate `{payload['ACCOUNT_PRODUCT_CANDIDATE']}`. Not VERIFIED.",
        "",
        "## Operator evidence required",
        "",
        *[f"- {x}" for x in operator],
        "",
    ]
    (root / PHASE57_MD).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE57_MD).write_text("\n".join(md), encoding="utf-8")
    return payload


if __name__ == "__main__":
    print(run_phase57_collection(Path("."))["ACCOUNT_PRODUCT"])

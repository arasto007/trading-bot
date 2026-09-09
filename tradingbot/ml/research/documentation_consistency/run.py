"""Run documentation consistency scan and write JSON reports (offline)."""

from __future__ import annotations

import json
from pathlib import Path

from tradingbot.ml.research.documentation_consistency.scanner import run_scan
from tradingbot.ml.research.documentation_system_audit.run import run_documentation_system_audit

ROOT = Path(__file__).resolve().parents[4]


def _write(rel: str, payload: object) -> None:
    path = ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def write_auxiliary_reports(scan: dict) -> None:
    inv = scan["invariants"]
    _write(
        "data/ml/reports/configuration_truth/config_map.json",
        {
            "scope": "code_defaults_and_this_process",
            "secrets_not_read": True,
            "values": inv,
            "notes": [
                "operator .env UNKNOWN",
                "ENABLE_ML_SHADOW code default false vs daemon true",
            ],
        },
    )
    _write(
        "data/ml/reports/production_boundary/boundary.json",
        {
            "production_live_owner": "priceaction",
            "ml_kernel_default": "off",
            "shadow": ["VOL_REGIME_probe", "ADAPTIVE_REGIME_probe", "ML_shadow_wrap"],
            "research_packages_not_in_bootstrap": scan["research_isolation"],
        },
    )
    _write(
        "data/ml/reports/knowledge_consistency/scan.json",
        {
            "ok": scan["ok"],
            "failures": scan["failures"],
            "contradiction_ids": scan["contradictions"]["ids"],
            "v41_bundle": scan["v41_bundle"],
        },
    )


def main() -> dict:
    audit = run_documentation_system_audit(write_reports=True)
    scan = run_scan()
    write_auxiliary_reports(scan)
    out = ROOT / "data" / "ml" / "reports" / "knowledge_consistency"
    out.mkdir(parents=True, exist_ok=True)
    (out / "documentation_scan.json").write_text(
        json.dumps(scan, indent=2, default=str), encoding="utf-8"
    )
    scan["documentation_system_audit_counts"] = audit.get("counts")
    return scan


if __name__ == "__main__":
    result = main()
    print(json.dumps({"ok": result["ok"], "failures": result["failures"]}, indent=2))
    raise SystemExit(0 if result["ok"] else 1)

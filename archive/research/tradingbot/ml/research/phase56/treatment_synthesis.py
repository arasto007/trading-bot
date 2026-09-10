"""Phase 56 — treatment synthesis & re-gate (research only)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
ARTIFACTS = ROOT / "tradingbot" / "ml" / "research" / "phase56" / "artifacts"
V7_PATH = ROOT / "tradingbot" / "ml" / "research" / "phase49" / "artifacts" / "dataset_v7_ml_signals.parquet"


def _load(name: str) -> dict:
    p = ROOT / name
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def synthesize_treatment(r52: dict, r53: dict, r54: dict, r55: dict) -> dict[str, Any]:
    findings: list[str] = []
    blockers: list[str] = []

    label_match = float(r52.get("stored_vs_production_match_pct") or 0)
    if label_match < 70:
        findings.append(f"Label-production mismatch {label_match:.1f}% — dataset v8 rebuild recommended")
        blockers.append("LABEL_MISALIGNMENT")
    else:
        findings.append(f"Labels reasonably aligned ({label_match:.1f}%)")

    agg = (r53.get("aggregate") or {})
    edge_loss = float(agg.get("edge_loss_pct") or 0)
    if edge_loss > 70:
        findings.append(f"Execution funnel destroys {edge_loss:.1f}% of raw signals")
        blockers.append("EXECUTION_FUNNEL_EDGE_LOSS")
    else:
        findings.append(f"Funnel capture rate {agg.get('capture_rate_pct', 0)}%")

    best_pf = float((r54.get("model_sweep") or {}).get("best_mean_pf") or 0)
    best_model = (r54.get("model_sweep") or {}).get("best_model", "random_forest")
    if best_pf < 1.0:
        findings.append(f"Best model {best_model} mean PF {best_pf:.2f} — ML edge insufficient")
        blockers.append("ML_PREDICTIVE_WEAK")
    else:
        findings.append(f"Best model {best_model} mean PF {best_pf:.2f}")

    noise_n = int(r55.get("noise_feature_count") or 0)
    if noise_n >= 8:
        findings.append(f"{noise_n} low-importance features flagged for pruning")
    else:
        findings.append("Feature set moderately clean")

    return {"findings": findings, "blockers": blockers, "best_model": best_model}


def run_phase56() -> dict:
    from tradingbot.ml.research.phase36.build_dataset_v3 import feature_columns
    from tradingbot.ml.research.phase50.strict_walk_forward import strict_walk_forward

    r52 = _load("phase52_final_report.json")
    r53 = _load("phase53_final_report.json")
    r54 = _load("phase54_final_report.json")
    r55 = _load("phase55_final_report.json")

    if not r52:
        return {"verdict": "INSUFFICIENT_DATA", "error": "run phase52 first"}

    synthesis = synthesize_treatment(r52, r53, r54, r55)
    best_model = synthesis.get("best_model", "random_forest")

    re_gate: dict[str, Any] = {"verdict": "SKIPPED", "reason": "v7 or prior phases missing"}
    if V7_PATH.is_file() and r54:
        df = pd.read_parquet(V7_PATH)
        feats = feature_columns(df)
        noise = set(r55.get("noise_features") or [])
        trimmed = [c for c in feats if c not in noise] if noise else feats
        re_gate = strict_walk_forward(df, "label_v3", trimmed, model_name=best_model)

    gate_passed = bool(re_gate.get("gate_passed"))
    if gate_passed:
        verdict = "TREATMENT_REGATE_PASS"
        integration = "INTEGRATION_REVIEW_ELIGIBLE"
    elif float(re_gate.get("mean_pf") or 0) >= 1.0:
        verdict = "TREATMENT_REGATE_MARGINAL"
        integration = "CONTINUE_RESEARCH_HIGH_PRIORITY"
    else:
        verdict = "TREATMENT_REGATE_FAIL"
        integration = "BLOCK_PRODUCTION_INTEGRATION"

    return {
        "now": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verdict": verdict,
        "integration_gate": integration,
        "synthesis": synthesis,
        "re_gate": {
            "model": best_model,
            "features_used": re_gate.get("features"),
            "mean_pf": re_gate.get("mean_pf"),
            "mean_auc": re_gate.get("mean_auc"),
            "gate_passed": gate_passed,
            "gates": re_gate.get("gates"),
            "verdict": re_gate.get("verdict"),
        },
        "phase_reports_used": {
            "phase52": r52.get("verdict"),
            "phase53": r53.get("verdict"),
            "phase54": r54.get("verdict"),
            "phase55": r55.get("verdict"),
        },
        "production_deploy_blocked": not gate_passed,
    }


def write_all(data: dict) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / "treatment_synthesis.json").write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    print("  wrote phase56/artifacts/treatment_synthesis.json", flush=True)
    report = {
        "phase": "56",
        "title": "Treatment Synthesis & Re-gate",
        "title_fa": "ترکیب درمان و بازگشت gate",
        "timestamp_utc": data["now"],
        "verdict": data["verdict"],
        "integration_gate": data.get("integration_gate"),
        "synthesis": data.get("synthesis"),
        "re_gate": data.get("re_gate"),
        "production_deploy_blocked": data.get("production_deploy_blocked"),
    }
    (ROOT / "phase56_final_report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("  wrote phase56_final_report.json", flush=True)


def main() -> None:
    data = run_phase56()
    write_all(data)
    print(json.dumps({
        "verdict": data["verdict"],
        "integration_gate": data.get("integration_gate"),
        "re_gate": data.get("re_gate"),
    }, indent=2))


if __name__ == "__main__":
    main()

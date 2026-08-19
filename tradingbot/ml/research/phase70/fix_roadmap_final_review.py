"""Phase 70 — FIX Roadmap Final Gate Review (closure, research only).

Synthesize phases 62-68 + FIX_ROADMAP.json into a final verdict.
NO production code changes — documentation and status updates only.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

ARTIFACTS = ROOT / "tradingbot" / "ml" / "research" / "phase70" / "artifacts"

PHASE_REPORTS = {
    "62": ROOT / "phase62_final_report.json",
    "63": ROOT / "phase63_final_report.json",
    "64": ROOT / "phase64_final_report.json",
    "65": ROOT / "phase65_final_report.json",
    "66": ROOT / "phase66_final_report.json",
    "67": ROOT / "phase67_final_report.json",
    "68": ROOT / "phase68_final_report.json",
}

PRODUCTION_GATES = {
    "mean_auc_ge": 0.55,
    "honest_pf_ge": 1.3,
    "honest_pf_min_trades_per_window": 30,
    "shadow_pf_ge": 1.0,
    "capture_rate_hc_pct_ge": 20.0,
}


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Required report missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _phase_summary(phase: str, report: dict[str, Any]) -> dict[str, Any]:
    return {
        "phase": phase,
        "title_en": report.get("title"),
        "title_fa": report.get("title_fa"),
        "verdict": report.get("verdict"),
        "timestamp_utc": report.get("timestamp_utc"),
        "gate_passed": report.get("gate_passed"),
        "research_only": report.get("research_only", True),
    }


def _execution_fixes(phase62: dict, phase63: dict, phase64: dict) -> dict[str, Any]:
    mismatch = (phase62.get("root_cause") or {}).get("engine_id_mismatch") or {}
    return {
        "status": "FIXED_IN_SHADOW",
        "primary_issue": "TradeQuality engine ID mismatch",
        "active_router_engine": mismatch.get("active_router_engine", "trend_rf_v41"),
        "regime_quality_recognizes": mismatch.get("regime_quality_recognizes", "trend_rf_v40"),
        "shadow_fix": {
            "policy": "map_to_v40",
            "source_phase": "63",
            "capture_rate_pct": (phase63.get("best_shadow_policy") or {}).get("capture_rate_pct")
            or (phase63.get("gate_check") or {}).get("capture_actual_pct")
            or 93.21,
            "shadow_pf": (phase63.get("best_shadow_policy") or {}).get("pf_proxy_label_v3", {}).get("pf")
            or (phase63.get("gate_check") or {}).get("shadow_pf_actual")
            or 0.3932,
        },
        "adaptive_risk": {
            "status": "REVIEWED_NO_CHANGE",
            "source_phase": "64",
            "worth_fixing": (phase64.get("conclusion") or {}).get("worth_fixing_ar", False),
            "phase68_policy": "keep_production_ar",
        },
        "production_deploy_required": True,
        "note_en": (
            "Engine alias restores ~93% capture in shadow. Production still blocks signals "
            "until regime_quality.py recognizes trend_rf_v41 or router uses trend_rf_v40."
        ),
        "note_fa": (
            "alias موتور در سایه capture را به ~۹۳٪ برمی‌گرداند. تولید هنوز سیگنال‌ها را "
            "مسدود می‌کند تا regime_quality.py موتور trend_rf_v41 را بشناسد."
        ),
    }


def _ml_remaining(phase65: dict, phase66: dict, phase67: dict, phase68: dict) -> dict[str, Any]:
    best = phase68.get("best_combined_config") or {}
    assessment = phase68.get("fix_roadmap_assessment") or {}
    return {
        "status": "BROKEN",
        "primary_issue": "Predictive edge near random — honest PF far below gate",
        "best_metrics": {
            "mean_auc": best.get("mean_auc", 0.5151),
            "mean_pf_honest": best.get("mean_pf_honest", 0.5676),
            "shadow_pf": best.get("shadow_pf", 0.3932),
            "capture_rate_pct": best.get("capture_rate_pct", 93.35),
            "config_id": best.get("config_id", "A"),
        },
        "ml_phase_outcomes": {
            "65": {"verdict": phase65.get("verdict"), "auc_gate": phase65.get("auc_gate_pass")},
            "66": {
                "verdict": phase66.get("verdict"),
                "best_auc": (phase66.get("best_experiment") or {}).get("mean_auc"),
                "best_honest_pf": (phase66.get("best_experiment") or {}).get("mean_pf_honest"),
            },
            "67": {
                "verdict": phase67.get("verdict"),
                "best_config": (phase67.get("best_config") or {}).get("config_id"),
                "both_gates_pass": phase67.get("any_both_gates_pass"),
            },
        },
        "decoupling_observed": True,
        "note_en": assessment.get(
            "primary_remaining_blocker_en",
            "ML predictive edge too weak — honest PF ~0.43-0.57, shadow PF ~0.39",
        ),
        "note_fa": assessment.get(
            "primary_remaining_blocker_fa",
            "edge پیش‌بینی ML ضعیف — PF صادق ~۰.۴۳-۰.۵۷، shadow PF ~۰.۳۹",
        ),
    }


def _gate_results_table(phase68: dict) -> list[dict[str, Any]]:
    best = phase68.get("best_combined_config") or {}
    config_a = next(
        (c for c in phase68.get("config_results") or [] if c.get("config_id") == best.get("config_id", "A")),
        None,
    )
    gates = ((config_a or {}).get("gate_evaluation") or {}).get("gates") or {}

    rows: list[dict[str, Any]] = []
    mapping = [
        ("mean_auc", "auc_ge_0_55", "mean_auc_ge", ">="),
        ("honest_pf", "honest_pf_ge_1_3", "honest_pf_ge", ">="),
        ("shadow_pf", "shadow_pf_ge_1_0", "shadow_pf_ge", ">="),
        ("capture_rate_hc_pct", "capture_rate_hc_pct_ge_20", "capture_rate_hc_pct_ge", ">="),
    ]
    for gate_name, gate_key, target_key, op in mapping:
        g = gates.get(gate_key) or {}
        rows.append({
            "gate": gate_name,
            "operator": op,
            "target": g.get("target", PRODUCTION_GATES.get(target_key)),
            "actual": g.get("actual"),
            "pass": bool(g.get("pass")),
            "config_id": best.get("config_id", "A"),
        })

    all_pass = all(r["pass"] for r in rows) if rows else False
    return rows if rows else [
        {
            "gate": "mean_auc",
            "operator": ">=",
            "target": PRODUCTION_GATES["mean_auc_ge"],
            "actual": best.get("mean_auc"),
            "pass": False,
            "config_id": best.get("config_id", "A"),
        },
        {
            "gate": "honest_pf",
            "operator": ">=",
            "target": PRODUCTION_GATES["honest_pf_ge"],
            "actual": best.get("mean_pf_honest"),
            "pass": False,
            "config_id": best.get("config_id", "A"),
        },
        {
            "gate": "shadow_pf",
            "operator": ">=",
            "target": PRODUCTION_GATES["shadow_pf_ge"],
            "actual": best.get("shadow_pf"),
            "pass": False,
            "config_id": best.get("config_id", "A"),
        },
        {
            "gate": "capture_rate_hc_pct",
            "operator": ">=",
            "target": PRODUCTION_GATES["capture_rate_hc_pct_ge"],
            "actual": best.get("capture_rate_pct"),
            "pass": True,
            "config_id": best.get("config_id", "A"),
        },
    ] if not all_pass else rows


def _integration_status(phase68: dict) -> dict[str, Any]:
    phase69 = phase68.get("phase69_verdict") or {}
    proceed = bool(phase69.get("proceed_to_phase69"))
    return {
        "phase69": {
            "status": "SKIPPED",
            "reason_en": phase69.get(
                "rationale_en",
                "Phase68 gates failed (0/4 pass). Paper trading not justified on evidence.",
            ),
            "reason_fa": phase69.get(
                "rationale_fa",
                "gateهای فاز ۶۸ پاس نشد (۰/۴). معاملات کاغذی با این شواهد توجیه نمی‌شود.",
            ),
            "would_require": "all_production_gates_pass_from_phase68",
            "proceed_to_phase69": proceed,
        },
        "phase70": {
            "status": "BLOCKED",
            "reason_en": (
                "Production gate review runs only when ALL gates pass. "
                "Current best config passes 1/4 gates (capture only). "
                "Closure review issued instead of production approval."
            ),
            "reason_fa": (
                "بازبینی gate تولید فقط وقتی همه gateها پاس شوند اجرا می‌شود. "
                "بهترین کانفیگ فعلی ۱/۴ gate را پاس کرد (فقط capture). "
                "به‌جای تأیید تولید، گزارش بسته‌شدن صادر شد."
            ),
            "production_deploy": "BLOCKED",
        },
    }


def _future_recommendations() -> list[dict[str, str]]:
    return [
        {
            "id": "R1",
            "category": "execution_only",
            "title_en": "Deploy TQ engine-ID fix to production",
            "title_fa": "اعمال fix شناسه موتور TQ در تولید",
            "description_en": (
                "Register trend_rf_v41 in regime_quality.py or align router to trend_rf_v40. "
                "Restores capture; does NOT create ML edge."
            ),
            "description_fa": (
                "ثبت trend_rf_v41 در regime_quality.py یا هم‌راستایی router با trend_rf_v40. "
                "capture را برمی‌گرداند؛ edge ML ایجاد نمی‌کند."
            ),
            "effort": "low",
            "expected_impact": "capture_restored_pf_still_weak",
        },
        {
            "id": "R2",
            "category": "new_data",
            "title_en": "Expand dataset beyond current TREND subset",
            "title_fa": "گسترش دیتاست فراتر از زیرمجموعه TREND فعلی",
            "description_en": (
                "Add order-flow, spread, session microstructure, or cross-asset features. "
                "Current 10f features show high noise (phase55)."
            ),
            "description_fa": (
                "افزودن order-flow، spread، microstructure سشن، یا ویژگی‌های cross-asset. "
                "۱۰ ویژگی فعلی نویز بالا دارند (فاز ۵۵)."
            ),
            "effort": "high",
            "expected_impact": "uncertain_auc_lift",
        },
        {
            "id": "R3",
            "category": "new_strategy",
            "title_en": "Pivot strategy — non-TREND regimes or rule-based filter",
            "title_fa": "تغییر استراتژی — رژیم‌های غیر TREND یا فیلتر rule-based",
            "description_en": (
                "TREND-only RF at ~0.51 AUC may lack edge. Test RANGE/BREAKOUT regimes "
                "or hybrid rule+ML gates before further ML tuning."
            ),
            "description_fa": (
                "RF فقط-TREND با AUC ~۰.۵۱ ممکن است edge نداشته باشد. "
                "رژیم‌های RANGE/BREAKOUT یا gate ترکیبی rule+ML را امتحان کنید."
            ),
            "effort": "medium",
            "expected_impact": "strategy_pivot_required",
        },
        {
            "id": "R4",
            "category": "external_model",
            "title_en": "External or alternative model architecture",
            "title_fa": "مدل خارجی یا معماری جایگزین",
            "description_en": (
                "Gradient boosting, temporal CNN/LSTM, or pre-trained market embeddings. "
                "Ensemble (phase67) did not beat baseline RF for tradeable PF."
            ),
            "description_fa": (
                "Gradient boosting، CNN/LSTM زمانی، یا embeddingهای ازپیش‌آموزش‌دیده. "
                "ensemble (فاز ۶۷) برای PF قابل معامله از RF پایه بهتر نشد."
            ),
            "effort": "high",
            "expected_impact": "research_required_no_guarantee",
        },
        {
            "id": "R5",
            "category": "observational",
            "title_en": "Optional observational paper (no gate expectation)",
            "title_fa": "کاغذی مشاهده‌ای اختیاری (بدون انتظار gate)",
            "description_en": (
                "Forward paper with shadow TQ alias for slippage/spread learning only. "
                "NOT a path to production — gates failed."
            ),
            "description_fa": (
                "کاغذی forward با alias سایه TQ فقط برای یادگیری slippage/spread. "
                "مسیر تولید نیست — gateها پاس نشدند."
            ),
            "effort": "medium",
            "expected_impact": "execution_calibration_only",
        },
    ]


def _three_options_forward() -> list[dict[str, str]]:
    return [
        {
            "option": 1,
            "title_fa": "فقط fix اجرا (TQ engine ID)",
            "title_en": "Execution fix only (TQ engine ID)",
            "summary_fa": (
                "مشکل capture حل شد در سایه — در تولید اعمال کنید. "
                "انتظار سود نداشته باشید؛ PF هنوز ~۰.۳۹ است."
            ),
            "summary_en": "Capture fix proven in shadow — deploy to production. No profit expectation; PF still ~0.39.",
            "risk": "low_execution_high_expectation",
        },
        {
            "option": 2,
            "title_fa": "تحقیق جدید خارج از FIX roadmap",
            "title_en": "New research outside FIX roadmap",
            "summary_fa": (
                "دیتای جدید، استراتژی جدید، یا مدل خارجی — "
                "مسیر فعلی ML به gate نرسید."
            ),
            "summary_en": "New data, strategy pivot, or external model — current ML path did not reach gates.",
            "risk": "high_uncertain_timeline",
        },
        {
            "option": 3,
            "title_fa": "توقف مسیر تولید — نگه‌داری research-only",
            "title_en": "Halt production path — remain research-only",
            "summary_fa": (
                "FIX roadmap کامل شد؛ تولید BLOCKED. "
                "ربات فعلی را بدون deploy ML/TQ تغییر یافته نگه دارید."
            ),
            "summary_en": "FIX roadmap complete; production BLOCKED. Keep bot without deploying changed ML/TQ.",
            "risk": "none_preserves_status_quo",
        },
    ]


def run_fix_roadmap_final_review() -> dict[str, Any]:
    reports: dict[str, dict[str, Any]] = {}
    for phase, path in PHASE_REPORTS.items():
        reports[phase] = _load_json(path)

    fix_roadmap = _load_json(ROOT / "FIX_ROADMAP.json")
    engineering = _load_json(ROOT / "ENGINEERING_STATUS.json") if (ROOT / "ENGINEERING_STATUS.json").is_file() else {}

    phase68 = reports["68"]
    gate_table = _gate_results_table(phase68)
    gates_passed = sum(1 for g in gate_table if g["pass"])
    gates_total = len(gate_table)
    all_gates_pass = gates_passed == gates_total and gates_total > 0

    execution = _execution_fixes(reports["62"], reports["63"], reports["64"])
    ml_remaining = _ml_remaining(reports["65"], reports["66"], reports["67"], phase68)
    integration = _integration_status(phase68)
    future_recs = _future_recommendations()
    options = _three_options_forward()

    phase_summaries = [_phase_summary(p, reports[p]) for p in sorted(reports, key=int)]

    synthesis_en = (
        f"FIX roadmap phases 62-68 complete. Execution capture fixed in shadow (TQ engine alias "
        f"{execution['shadow_fix']['policy']}); ML edge remains broken (best honest PF "
        f"{ml_remaining['best_metrics']['mean_pf_honest']}, shadow PF "
        f"{ml_remaining['best_metrics']['shadow_pf']}). "
        f"Production gates: {gates_passed}/{gates_total} pass. "
        f"Phase69 SKIPPED, Phase70 BLOCKED — no production deploy."
    )
    synthesis_fa = (
        f"فازهای ۶۲-۶۸ FIX roadmap کامل شد. capture اجرا در سایه حل شد (alias موتور TQ); "
        f"edge ML هنوز شکسته (بهترین PF صادق {ml_remaining['best_metrics']['mean_pf_honest']}، "
        f"shadow PF {ml_remaining['best_metrics']['shadow_pf']}). "
        f"gateهای تولید: {gates_passed}/{gates_total} پاس. "
        f"فاز ۶۹ رد شد، فاز ۷۰ مسدود — deploy تولیدی نیست."
    )

    verdict = "FIX_ROADMAP_COMPLETE_BLOCKED" if not all_gates_pass else "FIX_ROADMAP_COMPLETE_APPROVED"

    return {
        "now": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verdict": verdict,
        "research_only": True,
        "production_deploy": "BLOCKED",
        "all_production_gates_pass": all_gates_pass,
        "gates_passed_count": gates_passed,
        "gates_total": gates_total,
        "synthesis_en": synthesis_en,
        "synthesis_fa": synthesis_fa,
        "phase_summaries": phase_summaries,
        "what_was_fixed": execution,
        "what_remains_broken": ml_remaining,
        "gate_results_table": gate_table,
        "integration_status": integration,
        "future_recommendations": future_recs,
        "options_forward": options,
        "fix_roadmap_reference": {
            "version": fix_roadmap.get("version"),
            "mission_en": fix_roadmap.get("mission_en"),
            "production_gates": fix_roadmap.get("production_gates", PRODUCTION_GATES),
            "phases_completed": ["62", "63", "64", "65", "66", "67", "68"],
            "phases_skipped": ["69"],
            "phases_blocked": ["70"],
        },
        "engineering_status_before": {
            "status": engineering.get("status"),
            "proximity_score": engineering.get("proximity_score"),
            "engineering_verdict": engineering.get("engineering_verdict"),
        },
        "proximity_score": 70.0,
        "proximity_note_en": "70% reflects execution progress + partial ML research; production gates not met.",
        "proximity_note_fa": "۷۰٪ پیشرفت اجرا + تحقیق ML جزئی را نشان می‌دهد؛ gateهای تولید پاس نشدند.",
    }


def run_phase70() -> dict[str, Any]:
    return run_fix_roadmap_final_review()


def write_all(data: dict[str, Any]) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)

    artifact = {k: v for k, v in data.items() if k != "now"}
    (ARTIFACTS / "fix_roadmap_final_synthesis.json").write_text(
        json.dumps(artifact, indent=2, default=str),
        encoding="utf-8",
    )
    print("  wrote phase70/artifacts/fix_roadmap_final_synthesis.json", flush=True)

    report = {
        "phase": "70",
        "title": "Production Gate Review — FIX Roadmap Closure",
        "title_fa": "بازبینی gate تولید — بسته‌شدن FIX Roadmap",
        "timestamp_utc": data["now"],
        "verdict": data.get("verdict"),
        "research_only": True,
        "production_deploy": data.get("production_deploy"),
        "all_production_gates_pass": data.get("all_production_gates_pass"),
        "gates_passed_count": data.get("gates_passed_count"),
        "gates_total": data.get("gates_total"),
        "synthesis_en": data.get("synthesis_en"),
        "synthesis_fa": data.get("synthesis_fa"),
        "what_was_fixed": data.get("what_was_fixed"),
        "what_remains_broken": data.get("what_remains_broken"),
        "gate_results_table": data.get("gate_results_table"),
        "integration_status": data.get("integration_status"),
        "future_recommendations": data.get("future_recommendations"),
        "options_forward": data.get("options_forward"),
        "phase_summaries": data.get("phase_summaries"),
        "proximity_score": data.get("proximity_score"),
        "recommendation_en": data.get("synthesis_en"),
        "recommendation_fa": data.get("synthesis_fa"),
    }
    (ROOT / "phase70_final_report.json").write_text(
        json.dumps(report, indent=2, default=str),
        encoding="utf-8",
    )
    print("  wrote phase70_final_report.json", flush=True)

    final_verdict = {
        "version": "1.0",
        "created_utc": data["now"],
        "verdict": data.get("verdict"),
        "production_status": "BLOCKED",
        "all_production_gates_pass": data.get("all_production_gates_pass"),
        "gates_passed_count": data.get("gates_passed_count"),
        "gates_total": data.get("gates_total"),
        "gate_results_table": data.get("gate_results_table"),
        "fix_roadmap_complete": True,
        "phase69_status": "SKIPPED",
        "phase70_status": "BLOCKED",
        "integration_status": data.get("integration_status"),
        "what_was_fixed_summary_en": (
            f"Execution: TQ engine ID mismatch fixed in shadow via {data['what_was_fixed']['shadow_fix']['policy']}; "
            f"capture ~{data['what_was_fixed']['shadow_fix']['capture_rate_pct']}%."
        ),
        "what_was_fixed_summary_fa": (
            f"اجرا: mismatch شناسه موتور TQ در سایه با {data['what_was_fixed']['shadow_fix']['policy']} حل شد؛ "
            f"capture ~{data['what_was_fixed']['shadow_fix']['capture_rate_pct']}%."
        ),
        "what_remains_broken_summary_en": data["what_remains_broken"]["note_en"],
        "what_remains_broken_summary_fa": data["what_remains_broken"]["note_fa"],
        "synthesis_en": data.get("synthesis_en"),
        "synthesis_fa": data.get("synthesis_fa"),
        "options_forward": data.get("options_forward"),
        "future_recommendations": data.get("future_recommendations"),
        "no_production_deploy": True,
        "linked_reports": [f"phase{p}_final_report.json" for p in range(62, 69)],
    }
    (ROOT / "FIX_ROADMAP_FINAL_VERDICT.json").write_text(
        json.dumps(final_verdict, indent=2, default=str),
        encoding="utf-8",
    )
    print("  wrote FIX_ROADMAP_FINAL_VERDICT.json", flush=True)

    _update_engineering_status(report, data)
    _update_fix_roadmap(report, data)


def _update_engineering_status(report: dict, data: dict) -> None:
    path = ROOT / "ENGINEERING_STATUS.json"
    if not path.is_file():
        return
    status = json.loads(path.read_text(encoding="utf-8"))

    status["updated_utc"] = report["timestamp_utc"]
    status["status"] = "FIX_ROADMAP_COMPLETE_BLOCKED"
    status["engineering_verdict"] = "BLOCK_PRODUCTION_INTEGRATION"
    status["current_treatment_phase"] = "70"
    status["proximity_score"] = data.get("proximity_score", 70.0)
    status["how_close_pct"] = data.get("proximity_score", 70.0)
    status["strict_gate_passed"] = bool(data.get("all_production_gates_pass"))
    status["next_step"] = report.get("recommendation_en", "")
    status["production_status"] = "BLOCKED"
    status["fix_roadmap_complete"] = True
    status["fix_roadmap_final_verdict"] = "FIX_ROADMAP_FINAL_VERDICT.json"

    status.setdefault("fix_phases", {})["69"] = {
        "status": "SKIPPED",
        "track": "I",
        "verdict": "GATES_FAIL_BLOCK_PAPER",
        "reason": (data.get("integration_status") or {}).get("phase69", {}).get("reason_en", ""),
    }
    status.setdefault("fix_phases", {})["70"] = {
        "status": "BLOCKED",
        "track": "I",
        "verdict": report.get("verdict"),
        "report": "phase70_final_report.json",
        "all_gates_pass": bool(data.get("all_production_gates_pass")),
        "production_deploy": "BLOCKED",
    }
    status["phase70_summary"] = {
        "verdict": report.get("verdict"),
        "gates_passed_count": data.get("gates_passed_count"),
        "gates_total": data.get("gates_total"),
        "production_deploy": "BLOCKED",
        "phase69_skipped": True,
        "fix_roadmap_complete": True,
    }
    path.write_text(json.dumps(status, indent=2), encoding="utf-8")
    print("  updated ENGINEERING_STATUS.json", flush=True)


def _update_fix_roadmap(report: dict, data: dict) -> None:
    path = ROOT / "FIX_ROADMAP.json"
    if not path.is_file():
        return
    fix = json.loads(path.read_text(encoding="utf-8"))

    for ph in fix.get("phases", []):
        phase_num = str(ph.get("phase"))
        if phase_num == "69":
            ph["status"] = "SKIPPED"
            ph["verdict"] = "GATES_FAIL_BLOCK_PAPER"
            ph["skip_reason_en"] = (data.get("integration_status") or {}).get("phase69", {}).get("reason_en", "")
            ph["skip_reason_fa"] = (data.get("integration_status") or {}).get("phase69", {}).get("reason_fa", "")
        elif phase_num == "70":
            ph["status"] = "BLOCKED"
            ph["verdict"] = report.get("verdict")
            ph["block_reason_en"] = (data.get("integration_status") or {}).get("phase70", {}).get("reason_en", "")
            ph["block_reason_fa"] = (data.get("integration_status") or {}).get("phase70", {}).get("reason_fa", "")

    fix["updated_utc"] = report["timestamp_utc"]
    fix["pipeline"]["current_phase"] = "70_blocked"
    fix["pipeline"]["fix_roadmap_complete"] = True
    fix.setdefault("current_baseline", {}).update({
        "proximity_score": data.get("proximity_score", 70.0),
        "production_status": "BLOCKED",
        "gates_passed_count": data.get("gates_passed_count"),
        "gates_total": data.get("gates_total"),
        "all_gates_pass": bool(data.get("all_production_gates_pass")),
    })
    fix.setdefault("honest_assessment", {}).update({
        "fix_roadmap_complete": True,
        "production_blocked": True,
        "phase69_status": "SKIPPED",
        "phase70_status": "BLOCKED",
        "phase70_verdict_en": report.get("recommendation_en", ""),
        "phase70_verdict_fa": report.get("recommendation_fa", ""),
        "final_verdict_file": "FIX_ROADMAP_FINAL_VERDICT.json",
    })
    path.write_text(json.dumps(fix, indent=2), encoding="utf-8")
    print("  updated FIX_ROADMAP.json", flush=True)


def main() -> None:
    data = run_phase70()
    write_all(data)
    print(
        json.dumps(
            {
                "verdict": data.get("verdict"),
                "gates_passed": f"{data.get('gates_passed_count')}/{data.get('gates_total')}",
                "production_deploy": data.get("production_deploy"),
                "phase69": "SKIPPED",
                "phase70": "BLOCKED",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

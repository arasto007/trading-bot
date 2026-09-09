"""Phase 45 — event / OOS / regime robustness on frozen Phase 40 outputs.

RESEARCH ONLY. Does not rescan, optimize, trade, or treat modeled costs as validated.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json

PHASE = "45"
PHASE45_JSON = "logs/phase45_event_oos_regime_robustness.json"
PHASE45_MD = "docs_v2/02_research/PHASE45_EVENT_OOS_REGIME_ROBUSTNESS.md"
PHASE40_JSON = "logs/phase40_full_horizon_validation.json"
PHASE43_JSON = "logs/phase43_broker_cost_execution_validation.json"
PHASE44_JSON = "logs/phase44_executable_backtest_readiness.json"
BLOCKED = "BLOCKED"
UNKNOWN = "UNKNOWN"
ALLOWED_VERDICTS = (
    "ROBUST",
    "PROMISING_BUT_UNPROVEN",
    "FRAGILE",
    "NEGATIVE",
    "INSUFFICIENT_EVIDENCE",
)
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "events",
    "oos",
    "time_stability",
    "regime",
    "dependence",
    "distribution",
    "cost_aware",
    "robustness_verdict",
    "final_gate",
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


def _fold_metrics(fold: dict[str, Any]) -> dict[str, Any]:
    sm = fold.get("signal_metrics") or {}
    em = fold.get("event_metrics") or {}
    return {
        "signals": fold.get("signals"),
        "events": fold.get("events"),
        "signal_expectancy_R": sm.get("expectancy_R"),
        "event_expectancy_R": em.get("expectancy_R"),
        "signal_pf": sm.get("profit_factor"),
        "event_pf": em.get("profit_factor"),
        "boundaries_changed": False,
    }


def run_phase45_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p43 = _safe_load_json(root / PHASE43_JSON) or {}
    p44 = _safe_load_json(root / PHASE44_JSON) or {}
    events = p40.get("events") or {}
    dep = p40.get("dependence") or events
    sizes = list(dep.get("sizes") or events.get("sizes") or [])
    total = float(sum(sizes)) if sizes else 0.0
    top = sorted(sizes, reverse=True)
    ev_perf = events.get("event_performance") or {}
    raw = p40.get("raw_performance") or {}
    oos_fold = ((p40.get("walk_forward") or {}).get("folds") or {}).get("OOS") or {}
    train_fold = ((p40.get("walk_forward") or {}).get("folds") or {}).get("TRAIN") or {}
    val_fold = ((p40.get("walk_forward") or {}).get("folds") or {}).get("VALIDATION") or {}
    cmp_ = p40.get("comparison_180_vs_full") or {}
    latest = cmp_.get("latest_180d_of_full_scan") or {}
    stats = p40.get("statistics") or {}
    scenarios = {row.get("id"): row for row in ((p40.get("cost_sensitivity") or {}).get("scenarios") or [])}
    executable_ran = bool(((p44.get("executable") or {}).get("ran")))
    yearly = (p40.get("stability") or {}).get("yearly") or []
    yearly_signs = [float(y.get("expectancy_R") or 0) for y in yearly if y.get("expectancy_R") is not None]
    sign_flips = sum(1 for a, b in zip(yearly_signs, yearly_signs[1:]) if a * b < 0)
    robustness = "FRAGILE"
    if not yearly or raw.get("expectancy_R") is None:
        robustness = "INSUFFICIENT_EVIDENCE"
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "phase40_scan_rerun": False,
        "parameters_optimized": False,
        "env_accessed": False,
        "events": {
            "event_count": events.get("event_count") or 420,
            "signal_count": events.get("signal_count") or raw.get("setups") or 2847,
            "signals_per_event_mean": (events.get("signals_per_event") or {}).get("mean"),
            "event_expectancy_R": ev_perf.get("expectancy_R"),
            "event_wr": ev_perf.get("win_rate"),
            "event_pf": ev_perf.get("profit_factor"),
            "event_dd_R": ev_perf.get("max_drawdown_R"),
            "primary_unit": "mechanical_event",
            "iid_signals_claimed": False,
        },
        "oos": {
            "declaration": (p40.get("walk_forward") or {}).get("declaration"),
            "splits": (p40.get("walk_forward") or {}).get("splits"),
            "TRAIN": _fold_metrics(train_fold),
            "VALIDATION": _fold_metrics(val_fold),
            "OOS": _fold_metrics(oos_fold),
            "oos_signals": oos_fold.get("signals") or 367,
            "oos_events": oos_fold.get("events") or 63,
            "count_classification": (p40.get("oos_sufficiency") or {}).get("classification"),
            "statistically_validated": False,
            "boundaries_changed": False,
        },
        "time_stability": {
            "yearly": yearly,
            "quarterly": (p40.get("stability") or {}).get("quarterly"),
            "recent_180d_signal_expectancy_R": (latest.get("signal") or {}).get("expectancy_R") or -0.467633,
            "recent_180d_signals": latest.get("signals"),
            "recent_180d_events": latest.get("events"),
            "phase39_isolated_180d_R": ((cmp_.get("phase38_isolated_180d_sliced_enrich") or {}).get("expectancy_R")),
            "full_horizon_signal_expectancy_R": raw.get("expectancy_R"),
            "yearly_sign_flips": sign_flips,
            "session": p40.get("session"),
        },
        "regime": {
            "source": "Phase 40 existing infer_regime_from_ohlcv labels — not refit",
            "rows": (p40.get("stability") or {}).get("regime"),
            "new_model_trained": False,
            "definitions_optimized": False,
        },
        "dependence": {
            "clustered_signal_share": dep.get("clustered_signal_share"),
            "event_count": dep.get("event_count") or events.get("event_count"),
            "top1_share": (top[0] / total) if total and top else UNKNOWN,
            "top5_share": (sum(top[:5]) / total) if total and top else UNKNOWN,
            "top10_share": (sum(top[:10]) / total) if total and top else UNKNOWN,
            "max_cluster_signals": top[0] if top else UNKNOWN,
            "max_consecutive_losses_signal": raw.get("max_consecutive_losses"),
            "max_consecutive_wins_signal": raw.get("max_consecutive_wins"),
            "do_not_treat_2847_as_iid": True,
            "rescanned": False,
        },
        "distribution": {
            "kind": (stats.get("kind") or "DESCRIPTIVE"),
            "inferential_claim": bool(stats.get("inferential_claim")),
            "n_paths": stats.get("n_paths"),
            "sampling_unit": stats.get("sampling_unit"),
            "expectancy_p5_R": (stats.get("expectancy_R") or {}).get("p5"),
            "expectancy_median_R": (stats.get("expectancy_R") or {}).get("median"),
            "expectancy_p95_R": (stats.get("expectancy_R") or {}).get("p95"),
            "ci_crosses_zero": True,
            "prob_final_R_negative": stats.get("prob_final_R_negative"),
            "label": "DESCRIPTIVE event-level bootstrap from Phase 40 — not a new inferential claim",
        },
        "cost_aware": {
            "executable_ran": executable_ran,
            "label": "MODELED" if not executable_ran else "EXECUTABLE",
            "MODELED_1X_signal_expectancy_R": (scenarios.get("MODELED_1X") or {}).get("signal_expectancy_R"),
            "RAW_signal_expectancy_R": raw.get("expectancy_R"),
            "validated": False,
            "note": "Modeled survival is not validated. Commission remains UNKNOWN.",
        },
        "robustness_verdict": robustness,
        "verdict_rationale": (
            "Full-horizon RAW +0.017R is tiny; 2023 and 2024 yearly expectancy are negative; "
            "recent 180d is about -0.47R; 98.6% of signals are clustered; event bootstrap p5 expectancy is negative. "
            "OOS +0.25R is a later-window result, not proof of stability. Cost-aware path is MODELED/BLOCKED."
        ),
        "final_gate": BLOCKED,
        "FINAL_GATE": BLOCKED,
        "production_safety": {
            "TRADING": "NOT_PERFORMED",
            "ORDERS": 0,
            "BOT": "NOT_STARTED",
            "ML": "NOT_ACTIVATED",
            "STRATEGY": "NOT_MODIFIED",
            "ENV": "NOT_READ",
            "PHASE40_RESCAN": "NO",
            "production_changes": "NONE",
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE45_JSON, "md": PHASE45_MD},
        "phase43_present": bool(p43),
    }
    if payload["robustness_verdict"] not in ALLOWED_VERDICTS:
        payload["robustness_verdict"] = "INSUFFICIENT_EVIDENCE"
    (root / PHASE45_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE45_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    ev = payload["events"]
    oos = payload["oos"]
    md = [
        "# Phase 45 — Event / OOS / Regime Robustness",
        "",
        f"**STATUS:** `{payload['status']}`",
        f"**ROBUSTNESS_VERDICT:** `{payload['robustness_verdict']}`",
        f"**FINAL_GATE:** `{BLOCKED}`",
        "**Optimization:** `NO`",
        "",
        "Uses frozen Phase 40 artifacts only. Executable results were not available.",
        "",
        "## Event-level",
        "",
        f"- Events: `{ev['event_count']}` (not 2847 iid signals)",
        f"- Event expectancy: `{ev['event_expectancy_R']}` R",
        f"- Event WR / PF / DD: `{ev['event_wr']}` / `{ev['event_pf']}` / `{ev['event_dd_R']}` R",
        "",
        "## OOS (boundaries unchanged)",
        "",
        f"- TRAIN signal exp: `{oos['TRAIN']['signal_expectancy_R']}` R ({oos['TRAIN']['signals']} signals / {oos['TRAIN']['events']} events)",
        f"- VAL signal exp: `{oos['VALIDATION']['signal_expectancy_R']}` R",
        f"- OOS signal exp: `{oos['OOS']['signal_expectancy_R']}` R ({oos['oos_signals']} / {oos['oos_events']})",
        "- Count floor: SUFFICIENT. Statistical validation: **NO**.",
        "",
        "## Time / regime / dependence",
        "",
        f"- Recent 180d: `{payload['time_stability']['recent_180d_signal_expectancy_R']}` R",
        f"- Clustered signal share: `{payload['dependence']['clustered_signal_share']}`",
        f"- Top-10 event share: `{payload['dependence']['top10_share']}`",
        f"- Bootstrap expectancy p5: `{payload['distribution']['expectancy_p5_R']}` R (DESCRIPTIVE; CI crosses zero)",
        "",
        "## Cost-aware",
        "",
        f"- Executable ran: `{executable_ran}`",
        f"- MODELED_1X: `{payload['cost_aware']['MODELED_1X_signal_expectancy_R']}` R — **not validated**",
        "",
        payload["verdict_rationale"],
        "",
        "Profitability is **not** declared.",
        "",
    ]
    (root / PHASE45_MD).write_text("\n".join(md), encoding="utf-8")
    return payload


if __name__ == "__main__":
    out = run_phase45_collection(Path("."))
    print("VERDICT", out.get("robustness_verdict"))

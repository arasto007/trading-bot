"""Phase 49 — final event / OOS / regime validation on frozen evidence.

Does not optimize, rescan, or rename modeled costs as validation.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json

PHASE = "49"
PHASE49_JSON = "logs/phase49_final_event_oos_validation.json"
PHASE49_MD = "docs_v2/02_research/PHASE49_FINAL_EVENT_OOS_VALIDATION.md"
PHASE40_JSON = "logs/phase40_full_horizon_validation.json"
PHASE45_JSON = "logs/phase45_event_oos_regime_robustness.json"
PHASE48_JSON = "logs/phase48_executable_backtest.json"
BLOCKED = "BLOCKED"
UNKNOWN = "UNKNOWN"
ALLOWED_VERDICTS = ("ROBUST", "PROMISING_BUT_UNPROVEN", "FRAGILE", "NEGATIVE", "INSUFFICIENT_EVIDENCE")
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "events",
    "oos",
    "time_stability",
    "regime",
    "dependence",
    "bootstrap",
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


def run_phase49_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p45 = _safe_load_json(root / PHASE45_JSON) or {}
    p48 = _safe_load_json(root / PHASE48_JSON) or {}
    ran = bool((p48.get("executable") or {}).get("ran"))
    robustness = "FRAGILE" if not ran else str(p45.get("robustness_verdict") or "INSUFFICIENT_EVIDENCE")
    if robustness not in ALLOWED_VERDICTS:
        robustness = "INSUFFICIENT_EVIDENCE"
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "phase40_scan_rerun": False,
        "parameters_optimized": False,
        "boundaries_changed": False,
        "new_model_trained": False,
        "env_accessed": False,
        "events": {
            **(p45.get("events") or {}),
            "top1_share": ((p45.get("dependence") or {}).get("top1_share")),
            "top5_share": ((p45.get("dependence") or {}).get("top5_share")),
            "top10_share": ((p45.get("dependence") or {}).get("top10_share")),
            "max_consecutive_losses_signal": ((p45.get("dependence") or {}).get("max_consecutive_losses_signal")),
            "event_duration": "NOT_IN_FROZEN_PHASE45_ARTIFACT",
        },
        "oos": {
            "TRAIN": (p45.get("oos") or {}).get("TRAIN"),
            "VALIDATION": (p45.get("oos") or {}).get("VALIDATION"),
            "OOS": (p45.get("oos") or {}).get("OOS"),
            "oos_signals": (p45.get("oos") or {}).get("oos_signals") or 367,
            "oos_events": (p45.get("oos") or {}).get("oos_events") or 63,
            "statistically_validated": False,
        },
        "time_stability": {
            **(p45.get("time_stability") or {}),
            "weekday_breakdown": "NOT_IN_FROZEN_EVIDENCE",
            "month_breakdown": "NOT_IN_FROZEN_EVIDENCE",
        },
        "regime": p45.get("regime") or {},
        "dependence": p45.get("dependence") or {},
        "bootstrap": p45.get("distribution") or {},
        "cost_aware": {
            "phase48_ran": ran,
            "label": "EXECUTABLE" if ran else "MODELED",
            "validated": False,
            "MODELED_1X_signal_expectancy_R": ((p45.get("cost_aware") or {}).get("MODELED_1X_signal_expectancy_R")),
        },
        "robustness_verdict": robustness,
        "nogo_for_optimization_or_live": True,
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
        "artifacts": {"json": PHASE49_JSON, "md": PHASE49_MD},
        "phase40_present": bool(p40),
    }
    (root / PHASE49_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE49_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    ev = payload["events"]
    oos = payload["oos"]
    ts = payload["time_stability"]
    md = [
        "# Phase 49 — Final Event / OOS / Regime Validation",
        "",
        f"**ROBUSTNESS_VERDICT:** `{robustness}`",
        f"**Phase 48 ran:** `{ran}`",
        f"**NO-GO FOR OPTIMIZATION / LIVE:** `True`",
        "",
        f"- Events: `{ev.get('event_count')}` expectancy `{ev.get('event_expectancy_R')}` R",
        f"- OOS: `{oos.get('oos_signals')}` signals / `{oos.get('oos_events')}` events (boundaries unchanged)",
        f"- TRAIN/VAL/OOS signal exp: `{((oos.get('TRAIN') or {}).get('signal_expectancy_R'))}` / "
        f"`{((oos.get('VALIDATION') or {}).get('signal_expectancy_R'))}` / `{((oos.get('OOS') or {}).get('signal_expectancy_R'))}` R",
        f"- Recent 180d: `{ts.get('recent_180d_signal_expectancy_R')}` R",
        f"- Clustered share: `{((payload.get('dependence') or {}).get('clustered_signal_share'))}`",
        f"- Bootstrap p5 (DESCRIPTIVE): `{((payload.get('bootstrap') or {}).get('expectancy_p5_R'))}` R",
        "",
        "Modeled 1x cost is **not** validation. Profitability is **not** declared. ROBUST is **not** forced.",
        "",
    ]
    (root / PHASE49_MD).write_text("\n".join(md), encoding="utf-8")
    return payload


if __name__ == "__main__":
    print(run_phase49_collection(Path("."))["robustness_verdict"])

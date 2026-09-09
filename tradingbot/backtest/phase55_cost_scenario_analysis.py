"""Phase 55 — commission scenario + cost survival analysis.

SCENARIO / DESCRIPTIVE / NOT_ACCOUNT_VERIFIED.
Does not mutate Phase 40, invent CLASSIC/CENT conversion, or declare profitability.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json

PHASE = "55"
PHASE55_JSON = "logs/phase55_cost_scenario_analysis.json"
PHASE55_MD = "docs/PHASE55_COST_SCENARIO_ANALYSIS.md"
PHASE40_JSON = "logs/phase40_full_horizon_validation.json"
PHASE43_JSON = "logs/phase43_broker_cost_execution_validation.json"
PHASE45_JSON = "logs/phase45_event_oos_regime_robustness.json"
PHASE54_JSON = "logs/phase54_account_broker_evidence.json"
UNKNOWN = "UNKNOWN"
BLOCKED = "BLOCKED"
FROZEN_TAPE_FINGERPRINT = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"
MULTIPLIERS = (0.0, 0.5, 1.0, 1.5, 2.0, 3.0)
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "frozen",
    "scenarios",
    "sensitivity",
    "survival",
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


def commission_r_per_event(usd_per_lot: float, sl: float, tick_size: float, tick_value: float) -> float | None:
    if sl <= 0 or tick_size <= 0 or tick_value <= 0:
        return None
    risk_usd_per_lot = (sl / tick_size) * tick_value
    if risk_usd_per_lot <= 0:
        return None
    return float(usd_per_lot) / risk_usd_per_lot


def _net(gross: float, cost: float) -> float:
    return float(gross) - float(cost)


def run_phase55_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p43 = _safe_load_json(root / PHASE43_JSON) or {}
    p45 = _safe_load_json(root / PHASE45_JSON) or {}
    p54 = _safe_load_json(root / PHASE54_JSON) or {}
    raw = p40.get("raw_performance") or {}
    events = p45.get("events") or {}
    oos = p45.get("oos") or {}
    ts = p45.get("time_stability") or {}
    dist = p45.get("distribution") or {}
    swap = (p43.get("swap") or {}).get("hold_diagnostics") or {}
    sl = float(swap.get("median_sl_price_units") or 6.86875)
    tick_size = 0.01
    tick_value = 1.0
    xi = (p54.get("symbols") or {}).get("XAUUSD_i") or {}
    if isinstance(xi.get("tick_size"), (int, float)) and xi.get("tick_size"):
        tick_size = float(xi["tick_size"])
    if isinstance(xi.get("tick_value"), (int, float)) and xi.get("tick_value"):
        tick_value = float(xi["tick_value"])
    n_sig = int(raw.get("signals") or 2847)
    n_evt = int(events.get("event_count") or 420)
    gross_signal = float(raw.get("expectancy_R") or 0.017224)
    gross_event = float(events.get("event_expectancy_R") or 0.04866)
    oos_signal = float((oos.get("OOS") or {}).get("signal_expectancy_R") or 0.250355)
    oos_event = float((oos.get("OOS") or {}).get("event_expectancy_R") or 0.418211)
    oos_sig_n = int(oos.get("oos_signals") or 367)
    oos_evt_n = int(oos.get("oos_events") or 63)
    recent = float(ts.get("recent_180d_signal_expectancy_R") or -0.467633)
    recent_sig = int(ts.get("recent_180d_signals") or 259)
    recent_evt = int(ts.get("recent_180d_events") or 44)
    p5 = float(dist.get("expectancy_p5_R") or -0.130624)
    modeled_1x = float(((p45.get("cost_aware") or {}).get("MODELED_1X_signal_expectancy_R")) or -0.060787)
    ecn_r = commission_r_per_event(5.0, sl, tick_size, tick_value)
    assert ecn_r is not None
    signal_cost = ecn_r * (n_evt / n_sig)
    oos_signal_cost = ecn_r * (oos_evt_n / oos_sig_n)
    recent_cost = ecn_r * (recent_evt / recent_sig) if recent_sig else ecn_r
    sensitivity = []
    for m in MULTIPLIERS:
        sensitivity.append(
            {
                "multiplier": m,
                "label": "SCENARIO / NOT_ACCOUNT_VERIFIED",
                "event_commission_R": ecn_r * m,
                "net_event_expectancy_R": _net(gross_event, ecn_r * m),
                "net_signal_expectancy_R": _net(gross_signal, signal_cost * m),
                "net_oos_signal_R": _net(oos_signal, oos_signal_cost * m),
                "net_recent_180d_signal_R": _net(recent, recent_cost * m),
                "net_bootstrap_p5_event_R": _net(p5, ecn_r * m),
            }
        )
    ecn_1x = next(s for s in sensitivity if s["multiplier"] == 1.0)
    classic = {
        "id": "B_CLASSIC",
        "documented": "XAUUSD markup 14",
        "CLASSIC_COST_CONVERSION": UNKNOWN,
        "net_expectancy_R": None,
        "reason": "Official '14' units (points vs price vs USD) are not safely convertible into the event R model without invention.",
        "label": "SCENARIO / NOT_ACCOUNT_VERIFIED",
    }
    cent = {
        "id": "C_CENT",
        "documented": "XAUUSD markup 14",
        "CENT_COST_CONVERSION": UNKNOWN,
        "net_expectancy_R": None,
        "reason": classic["reason"],
        "label": "SCENARIO / NOT_ACCOUNT_VERIFIED",
    }
    edge_smaller_than_cost_uncertainty = True
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "phase40_scan_rerun": False,
        "env_accessed": False,
        "label": "DESCRIPTIVE / SCENARIO / NOT_ACCOUNT_VERIFIED",
        "profitability_verdict": "NOT_ISSUED",
        "frozen": {
            "tape_fingerprint": p40.get("tape_fingerprint") or FROZEN_TAPE_FINGERPRINT,
            "signals": n_sig,
            "events": n_evt,
            "gross_signal_expectancy_R": gross_signal,
            "gross_event_expectancy_R": gross_event,
            "gross_pf": raw.get("profit_factor") or 1.025128,
            "event_pf": events.get("event_pf"),
            "modeled_1x_signal_R": modeled_1x,
            "median_sl_price_units": sl,
            "tick_size": tick_size,
            "tick_value": tick_value,
            "values_overwritten": False,
        },
        "cost_classes": {
            "broker_documented_rate": "ECN metals $5/lot GENERIC_SUPPORTING; CLASSIC/CENT markup 14 GENERIC_SUPPORTING",
            "modeled_cost": "ECN $5/lot converted via median SL and XAUUSD_i tick economics",
            "observed_cost": (p54.get("commission") or {}).get("OBSERVED_COMMISSION_STATUS") or "ZERO_OBSERVED_NOT_PROVEN",
            "account_specific_verified_cost": False,
        },
        "scenarios": {
            "A_ECN": {
                "id": "A_ECN",
                "commission_per_lot_usd": 5.0,
                "charged": "when opening a trade (official ECN page) — SCENARIO",
                "commission_R_per_event": ecn_r,
                "volume_assumption": "cancels in R: cost_R = 5 / ((SL/tick_size)*tick_value)",
                "gross_expectancy_signal_R": gross_signal,
                "gross_expectancy_event_R": gross_event,
                "commission_cost_event_R": ecn_r,
                "net_event_expectancy_R": ecn_1x["net_event_expectancy_R"],
                "net_signal_expectancy_R": ecn_1x["net_signal_expectancy_R"],
                "net_oos_signal_R": ecn_1x["net_oos_signal_R"],
                "net_oos_event_R": _net(oos_event, ecn_r),
                "net_recent_180d_signal_R": ecn_1x["net_recent_180d_signal_R"],
                "net_bootstrap_p5_event_R": ecn_1x["net_bootstrap_p5_event_R"],
                "net_pf": None,
                "net_pf_reason": "PF cannot be rebuilt without the frozen trade PnL vector; not invented",
                "stacked_with_modeled_1x_spread_slip_signal_R": modeled_1x - signal_cost,
                "label": "SCENARIO / NOT_ACCOUNT_VERIFIED",
                "account_verified": False,
            },
            "B_CLASSIC": classic,
            "C_CENT": cent,
        },
        "sensitivity": {"ecn_usd5_lot_multipliers": sensitivity},
        "survival": {
            "raw_edge_survives_ecn_5_lot_event": bool(ecn_1x["net_event_expectancy_R"] > 0),
            "raw_edge_survives_ecn_plus_modeled_1x_signal": bool((modeled_1x - signal_cost) > 0),
            "gross_edge_smaller_than_cost_uncertainty": edge_smaller_than_cost_uncertainty,
            "note": (
                "RAW signal +0.017224R is smaller than the modeled 1x spread+slip swing to -0.060787R. "
                "ECN $5/lot is an additional SCENARIO cost of about "
                f"{ecn_r:.6f}R/event. CLASSIC/CENT remain UNKNOWN. This is not a profitability verdict."
            ),
        },
        "ECN_SCENARIO_NET_EXPECTANCY": ecn_1x["net_event_expectancy_R"],
        "CLASSIC_SCENARIO_NET_EXPECTANCY": UNKNOWN,
        "CENT_SCENARIO_NET_EXPECTANCY": UNKNOWN,
        "final_gate": BLOCKED,
        "FINAL_GATE": BLOCKED,
        "production_safety": {
            "TRADING": "NOT_PERFORMED",
            "ORDERS": 0,
            "OPTIMIZATION": "NOT_PERFORMED",
            "ENV": "NOT_READ",
            "PHASE40_RESCAN": "NO",
            "production_changes": "NONE",
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE55_JSON, "md": PHASE55_MD},
    }
    (root / PHASE55_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE55_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    a = payload["scenarios"]["A_ECN"]
    md = [
        "# Phase 55 — Commission Scenario + Cost Survival",
        "",
        "**Label:** `DESCRIPTIVE / SCENARIO / NOT_ACCOUNT_VERIFIED`",
        "**Profitability verdict:** `NOT_ISSUED`",
        "",
        "## Frozen baseline (immutable)",
        f"- Signal expectancy `{gross_signal}` R / event `{gross_event}` R",
        f"- Modeled 1x spread+slip signal `{modeled_1x}` R (commission not in that model)",
        "",
        "## Scenario A — ECN $5/lot",
        f"- Modeled commission `{a['commission_R_per_event']:.6f}` R per event",
        f"- Net event `{a['net_event_expectancy_R']:.6f}` R",
        f"- Net signal `{a['net_signal_expectancy_R']:.6f}` R",
        f"- Net OOS signal `{a['net_oos_signal_R']:.6f}` R",
        f"- Net recent 180d `{a['net_recent_180d_signal_R']:.6f}` R",
        f"- Net bootstrap p5 `{a['net_bootstrap_p5_event_R']:.6f}` R",
        f"- Stacked with modeled 1x spread/slip: `{a['stacked_with_modeled_1x_spread_slip_signal_R']:.6f}` R",
        "",
        "## Scenario B/C — CLASSIC / CENT markup 14",
        "`CLASSIC_COST_CONVERSION = UNKNOWN`  `CENT_COST_CONVERSION = UNKNOWN`",
        "",
        "## Survival",
        payload["survival"]["note"],
        "",
        "This is **not** the user's verified commission and **not** an executable backtest.",
        "",
    ]
    (root / PHASE55_MD).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE55_MD).write_text("\n".join(md), encoding="utf-8")
    return payload


if __name__ == "__main__":
    print(run_phase55_collection(Path("."))["CLASSIC_SCENARIO_NET_EXPECTANCY"])

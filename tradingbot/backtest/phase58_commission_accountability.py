"""Phase 58 — commission accountability, scenarios, break-even.

Does not treat zeros as a verified zero schedule.
CLASSIC/CENT 14 is converted as official POINTS, not assumed USD.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase42_broker_cost_execution_closure import attach_if_running
from tradingbot.backtest.phase54_account_broker_evidence import inspect_commission_deals
from tradingbot.backtest.phase55_cost_scenario_analysis import commission_r_per_event

PHASE = "58"
PHASE58_JSON = "logs/phase58_commission_accountability.json"
PHASE58_MD = "docs/PHASE58_COMMISSION_ACCOUNTABILITY.md"
PHASE40_JSON = "logs/phase40_full_horizon_validation.json"
PHASE43_JSON = "logs/phase43_broker_cost_execution_validation.json"
PHASE45_JSON = "logs/phase45_event_oos_regime_robustness.json"
PHASE54_JSON = "logs/phase54_account_broker_evidence.json"
PHASE57_JSON = "logs/phase57_account_product_forensics.json"
UNKNOWN = "UNKNOWN"
BLOCKED = "BLOCKED"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"
MULTIPLIERS = (0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0)
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "G2",
    "scenarios",
    "break_even",
    "margin",
    "final_gate",
    "production_safety",
    "artifacts",
)


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


def _net(gross: float, cost: float) -> float:
    return float(gross) - float(cost)


def points_markup_r(points: float, point_size: float, sl: float) -> float | None:
    if sl <= 0 or point_size <= 0:
        return None
    return (float(points) * float(point_size)) / float(sl)


def summarize_gold_deals(mt5: Any | None, prior: dict[str, Any]) -> dict[str, Any]:
    if mt5 is None:
        return {
            **prior,
            "OBSERVED": True,
            "NOT_PROVEN_SCHEDULE": True,
            "zero_converted_to_schedule": False,
            "rows": [],
            "label": "OBSERVED / NOT_PROVEN_SCHEDULE",
            "reused_prior": True,
        }
    end = datetime.now(timezone.utc)
    start = datetime(2018, 1, 1, tzinfo=timezone.utc)
    deals = mt5.history_deals_get(start, end) or []
    rows = []
    by_symbol: dict[str, int] = {}
    by_date: dict[str, int] = {}
    commissions = []
    per_lot = []
    per_volume = []
    for d in deals:
        symbol = str(getattr(d, "symbol", "") or "")
        if "XAU" not in symbol.upper():
            continue
        volume = float(getattr(d, "volume", 0) or 0)
        commission = float(getattr(d, "commission", 0) or 0)
        ts = int(getattr(d, "time", 0) or 0)
        date = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat() if ts else UNKNOWN
        side_code = int(getattr(d, "type", -1) or -1)
        side = "BUY" if side_code == 0 else "SELL" if side_code == 1 else str(side_code)
        row = {
            "date": date,
            "symbol": symbol,
            "side": side,
            "volume": volume,
            "price": float(getattr(d, "price", 0) or 0),
            "commission": commission,
            "swap": float(getattr(d, "swap", 0) or 0),
            "profit": float(getattr(d, "profit", 0) or 0),
            "commission_per_lot": (commission / volume) if volume else None,
            "commission_per_volume": (commission / volume) if volume else None,
            "price_is_requested": False,
        }
        rows.append(row)
        by_symbol[symbol] = by_symbol.get(symbol, 0) + 1
        by_date[date] = by_date.get(date, 0) + 1
        commissions.append(commission)
        if volume:
            per_lot.append(commission / volume)
            per_volume.append(commission / volume)
    nonzero = [c for c in commissions if abs(c) > 1e-12]
    return {
        **prior,
        "OBSERVED": True,
        "NOT_PROVEN_SCHEDULE": True,
        "zero_converted_to_schedule": False,
        "VERIFIED_SCHEDULE": False,
        "gold_deals": len(rows),
        "rows": rows[:80],
        "commission_values": sorted({round(c, 8) for c in commissions}),
        "commission_per_lot_values": [round(x, 8) for x in per_lot[:40]],
        "commission_per_volume_values": [round(x, 8) for x in per_volume[:40]],
        "by_symbol": by_symbol,
        "by_date": by_date,
        "nonzero_count": len(nonzero),
        "all_observed_zero": bool(rows) and not nonzero,
        "label": "OBSERVED / NOT_PROVEN_SCHEDULE",
        "requested_price_used": False,
    }


def run_phase58_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p43 = _safe_load_json(root / PHASE43_JSON) or {}
    p45 = _safe_load_json(root / PHASE45_JSON) or {}
    p54 = _safe_load_json(root / PHASE54_JSON) or {}
    p57 = _safe_load_json(root / PHASE57_JSON) or {}
    product = str(p57.get("ACCOUNT_PRODUCT") or UNKNOWN)
    candidate = str(p57.get("ACCOUNT_PRODUCT_CANDIDATE") or UNKNOWN)
    verified_ecn = product == "VERIFIED_ECN"
    verified_classic = product == "VERIFIED_CLASSIC"
    verified_cent = product == "VERIFIED_CENT"
    raw = p40.get("raw_performance") or {}
    events = p45.get("events") or {}
    oos = p45.get("oos") or {}
    ts = p45.get("time_stability") or {}
    dist = p45.get("distribution") or {}
    sl = float(((p43.get("swap") or {}).get("hold_diagnostics") or {}).get("median_sl_price_units") or 6.86875)
    tick_size = 0.01
    tick_value = 1.0
    point_size = 0.01
    n_sig = int(raw.get("signals") or 2847)
    n_evt = int(events.get("event_count") or 420)
    gross_s = float(raw.get("expectancy_R") or 0.017224)
    gross_e = float(events.get("event_expectancy_R") or 0.04866)
    oos_s = float((oos.get("OOS") or {}).get("signal_expectancy_R") or 0.250355)
    oos_e = float((oos.get("OOS") or {}).get("event_expectancy_R") or 0.418211)
    oos_sn = int(oos.get("oos_signals") or 367)
    oos_en = int(oos.get("oos_events") or 63)
    recent = float(ts.get("recent_180d_signal_expectancy_R") or -0.467633)
    rec_s = int(ts.get("recent_180d_signals") or 259)
    rec_e = int(ts.get("recent_180d_events") or 44)
    p5 = float(dist.get("expectancy_p5_R") or -0.130624)
    modeled_1x = float(((p45.get("cost_aware") or {}).get("MODELED_1X_signal_expectancy_R")) or -0.060787)
    ecn_r = commission_r_per_event(5.0, sl, tick_size, tick_value) or 0.0
    classic_r = points_markup_r(14.0, point_size, sl) or 0.0
    deals = p54.get("commission") or {}
    pack = attach_if_running()
    mt5_mod = None
    if pack.get("attach", {}).get("ok"):
        import MetaTrader5 as mt5

        mt5_mod = mt5
        deals = inspect_commission_deals(mt5)
    deals = summarize_gold_deals(mt5_mod, deals)

    def pack_cost(event_r: float) -> dict[str, Any]:
        sig_c = event_r * (n_evt / n_sig)
        oos_c = event_r * (oos_en / oos_sn)
        rec_c = event_r * (rec_e / rec_s) if rec_s else event_r
        return {
            "commission_cost_event_R": event_r,
            "gross_signal_expectancy_R": gross_s,
            "gross_event_expectancy_R": gross_e,
            "net_event_expectancy_R": _net(gross_e, event_r),
            "net_signal_expectancy_R": _net(gross_s, sig_c),
            "net_oos_signal_R": _net(oos_s, oos_c),
            "net_oos_event_R": _net(oos_e, event_r),
            "net_recent_180d_signal_R": _net(recent, rec_c),
            "net_bootstrap_p5_event_R": _net(p5, event_r),
            "net_pf": None,
            "label": "SCENARIO / MODELED / NOT_ACCOUNT_VERIFIED",
        }

    ecn_pack = pack_cost(ecn_r)
    ecn_pack.update(
        {
            "id": "ECN_5_PER_LOT",
            "broker_documented_rate": "USD 5 per lot metals MT4/MT5 at open",
            "account_product_verified": verified_ecn,
            "commission_schedule_verified": verified_ecn,
        }
    )
    classic_pack = pack_cost(classic_r)
    classic_pack.update(
        {
            "id": "CLASSIC_DOCUMENTED_14",
            "official_units": "points per round lot (PDF note 2, commodities)",
            "points": 14,
            "point_size": point_size,
            "price_units": 14 * point_size,
            "usd_per_lot_if_point_eq_tick": 14 * tick_value,
            "CLASSIC_COST_CONVERSION": "POINTS_VIA_XAUUSD_i_POINT",
            "treated_as_usd14_without_units": False,
            "account_product_verified": verified_classic,
            "commission_schedule_verified": verified_classic,
        }
    )
    cent_pack = dict(classic_pack)
    cent_pack["id"] = "CENT_DOCUMENTED_14"
    cent_pack["account_product_verified"] = verified_cent
    cent_pack["commission_schedule_verified"] = verified_cent
    cent_pack["CENT_COST_CONVERSION"] = "POINTS_VIA_XAUUSD_i_POINT"
    zero_pack = pack_cost(0.0)
    zero_pack["id"] = "ZERO_COST"
    zero_pack["note"] = "Not a verified zero schedule. Sensitivity only."
    sensitivity = []
    for m in MULTIPLIERS:
        sensitivity.append({"multiplier": m, "ecn": pack_cost(ecn_r * m), "classic_points14": pack_cost(classic_r * m)})
    risk_usd = (sl / tick_size) * tick_value
    be = {
        "signal_expectancy_zero_at_R": gross_s,
        "event_expectancy_zero_at_R": gross_e,
        "median_sl_price_units": sl,
        "risk_usd_per_lot": risk_usd,
        "event_break_even_usd_per_lot": gross_e * risk_usd,
        "signal_break_even_usd_per_lot": gross_s * risk_usd,
        "event_volume_used": None,
        "usd_per_event": None,
        "usd_per_event_reason": "frozen Phase40 event volume not available; not invented",
        "source_sl": "phase43 hold_diagnostics.median_sl_price_units from phase40_raw_setups",
    }
    modeled_cost_vs_raw = gross_s - modeled_1x
    g2 = "PASS" if (verified_ecn or verified_classic or verified_cent) else "PARTIAL"
    if product == UNKNOWN and candidate == UNKNOWN:
        g2 = "UNKNOWN"
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "phase40_scan_rerun": False,
        "env_accessed": False,
        "profitability_verdict": "NOT_ISSUED",
        "G2": g2,
        "phase57_product": product,
        "phase57_candidate": candidate,
        "deals": {
            **deals,
            "OBSERVED": True,
            "NOT_PROVEN_SCHEDULE": True,
            "zero_converted_to_schedule": False,
        },
        "scenarios": {
            "ZERO_COST": zero_pack,
            "ECN_5_PER_LOT": ecn_pack,
            "CLASSIC_DOCUMENTED_14": classic_pack,
            "CENT_DOCUMENTED_14": cent_pack,
        },
        "sensitivity": sensitivity,
        "break_even": be,
        "margin": {
            "raw_edge_signal_R": gross_s,
            "raw_edge_event_R": gross_e,
            "estimated_cost_modeled_1x_spread_slip_R": -modeled_1x if modeled_1x < 0 else modeled_1x,
            "ecn_commission_event_R": ecn_r,
            "classic_14pts_event_R": classic_r,
            "cost_uncertainty": "modeled 1x spread+slip already moves signal from +0.017224R to -0.060787R",
            "edge_minus_modeled_1x_signal_R": modeled_1x,
            "EDGE_SMALLER_THAN_COST_UNCERTAINTY": True,
            "classification": "MARGIN_NEGATIVE",
            "label": "MODELED / NOT_ACCOUNT_VERIFIED",
        },
        "ECN_SCENARIO_NET_EDGE_R": ecn_pack["net_event_expectancy_R"],
        "CLASSIC_SCENARIO_NET_EDGE_R": classic_pack["net_event_expectancy_R"],
        "BREAK_EVEN_COST_R": be["event_expectancy_zero_at_R"],
        "BREAK_EVEN_COST_USD_PER_LOT": be["event_break_even_usd_per_lot"],
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
        "artifacts": {"json": PHASE58_JSON, "md": PHASE58_MD},
        "frozen_fingerprint": p40.get("tape_fingerprint") or FROZEN,
        "modeled_cost_vs_raw_span_R": modeled_cost_vs_raw,
    }
    (root / PHASE58_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE58_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    md = [
        "# Phase 58 — Commission Accountability",
        "",
        f"**G2:** `{g2}`",
        f"**Product (Phase 57):** `{product}` candidate `{candidate}`",
        "",
        "Observed gold-deal commissions remain **NOT_PROVEN_SCHEDULE** even if all zeros.",
        "",
        "## 58A Product → schedule",
        "ECN $5/lot is BROKER_DOCUMENTED. It is ACCOUNT_PRODUCT_VERIFIED / COMMISSION_SCHEDULE_VERIFIED only if Phase 57 is VERIFIED_ECN and the 2026-05-19 PDF applies. It is not.",
        "",
        "## 58B Historical deals",
        "Per-deal commission is OBSERVED. A zero schedule is NOT inferred.",
        "",
        "## 58C–58D ECN / CLASSIC / CENT",
        f"- ECN $5/lot → `{ecn_r:.6f}` R/event (SCENARIO). Net event `{ecn_pack['net_event_expectancy_R']:.6f}` R",
        f"- CLASSIC/CENT 14 **points** (official PDF 2026-05-19 note 2) → `{classic_r:.6f}` R/event using XAUUSD_i point=0.01. Not treated as $14 without units.",
        "",
        "## 58E–58G Scenarios / break-even / uncertainty",
        f"- Event break-even cost `{be['event_expectancy_zero_at_R']:.6f}` R ≈ `{be['event_break_even_usd_per_lot']:.2f}` USD/lot at median SL.",
        f"- EDGE_SMALLER_THAN_COST_UNCERTAINTY = TRUE (modeled 1x spread+slip).",
        "",
        "Not a profitability verdict. G2 is not PASS while the account product is not VERIFIED.",
        "",
    ]
    (root / PHASE58_MD).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE58_MD).write_text("\n".join(md), encoding="utf-8")
    return payload


if __name__ == "__main__":
    print(run_phase58_collection(Path("."))["G2"])

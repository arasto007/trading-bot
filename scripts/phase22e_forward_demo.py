#!/usr/bin/env python3
"""PHASE 22E 10-day forward demo certification. Research/shadow only. No live patches.

Runs only Phase 22B certified engines. 22B certified none, so no new demo
portfolio is started. Existing PA demo logs are audited observationally.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.update({
    "USE_ML_KERNEL": "false",
    "TRADINGBOT_DISABLE_JOURNAL": "1",
    "TRADINGBOT_DRY_RUN": "1",
})

from tradingbot.config.dotenv_loader import load_dotenv
load_dotenv()

from tradingbot.config.live import PRIMARY_SYMBOL
from tradingbot.research.portfolio_router import MODEL_TO_ENGINE

OUT = ROOT / "logs" / "phase22e"
CERT_22B = ROOT / "logs" / "phase22b" / "certification_matrix.json"
CERT_22D = ROOT / "logs" / "phase22d" / "phase22d_result.txt"
JOURNAL = ROOT / "data" / "trade_journal.db"
META_LOG = ROOT / "data" / "meta_decisions.jsonl"
PA_LIVE = ROOT / "logs" / "engines" / "pa_live_decisions.jsonl"
PA_EVENTS = ROOT / "logs" / "engines" / "pa_events.jsonl"
MATRIX_22A = ROOT / "logs" / "phase22a" / "strategy_discovery_matrix.json"

TARGET_DAYS = 10
MIN_TRADES = 30
PF_GATE = 1.20
EXP_GATE = 0.10
MAX_DD_PCT_GATE = 5.0
CANONICAL = "XAUUSD"
BROKER = "XAUUSD_I"
MATERIAL_PF_RATIO = 0.35


def emit(msg: str) -> None:
    print(msg, flush=True)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(raw: Any) -> datetime | None:
    if raw is None:
        return None
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)
    except Exception:
        return None


def trading_days(end: datetime, n: int = TARGET_DAYS) -> list[str]:
    days = []
    d = end.date()
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d.isoformat())
        d -= timedelta(days=1)
    return list(reversed(days))


def load_certified() -> list[str]:
    if not CERT_22B.is_file():
        return []
    blob = json.loads(CERT_22B.read_text(encoding="utf-8"))
    names = []
    for line in str(blob.get("result_block") or "").splitlines():
        if line.startswith("CERTIFIED_MODELS="):
            val = line.split("=", 1)[1].strip()
            if val and val != "NONE":
                for p in val.split(","):
                    names.append(MODEL_TO_ENGINE.get(p.strip(), p.strip()))
    return [x for x in names if x and x != "NONE"]


def read_jsonl(path: Path, *, since: datetime, until: datetime) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            ts = parse_ts(row.get("timestamp") or row.get("ts") or row.get("logged_at"))
            if ts is None or ts < since or ts > until:
                continue
            out.append(row)
    return out

def journal_window(since: datetime, until: datetime) -> dict[str, Any]:
    empty = {
        "executions": [], "paper_closed": [], "exec_fail": 0, "symbol_mismatch": 0,
        "duplicates": 0, "abnormal_stops": 0,
    }
    if not JOURNAL.is_file():
        return empty
    since_s, until_s = since.isoformat(), until.isoformat()
    with sqlite3.connect(JOURNAL) as conn:
        conn.row_factory = sqlite3.Row
        execs = [dict(r) for r in conn.execute(
            "SELECT * FROM executions WHERE ts >= ? AND ts <= ?", (since_s, until_s)
        ).fetchall()]
        papers = [dict(r) for r in conn.execute(
            "SELECT * FROM paper_trades WHERE COALESCE(time_close, time_open) >= ? AND COALESCE(time_close, time_open) <= ?",
            (since_s, until_s),
        ).fetchall()]
    fail = sum(1 for r in execs if not int(r.get("success") or 0))
    mismatch = 0
    for r in execs + papers:
        sym = str(r.get("symbol") or "").upper().replace(".", "")
        if sym and CANONICAL not in sym and BROKER not in sym and "XAUUSD" not in sym:
            mismatch += 1
    keys = []
    dup = 0
    for r in execs:
        if not int(r.get("success") or 0):
            continue
        k = (str(r.get("ts") or "")[:16], str(r.get("direction")), str(r.get("symbol")))
        if k in keys:
            dup += 1
        keys.append(k)
    abnormal = 0
    for r in papers:
        reason = str(r.get("exit_reason") or "").lower()
        if reason in ("error", "broker_stopout", "invalid", "abnormal"):
            abnormal += 1
        sl, tp, entry = r.get("sl"), r.get("tp"), r.get("fill_price") or r.get("entry_price")
        if sl and entry and abs(float(sl) - float(entry)) < 1e-8:
            abnormal += 1
    return {
        "executions": execs,
        "paper_closed": [p for p in papers if str(p.get("status") or "") in ("closed", "complete", "") and p.get("time_close")],
        "paper_all": papers,
        "exec_fail": fail,
        "symbol_mismatch": mismatch,
        "duplicates": dup,
        "abnormal_stops": abnormal,
    }


def pa_funnel(rows: list[dict[str, Any]]) -> dict[str, int]:
    raw = 0
    accepted = 0
    reasons = Counter()
    for r in rows:
        reasons[str(r.get("reject_reason") or "ok")] += 1
        sweep = bool(r.get("sweep_detected"))
        if sweep:
            raw += 1
        if not r.get("reject_reason") and (r.get("session_ok") or r.get("sweep_detected")):
            accepted += 1
        elif str(r.get("reject_reason") or "") in ("", "none", "ok"):
            accepted += 1
    return {"raw_setups": raw, "accepted_setups": accepted, "rows": len(rows), "reasons": dict(reasons)}


def meta_funnel(rows: list[dict[str, Any]]) -> dict[str, int]:
    acc = sum(1 for r in rows if r.get("allowed") is True)
    rej = sum(1 for r in rows if r.get("allowed") is False)
    return {"meta_accepted": acc, "meta_rejected": rej, "meta_decisions": len(rows)}


def metrics_from_r(rs: list[float], pnls: list[float] | None = None, start_eq: float = 200.0) -> dict[str, Any]:
    if not rs:
        return {"trades": 0, "pf": 0.0, "exp_r": 0.0, "max_dd_r": 0.0, "max_dd_pct": 0.0, "win_rate": 0.0}
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    gw, gl = sum(wins), abs(sum(losses))
    pf = (gw / gl) if gl > 0 else (99.0 if gw > 0 else 0.0)
    eq = peak = mdd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    dd_pct = 0.0
    if pnls:
        cash = start_eq
        cpeak = start_eq
        cmdd = 0.0
        for p in pnls:
            cash += float(p)
            cpeak = max(cpeak, cash)
            if cpeak > 0:
                cmdd = max(cmdd, (cpeak - cash) / cpeak * 100.0)
        dd_pct = cmdd
    else:
        dd_pct = (mdd / max(start_eq / 10.0, 1.0)) * 100.0
    return {
        "trades": len(rs),
        "pf": round(min(pf, 99.0), 4),
        "exp_r": round(sum(rs) / len(rs), 4),
        "max_dd_r": round(mdd, 4),
        "max_dd_pct": round(dd_pct, 4),
        "win_rate": round(100.0 * len(wins) / len(rs), 2),
    }


def backtest_expectation() -> dict[str, Any]:
    out = {"source": "phase22a_30d_MODEL_A", "pf": None, "exp_r": None, "trades": 0}
    if not MATRIX_22A.is_file():
        return out
    blob = json.loads(MATRIX_22A.read_text(encoding="utf-8"))
    m = (((blob.get("windows") or {}).get("30d") or {}).get("MODEL_A_CURRENT_PA")) or {}
    out["pf"] = m.get("profit_factor")
    out["exp_r"] = m.get("expectancy_R")
    out["trades"] = m.get("trades")
    m180 = (((blob.get("windows") or {}).get("180d") or {}).get("MODEL_A_CURRENT_PA")) or {}
    out["pf_180d"] = m180.get("profit_factor")
    out["exp_180d"] = m180.get("expectancy_R")
    return out


def material_divergence(demo_pf: float, bt_pf: float | None, n: int) -> tuple[bool, str]:
    if bt_pf is None or n < 8:
        return False, "insufficient_demo_or_missing_backtest"
    if bt_pf <= 0 and demo_pf <= 0:
        return False, "both_nonpositive"
    if bt_pf <= 0 < demo_pf:
        return False, "demo_better_than_negative_backtest"
    ratio = abs(demo_pf - float(bt_pf)) / max(abs(float(bt_pf)), 1e-6)
    if ratio >= MATERIAL_PF_RATIO:
        return True, "pf_relative_gap=%.3f" % ratio
    return False, "pf_relative_gap=%.3f" % ratio

def cycle_flags(since: datetime, until: datetime) -> dict[str, int]:
    stale = 0
    if not JOURNAL.is_file():
        return {"stale_mentions": 0}
    with sqlite3.connect(JOURNAL) as conn:
        rows = conn.execute(
            "SELECT ts, state, detail FROM cycle_events WHERE ts >= ? AND ts <= ?",
            (since.isoformat(), until.isoformat()),
        ).fetchall()
    for ts, state, detail in rows:
        blob = ("%s %s" % (state, detail)).lower()
        if "stale" in blob or "bar_lag" in blob:
            stale += 1
    return {"stale_mentions": stale, "cycle_rows": len(rows)}


def risk_from_pa_events(rows: list[dict[str, Any]]) -> dict[str, int]:
    appr = rej = 0
    for r in rows:
        ev = str(r.get("event") or r.get("type") or "").lower()
        if "risk" in ev or r.get("risk_allowed") is not None:
            if r.get("risk_allowed") is True or "approv" in ev:
                appr += 1
            elif r.get("risk_allowed") is False or "reject" in ev:
                rej += 1
        reason = str(r.get("reason") or r.get("reject_reason") or "").lower()
        if "risk" in reason and "reject" in reason:
            rej += 1
    return {"riskgate_approved": appr, "riskgate_rejected": rej}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    certified = load_certified()
    end = now_utc()
    days = trading_days(end, TARGET_DAYS)
    since = datetime.fromisoformat(days[0] + "T00:00:00+00:00")
    until = end
    emit("certified=%s window %s -> %s days=%s" % (certified or ["NONE"], days[0], days[-1], len(days)))

    forward_started = bool(certified)
    if not certified:
        emit("NO 22B-certified engines. Forward demo portfolio NOT started. STOP promotion.")

    journal = journal_window(since, until)
    pa_live = read_jsonl(PA_LIVE, since=since, until=until)
    pa_ev = read_jsonl(PA_EVENTS, since=since, until=until)
    meta_rows = read_jsonl(META_LOG, since=since, until=until)
    funnel = pa_funnel(pa_live)
    meta_f = meta_funnel(meta_rows)
    risk_f = risk_from_pa_events(pa_ev)
    stale = cycle_flags(since, until)

    closed = journal["paper_closed"]
    rs = [float(t.get("pnl_r") or 0.0) for t in closed]
    pnls = [float(t.get("pnl") or 0.0) for t in closed]
    demo_m = metrics_from_r(rs, pnls)
    slips = [float(e["slippage_pips"]) for e in journal["executions"] if e.get("slippage_pips") is not None]
    spreads = [float(t["spread"]) for t in journal.get("paper_all") or [] if t.get("spread") is not None]
    latencies = []
    for e in journal["executions"]:
        ts = parse_ts(e.get("ts"))
        # no request ts; skip
    bt = backtest_expectation()
    diverged, div_reason = material_divergence(float(demo_m["pf"]), bt.get("pf"), int(demo_m["trades"]))

    active_days = sorted({(parse_ts(r.get("timestamp") or r.get("logged_at")).date().isoformat())
                          for r in pa_live if parse_ts(r.get("timestamp") or r.get("logged_at"))})
    obs_days = len([d for d in days if d in set(active_days)])

    exec_fail = int(journal["exec_fail"])
    abnormal = int(journal["abnormal_stops"])
    mismatch = int(journal["symbol_mismatch"])
    stale_exec = int(stale.get("stale_mentions") or 0)
    dups = int(journal["duplicates"])

    # Certification uses certified-engine closed trades only (empty).
    cert_trades = 0
    cert_m = metrics_from_r([])
    gates = {
        "certified_candidates_exist": bool(certified),
        "forward_run_started": forward_started,
        "trading_days_ge_10": False if not forward_started else obs_days >= TARGET_DAYS,
        "closed_trades_ge_30": cert_trades >= MIN_TRADES,
        "pf_gt_1_20": float(cert_m["pf"]) > PF_GATE,
        "exp_gt_0_10": float(cert_m["exp_r"]) > EXP_GATE,
        "maxdd_lt_5pct": float(cert_m["max_dd_pct"]) < MAX_DD_PCT_GATE and cert_trades > 0,
        "no_execution_failures": exec_fail == 0,
        "no_abnormal_stops": abnormal == 0,
        "no_symbol_mismatch": mismatch == 0,
        "no_stale_data_execution": stale_exec == 0,
        "no_duplicate_entries": dups == 0,
        "no_material_demo_vs_backtest_divergence": not diverged if cert_trades >= 8 else True,
    }
    passed = all(gates.values())
    stop = True
    if passed:
        stop = False

    trades_path = OUT / "observational_trades.jsonl"
    with trades_path.open("w", encoding="utf-8") as fh:
        for t in closed:
            fh.write(json.dumps({
                "timestamp": t.get("time_close") or t.get("time_open"),
                "engine": t.get("engine") or "PA",
                "raw_setups": None,
                "accepted": True,
                "meta": None,
                "riskgate": None,
                "executed": True,
                "sl": t.get("sl"),
                "tp": t.get("tp"),
                "mfe": t.get("mfe"),
                "mae": t.get("mae"),
                "R": t.get("pnl_r"),
                "PnL": t.get("pnl"),
                "spread": t.get("spread"),
                "slippage": None,
                "latency": None,
                "symbol": t.get("symbol"),
                "direction": t.get("direction"),
                "exit_reason": t.get("exit_reason"),
                "certified_engine": False,
            }, default=str) + "\n")

    result_lines = [
        "PHASE_22E_RESULT",
        "",
        "CERTIFIED_CANDIDATES=%s" % (",".join(certified) if certified else "NONE"),
        "FORWARD_RUN_STARTED=%s" % ("YES" if forward_started else "NO"),
        "TRADING_DAYS=%s" % (obs_days if forward_started else 0),
        "CLOSED_TRADES=%s" % cert_trades,
        "PF=%s" % cert_m["pf"],
        "EXPR=%s" % cert_m["exp_r"],
        "MAX_DD_PCT=%s" % cert_m["max_dd_pct"],
        "",
        "EXECUTION_FAILURES=%s" % exec_fail,
        "ABNORMAL_STOPS=%s" % abnormal,
        "SYMBOL_MISMATCH=%s" % mismatch,
        "STALE_DATA_EXEC=%s" % stale_exec,
        "DUPLICATE_ENTRIES=%s" % dups,
        "",
        "BACKTEST_PF_30D_PA=%s" % bt.get("pf"),
        "OBS_DEMO_PA_TRADES=%s" % demo_m["trades"],
        "OBS_DEMO_PA_PF=%s" % demo_m["pf"],
        "OBS_DEMO_PA_EXPR=%s" % demo_m["exp_r"],
        "DEMO_VS_BACKTEST=%s" % div_reason,
        "MATERIAL_DIVERGENCE=%s" % ("YES" if diverged else "NO"),
        "",
        "STOP_PROMOTION=YES",
        "CERTIFIED_FOR_PROMOTION=NO",
        "KEEP_SHADOW_MODE=YES",
        "LIVE_PATCH_APPLIED=NO",
        "",
    ]
    result = "\n".join(result_lines)
    matrix = {
        "phase": "22E",
        "live_files_modified": False,
        "certified_candidates": certified,
        "forward_run_started": forward_started,
        "window_days": days,
        "observational_only": not forward_started,
        "funnel": {
            **funnel,
            **meta_f,
            **risk_f,
            "executed": len(journal["executions"]),
            "executed_ok": len(journal["executions"]) - exec_fail,
            "paper_closed": len(closed),
        },
        "safety": {
            "execution_failures": exec_fail,
            "abnormal_stops": abnormal,
            "symbol_mismatch": mismatch,
            "stale_data_mentions": stale_exec,
            "duplicate_entries": dups,
        },
        "certified_portfolio_metrics": cert_m,
        "observational_pa_demo": demo_m,
        "backtest_expectation": bt,
        "divergence": {"material": diverged, "reason": div_reason},
        "avg_slippage_pips": None if not slips else round(sum(slips) / len(slips), 4),
        "avg_spread": None if not spreads else round(sum(spreads) / len(spreads), 4),
        "gates": gates,
        "passed": passed,
        "stop_promotion": stop,
        "result_block": result,
    }
    (OUT / "forward_demo_matrix.json").write_text(json.dumps(matrix, indent=2, default=str), encoding="utf-8")
    extra = result + "NOTES\n" + json.dumps({
        "reason_no_forward": "phase22b_certified_none",
        "observational_pa_funnel": funnel,
        "meta": meta_f,
        "risk": risk_f,
        "stale": stale,
        "gates": gates,
        "did_not_enable_uncertified_engines": True,
        "did_not_modify_live_router": True,
    }, indent=2) + "\nLIVE_PATCH_APPLIED=NO\n"
    (OUT / "phase22e_result.txt").write_text(extra, encoding="utf-8")
    emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
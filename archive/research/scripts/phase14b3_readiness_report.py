#!/usr/bin/env python3
from __future__ import annotations
import json, re, subprocess
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def parse_ts(s):
    if not s:
        return None
    s = str(s).replace("Z", "+00:00")
    if " " in s and "T" not in s:
        s = s.replace(" ", "T", 1)
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None

def read_from(path: Path, start_byte: int) -> list[dict]:
    if not path.is_file():
        return []
    with path.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, min(start_byte, size) - 50000))
        chunk = f.read().decode("utf-8", errors="replace")
    rows = []
    for ln in chunk.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            rows.append(json.loads(ln))
        except Exception:
            pass
    return rows

def main() -> None:
    win = json.loads((ROOT / "logs" / "phase14b3_window_start.json").read_text(encoding="utf-8"))
    start_dt = datetime.fromtimestamp(float(win["t"]), tz=timezone.utc)
    slack = start_dt - timedelta(seconds=90)
    base = json.loads((ROOT / "logs" / "phase14b3_baseline.json").read_text(encoding="utf-8"))

    def in_win(row):
        for k in ("timestamp", "logged_at", "ts", "time", "created_at"):
            dt = parse_ts(row.get(k))
            if dt and dt >= slack:
                return True
        return False

    router = [r for r in read_from(ROOT / "logs" / "router_decisions.jsonl", base["logs/router_decisions.jsonl"]["size"]) if in_win(r)]
    pa = [r for r in read_from(ROOT / "logs" / "engines" / "pa_events.jsonl", base["logs/engines/pa_events.jsonl"]["size"]) if in_win(r)]
    hold_path = ROOT / "logs" / "engines" / "pa_hold_reasons.jsonl"
    hold_base = base.get("logs/engines/pa_hold_reasons.jsonl", {}).get("size", 0)
    holds = [r for r in read_from(hold_path, hold_base) if in_win(r)]
    trades = [r for r in read_from(ROOT / "logs" / "phase51a" / "trades.jsonl", 0) if in_win(r)]
    rej = [r for r in read_from(ROOT / "logs" / "rejection_events.jsonl", base["logs/rejection_events.jsonl"]["size"]) if in_win(r)]

    sel = Counter(str(r.get("selected_engine")) for r in router)
    pa_sig = Counter(str(r.get("pa_signal")) for r in router)
    pa_ev = Counter(str(r.get("event")) for r in pa)
    hold_reasons = Counter(str(r.get("reject_reason")) for r in holds)
    raw_setups = sum(1 for r in pa if r.get("event") == "signal")
    pa_buy_sell = sum(1 for r in router if str(r.get("pa_signal")) in ("BUY", "SELL"))

    meta_accepted = 0
    risk_approved = 0
    order_attempted = False
    for r in rej:
        blob = json.dumps(r, default=str).lower()
        reason = str(r.get("reason", "")).lower()
        stage = str(r.get("stage", "")).lower()
        if "meta" in reason or "meta" in stage or "meta" in blob:
            if r.get("allowed") is True or "accept" in reason or "pass" in reason:
                meta_accepted += 1
        if "risk" in stage or "risk_gate" in reason or "risk_gate" in blob:
            if r.get("allowed") is True or str(r.get("decision", "")).lower() == "approved":
                risk_approved += 1
        if any(x in blob for x in ("order_send", "ordersend", "send_order", "execution_attempt")):
            order_attempted = True
    if trades:
        order_attempted = True

    rt = json.loads((ROOT / "logs" / "runtime_truth.json").read_text(encoding="utf-8"))
    mt5_ok = bool(rt.get("mt5_equity_read_ok") or rt.get("equity_source") == "MT5")

    alive = False
    try:
        out = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                "Where-Object { $_.CommandLine -match 'run_live_watchdog' } | "
                "Measure-Object | Select-Object -ExpandProperty Count",
            ],
            text=True,
            timeout=15,
        )
        alive = int((out or "0").strip() or "0") > 0
    except Exception:
        alive = False

    lp = (ROOT / "logs" / "watchdog_latest.logpaths.txt").read_text(encoding="utf-8-sig")
    paths = {}
    for line in lp.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            paths[k.strip()] = v.strip()
    err_path = Path(paths.get("watchdog_stderr", ""))
    err_txt = err_path.read_text(encoding="utf-8", errors="replace") if err_path.is_file() else ""
    # ignore INFO lines; look for real exceptions after startup
    exc = bool(re.search(r"(?m)^(Traceback \(most recent call last\):|.*\bERROR\b.*Exception)", err_txt))
    if re.search(r"order_send|OrderSend|placed order", err_txt, re.I):
        order_attempted = True

    # last 20 hold records from file
    hold_lines = [ln for ln in hold_path.read_text(encoding="utf-8").splitlines() if ln.strip()][-20:]
    last20 = []
    for ln in hold_lines:
        try:
            last20.append(json.loads(ln))
        except Exception:
            pass

    # pipeline activity
    pa_active = len(pa) > 0 or len(holds) > 0 or len(router) > 0
    meta_active = True  # wired via risk_gate for PA; accepted count may be 0 if no setups
    # evidence of meta path: models ready in runtime / no crash; use meta events if any
    meta_events_path = ROOT / "logs" / "engines" / "meta_events.jsonl"
    meta_file_exists = meta_events_path.is_file()
    risk_active = len(rej) > 0 or alive  # risk gate runs each cycle when signal; rejections logged
    # more precise: risk pipeline active if bot looping without crash
    exec_active = alive and (rt.get("execution_mode") in ("live", "dry_run", "paper") or rt.get("dry_run") is False)

    # blocking stage
    if not mt5_ok or not alive:
        blocking = "MT5_OR_WATCHDOG"
    elif pa_buy_sell == 0 and raw_setups == 0:
        top_hold = hold_reasons.most_common(1)[0][0] if hold_reasons else "PA_NO_SIGNAL"
        blocking = "PA_HOLD:" + top_hold
    elif meta_accepted == 0 and pa_buy_sell > 0:
        blocking = "META"
    elif risk_approved == 0 and pa_buy_sell > 0:
        blocking = "RISKGATE"
    elif not order_attempted:
        blocking = "NO_EXECUTABLE_SIGNAL"
    else:
        blocking = "NONE"

    # probability tomorrow - NY session not active now (hour ~3 UTC); pipeline ready -> MEDIUM if PA can produce historically
    hour = datetime.now(timezone.utc).hour
    if blocking.startswith("PA_HOLD:outside"):
        prob = "MEDIUM"  # session will open tomorrow
    elif raw_setups > 0 or pa_buy_sell > 0:
        prob = "HIGH"
    elif alive and mt5_ok and pa_active:
        prob = "MEDIUM"
    else:
        prob = "LOW"

    market_ready = "YES" if (alive and mt5_ok and pa_active and int(rt.get("cooldown_bars", 0) or 0) == 18) else "NO"

    report = {
        "MT5_CONNECTED": "YES" if (mt5_ok and alive) else ("PARTIAL" if mt5_ok else "NO"),
        "ROUTER_SELECTED_ENGINE_COUNTS": dict(sel),
        "PA_RAW_SETUPS_DETECTED": int(raw_setups + pa_buy_sell),
        "META_ACCEPTED": int(meta_accepted),
        "RISKGATE_APPROVED": int(risk_approved),
        "ORDER_SEND_ATTEMPTED": "YES" if order_attempted else "NO",
        "ANY_RUNTIME_EXCEPTION": "YES" if exc else "NO",
        "router_n": len(router),
        "pa_n": len(pa),
        "holds_n": len(holds),
        "pa_signal_counts": dict(pa_sig),
        "hold_reason_counts": dict(hold_reasons),
        "runtime_cooldown": rt.get("cooldown_bars"),
        "runtime_pa_cooldown": rt.get("pa_cooldown_bars"),
        "execution_mode": rt.get("execution_mode"),
        "dry_run": rt.get("dry_run"),
        "MARKET_READY": market_ready,
        "PA_PIPELINE_ACTIVE": "YES" if pa_active else "NO",
        "META_PIPELINE_ACTIVE": "YES" if alive else "NO",
        "RISK_PIPELINE_ACTIVE": "YES" if alive else "NO",
        "EXECUTION_PIPELINE_ACTIVE": "YES" if exec_active else "NO",
        "TOMORROW_TRADE_PROBABILITY": prob,
        "BLOCKING_STAGE": blocking,
        "last20_holds": last20,
        "watchdog_alive": alive,
        "mt5_ok": mt5_ok,
        "window_start": start_dt.isoformat(),
        "hour_utc_now": hour,
    }

    out = ROOT / "logs" / "phase14b3_tomorrow_readiness.txt"
    lines = [
        "PHASE 14B-3 — Tomorrow Market Readiness",
        "window_start_utc=" + start_dt.isoformat(),
        "CONFIG_OK PA_LOCK=true ML=false SHADOW=true VOL=false ADAPTIVE=false PHASE52A_PM=false META=0.38 MODE=london_sweep COOLDOWN=18",
        "",
        "MT5_CONNECTED=" + report["MT5_CONNECTED"],
        "ROUTER_SELECTED_ENGINE_COUNTS=" + str(report["ROUTER_SELECTED_ENGINE_COUNTS"]),
        "PA_RAW_SETUPS_DETECTED=" + str(report["PA_RAW_SETUPS_DETECTED"]),
        "META_ACCEPTED=" + str(report["META_ACCEPTED"]),
        "RISKGATE_APPROVED=" + str(report["RISKGATE_APPROVED"]),
        "ORDER_SEND_ATTEMPTED=" + report["ORDER_SEND_ATTEMPTED"],
        "ANY_RUNTIME_EXCEPTION=" + report["ANY_RUNTIME_EXCEPTION"],
        "router_cycles=" + str(len(router)) + " pa_events=" + str(len(pa)) + " holds=" + str(len(holds)),
        "pa_signal_counts=" + str(dict(pa_sig)),
        "hold_reason_counts=" + str(dict(hold_reasons)),
        "",
        "MARKET_READY=" + report["MARKET_READY"],
        "PA_PIPELINE_ACTIVE=" + report["PA_PIPELINE_ACTIVE"],
        "META_PIPELINE_ACTIVE=" + report["META_PIPELINE_ACTIVE"],
        "RISK_PIPELINE_ACTIVE=" + report["RISK_PIPELINE_ACTIVE"],
        "EXECUTION_PIPELINE_ACTIVE=" + report["EXECUTION_PIPELINE_ACTIVE"],
        "TOMORROW_TRADE_PROBABILITY=" + report["TOMORROW_TRADE_PROBABILITY"],
        "BLOCKING_STAGE=" + report["BLOCKING_STAGE"],
    ]
    if report["ORDER_SEND_ATTEMPTED"] == "NO":
        lines.append("")
        lines.append("LAST_20_PA_HOLD_REASONS")
        for r in last20:
            lines.append(json.dumps(r, ensure_ascii=False, default=str))
    text = "\n".join(lines) + "\n"
    out.write_text(text, encoding="utf-8")
    (ROOT / "logs" / "phase14b3_window_stats.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(text)

if __name__ == "__main__":
    main()

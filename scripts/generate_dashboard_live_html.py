#!/usr/bin/env python3
"""Build full live panel HTML from snapshot lines (no VBScript HTML)."""
from __future__ import annotations

from pathlib import Path

from scripts.hta_html_fragments import _badge, _esc, write_hta_html_fragments

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "dashboard_live.html"
VERSION = "v10.0.0"


def _parse(lines: list[str]) -> dict[str, object]:
    d: dict[str, object] = {
        "state": "OFFLINE",
        "utc": "-",
        "equity": "-",
        "balance": "-",
        "pnl": "-",
        "watchdog": "-",
        "bot": "-",
        "kernel": "-",
        "note": "",
        "ml": "-",
        "ml_detail": "-",
        "pa_pf": "-",
        "pa_expr": "-",
        "pa_accept": "-",
        "pa_trades": "0",
        "engines": [],
        "tasks": [],
        "signals": [],
        "cycles": [],
        "phase4": [],
        "alerts": [],
    }
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("STATE|"):
            d["state"] = "RUNNING" if "RUNNING" in line else "STOPPED"
        elif line.startswith("UTC|"):
            d["utc"] = line[4:]
        elif line.startswith("ACCOUNT|"):
            p = line.split("|")
            if len(p) >= 4:
                d["balance"] = p[1]
                d["equity"] = p[2]
                d["pnl"] = p[3]
        elif line.startswith("WATCHDOG|"):
            d["watchdog"] = line[10:]
        elif line.startswith("BOT|"):
            d["bot"] = line[5:]
        elif line.startswith("KERNEL|"):
            d["kernel"] = line[8:]
        elif line.startswith("NOTE|"):
            d["note"] = line[5:]
        elif line.startswith("ML|"):
            p = line.split("|")
            if len(p) >= 2:
                d["ml"] = p[1]
            if len(p) >= 3:
                d["ml_detail"] = p[2]
        elif line.startswith("ENGINE|"):
            p = line.split("|")
            if len(p) >= 8:
                row = {
                    "name": p[1],
                    "state": p[2],
                    "accept": p[4].replace("accept=", ""),
                    "trades": p[5].replace("trades=", ""),
                    "pf": p[6].replace("PF=", ""),
                    "expr": p[7].replace("ExpR=", ""),
                }
                d["engines"].append(row)
                if p[1].upper() == "PA":
                    d["pa_accept"] = row["accept"] + "%"
                    d["pa_trades"] = row["trades"]
                    d["pa_pf"] = row["pf"]
                    d["pa_expr"] = row["expr"] + "R"
        elif line.startswith("TASK|"):
            p = line.split("|")
            if len(p) >= 4:
                d["tasks"].append({"name": p[1], "state": p[2], "detail": p[3]})
        elif line.startswith("SIGNAL|"):
            d["signals"].insert(0, line[7:])
        elif line.startswith("CYCLE|"):
            p = line.split("|")
            if len(p) >= 5:
                d["cycles"].append(f"{p[2]} | {p[3]} | {p[4]}")
        elif line.startswith(("PROP|", "DRIFT|", "SLIP|", "SPREAD|")):
            d["phase4"].append(line.split("|", 1)[-1])
        elif line.startswith("ALERT|"):
            p = line.split("|")
            if len(p) >= 4:
                d["alerts"].append((p[2], p[3]))
    return d


def _engine_html(engines: list[dict[str, str]]) -> str:
    rows = []
    for e in engines:
        rows.append(
            "<tr><td class='engine-name'>"
            f"{_esc(e['name'])}</td><td>{_badge(e['state'])}</td>"
            f"<td class='engine-metrics'>{_esc(e['accept'])}% | {_esc(e['trades'])} tr | "
            f"PF {_esc(e['pf'])} | {_esc(e['expr'])}R</td></tr>"
        )
    return "<table class='engine-table'>" + "".join(rows) + "</table>" if rows else "-"


def _task_html(tasks: list[dict[str, str]]) -> str:
    rows = []
    for t in tasks:
        rows.append(
            f"<div class='task'><span>{_esc(t['name'])}</span> "
            f"{_badge(t['state'])} <span class='muted'>{_esc(t['detail'])}</span></div>"
        )
    return "".join(rows) if rows else "-"


def build_html(lines: list[str]) -> str:
    d = _parse(lines)
    state = str(d["state"])
    state_cls = "badge-run" if state == "RUNNING" else "badge-off"
    note = str(d["note"])
    note_block = (
        f"<div class='demo-banner show'>{_esc(note)}</div>" if note else ""
    )
    alerts = d["alerts"]
    alert_block = ""
    if alerts:
        items = "".join(
            f"<div class='alert-item'><b>{_esc(a)}</b> {_esc(b)}</div>"
            for a, b in alerts
        )
        alert_block = f"<div class='alert-banner show'>{items}</div>"

    signals = d["signals"]
    signal_html = (
        "".join(f"<div class='signal'>{_esc(s)}</div>" for s in signals)
        or "<div class='muted'>No signals yet</div>"
    )
    cycles = d["cycles"]
    cycle_html = "".join(f"<div class='cycle'>{_esc(c)}</div>" for c in cycles) or "-"
    phase4 = d["phase4"]
    phase4_html = "".join(f"<div class='cycle'>{_esc(p)}</div>" for p in phase4) or "-"

    mt5 = "LINK" if str(d["equity"]) != "-" else "OFF"
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<title>Live Panel {VERSION}</title>
<style>
body{{margin:0;padding:16px 20px;background:#0E0E10;color:#E8E6E3;font-family:Segoe UI,Tahoma,Arial;font-size:12px}}
.badge{{display:inline-block;padding:2px 8px;border-radius:3px;font-size:10px;font-weight:600}}
.badge-run{{background:#0F1A14;color:#3DDC84;border:1px solid #3DDC84}}
.badge-off{{background:#1A1A20;color:#5C5854;border:1px solid #2A2A30}}
.badge-warn{{background:#1A1408;color:#F0C040;border:1px solid #6B5A2E}}
.demo-banner{{background:#1A1408;border:1px solid #6B5A2E;color:#F0C040;padding:8px 16px;border-radius:4px;margin-bottom:12px}}
.alert-banner{{background:#1A1408;border:1px solid #6B5A2E;padding:12px;border-radius:4px;margin:12px 0}}
.card{{background:#141418;border:1px solid #2A2A30;border-radius:4px;padding:16px;margin-bottom:12px}}
.card-title{{font-size:9px;text-transform:uppercase;letter-spacing:1px;color:#5C5854;margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid #2A2A30}}
.hero{{font-size:32px;font-weight:700;color:#D4AF37;font-family:Consolas,monospace}}
.kpi{{font-size:20px;font-weight:600;font-family:Consolas,monospace}}
.muted{{color:#5C5854;font-size:10px}}
.engine-table{{width:100%;border-collapse:collapse}}
.engine-table td{{padding:6px 0;border-bottom:1px solid #1E1E24;font-size:11px}}
.engine-name{{color:#D4AF37;font-weight:600;width:80px}}
.engine-metrics{{font-family:Consolas,monospace;color:#8B8680;text-align:right}}
.task{{padding:5px 0;border-bottom:1px solid #1E1E24}}
.signal,.cycle{{font-family:Consolas,monospace;font-size:10px;color:#8B8680;padding:4px 0;border-bottom:1px solid #1E1E24}}
.row{{width:100%;border-collapse:separate;border-spacing:12px 0;margin-bottom:12px}}
.footer{{font-family:Consolas,monospace;font-size:10px;color:#5C5854;padding:8px 0;border-top:1px solid #2A2A30;margin-top:8px}}
</style></head><body>
{note_block}
<table class="row"><tr>
<td width="62%" valign="top"><div class="card">
<div class="card-title">Aggregate Account Equity</div>
<div class="hero">${_esc(str(d['equity']))}</div>
<div class="muted">Balance ${_esc(str(d['balance']))} | PnL ${_esc(str(d['pnl']))}</div>
<div style="margin-top:10px"><span class="badge {state_cls}">{_esc(state)}</span></div>
</div></td>
<td width="38%" valign="top"><div class="card">
<div class="card-title">Automation Scheduler</div>
{_task_html(d['tasks'])}
</div></td></tr></table>
<table class="row"><tr>
<td width="25%"><div class="card"><div class="card-title">Profit Factor</div>
<div class="kpi">{_esc(str(d['pa_pf']))}</div><div class="muted">{_esc(str(d['pa_trades']))} trades | PA</div></div></td>
<td width="25%"><div class="card"><div class="card-title">Expectancy R</div>
<div class="kpi">{_esc(str(d['pa_expr']))}</div><div class="muted">per trade</div></div></td>
<td width="25%"><div class="card"><div class="card-title">Acceptance</div>
<div class="kpi">{_esc(str(d['pa_accept']))}</div><div class="muted">setup pass rate</div></div></td>
<td width="25%"><div class="card"><div class="card-title">ML Stack</div>
<div class="kpi" style="font-size:16px">{_esc(str(d['ml']))}</div>
<div class="muted">{_esc(str(d['ml_detail']))}</div></div></td>
</tr></table>
<table class="row"><tr>
<td width="50%" valign="top"><div class="card"><div class="card-title">Engine Health</div>
{_engine_html(d['engines'])}
</div><div class="card"><div class="card-title">Phase 4</div>{phase4_html}</div></td>
<td width="50%" valign="top"><div class="card"><div class="card-title">Signal Stream</div>{signal_html}</div>
<div class="card"><div class="card-title">Last Cycles</div>{cycle_html}</div></td>
</tr></table>
{alert_block}
<div class="footer">UTC {_esc(str(d['utc']))} | MT5 {mt5} | WD {_esc(str(d['watchdog']))} | BOT {_esc(str(d['bot']))} | {VERSION}</div>
</body></html>"""


def write_dashboard_live_html(lines: list[str], root: Path | None = None) -> Path:
    root = root or ROOT
    write_hta_html_fragments(lines, root)
    html = build_html(lines)
    out = root / "data" / "dashboard_live.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="ascii", errors="replace")
    return out


if __name__ == "__main__":
    cache = ROOT / "data" / "hta_dashboard_snapshot.txt"
    if cache.is_file():
        lines = cache.read_text(encoding="utf-8", errors="replace").splitlines()
    else:
        lines = ["STATE|STOPPED", "UTC|-", "ACCOUNT|-|-|-"]
    p = write_dashboard_live_html(lines)
    print("OK", p, "bytes", p.stat().st_size)

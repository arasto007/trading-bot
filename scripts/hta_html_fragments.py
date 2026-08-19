#!/usr/bin/env python3
"""Generate HTML fragment files for HTA (no < in VBScript)."""
from __future__ import annotations

from pathlib import Path


def _esc(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _badge(st: str) -> str:
    u = st.upper()
    if u in ("ACTIVE", "HEALTHY", "RUNNING", "ON", "LIVE"):
        cls = "badge-run"
    elif u == "DEGRADED":
        cls = "badge-warn"
    elif u in ("DISABLED", "OFF", "STOPPED"):
        cls = "badge-off"
    else:
        cls = "badge-live"
    return f"<span class='badge {cls}'>{_esc(st)}</span>"


def write_hta_html_fragments(lines: list[str], root: Path) -> None:
    engine_rows: list[str] = []
    task_rows: list[str] = []
    signal_rows: list[str] = []
    cycle_rows: list[str] = []
    phase4_rows: list[str] = []
    alert_rows: list[str] = []

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("ENGINE|"):
            parts = line.split("|")
            if len(parts) >= 8:
                engine_rows.append(
                    "<table class='engine-row'><tr>"
                    f"<td class='engine-name'>{_esc(parts[1])}</td>"
                    f"<td class='engine-state'>{_badge(parts[2])}</td>"
                    f"<td class='engine-metrics'>"
                    f"{_esc(parts[4].replace('accept=', ''))}% | "
                    f"{_esc(parts[5].replace('trades=', ''))} tr | "
                    f"PF {_esc(parts[6].replace('PF=', ''))} | "
                    f"{_esc(parts[7].replace('ExpR=', ''))}R"
                    f"</td></tr></table>"
                )
        elif line.startswith("TASK|"):
            parts = line.split("|")
            if len(parts) >= 4:
                task_rows.append(
                    "<table class='task-row'><tr>"
                    f"<td class='task-name'>{_esc(parts[1])}</td>"
                    f"<td class='task-badge'>{_badge(parts[2])} "
                    f"<span style='color:#5C5854;font-size:9px'>{_esc(parts[3])}</span></td>"
                    "</tr></table>"
                )
        elif line.startswith("SIGNAL|"):
            signal_rows.insert(0, f"<div class='signal-row'>{_esc(line[7:])}</div>")
        elif line.startswith("CYCLE|"):
            parts = line.split("|")
            if len(parts) >= 5:
                cycle_rows.append(
                    f"<div class='cycle'>{_esc(parts[2])} | {_esc(parts[3])} | {_esc(parts[4])}</div>"
                )
        elif line.startswith("PROP|"):
            phase4_rows.append(f"<div class='cycle'>Prop: {_esc(line[5:])}</div>")
        elif line.startswith("DRIFT|"):
            phase4_rows.append(f"<div class='cycle'>Drift: {_esc(line[6:])}</div>")
        elif line.startswith("SLIP|"):
            phase4_rows.append(f"<div class='cycle'>Slippage: {_esc(line[5:])}</div>")
        elif line.startswith("SPREAD|"):
            phase4_rows.append(f"<div class='cycle'>Spread: {_esc(line[7:])} pips</div>")
        elif line.startswith("ALERT|"):
            parts = line.split("|")
            if len(parts) >= 4:
                alert_rows.append(
                    f"<div class='alert-item'><b>{_esc(parts[2])}</b> {_esc(parts[3])}</div>"
                )

    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "hta_engine.html").write_text("".join(engine_rows), encoding="ascii", errors="replace")
    (data / "hta_tasks.html").write_text("".join(task_rows), encoding="ascii", errors="replace")
    (data / "hta_signals.html").write_text(
        "".join(signal_rows) or "<div class='cycle'>No signals yet</div>",
        encoding="ascii",
        errors="replace",
    )
    (data / "hta_cycles.html").write_text("".join(cycle_rows), encoding="ascii", errors="replace")
    (data / "hta_phase4.html").write_text(
        "".join(phase4_rows) or "-",
        encoding="ascii",
        errors="replace",
    )
    (data / "hta_alerts.html").write_text("".join(alert_rows), encoding="ascii", errors="replace")

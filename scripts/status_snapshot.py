#!/usr/bin/env python3
"""خروجی فشرده وضعیت live — برای پنل HTA (بدون emoji)."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

# severity|code|message — خطوط ALERT برای پاپ‌آپ HTA
Alert = tuple[str, str, str]


def _process_state() -> dict[str, object]:
    """Detect live kernel watchdog + bot only."""
    state: dict[str, object] = {
        "kernel_watchdog": False,
        "kernel_bot": False,
        "kernel_running": False,
        "watchdog_running": False,
        "bot_running": False,
        "watchdog_pid": None,
        "bot_pid": None,
    }
    try:
        out = subprocess.check_output(
            [
                "powershell",
                "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                "Where-Object { $_.CommandLine -match "
                "'run_live_watchdog|tradingbot.*--loop' } | "
                "Select-Object ProcessId, CommandLine | ConvertTo-Json -Compress",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=8,
        ).strip()
        if out:
            rows = json.loads(out)
            if isinstance(rows, dict):
                rows = [rows]
            for row in rows:
                cmd = str(row.get("CommandLine", ""))
                pid = row.get("ProcessId")
                if "run_live_watchdog" in cmd:
                    state["kernel_watchdog"] = True
                    state["watchdog_pid"] = pid
                elif "tradingbot" in cmd and "--loop" in cmd:
                    state["kernel_bot"] = True
                    state["bot_pid"] = pid

        state["kernel_running"] = bool(
            state["kernel_watchdog"] or state["kernel_bot"]
        )
        state["watchdog_running"] = bool(state["kernel_watchdog"])
        state["bot_running"] = bool(state["kernel_bot"])
    except Exception:
        pass
    return state


def _parse_ts(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def _recent(ts: str, *, minutes: int = 12) -> bool:
    dt = _parse_ts(ts)
    if dt is None:
        return True
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - dt <= timedelta(minutes=minutes)


def _load_startup_report() -> dict[str, object] | None:
    path = ROOT / "data" / "startup" / "startup_report.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _startup_report_fresh(report: dict[str, object] | None, *, hours: int = 24) -> bool:
    if not report:
        return False
    ts = _parse_ts(str(report.get("startup_timestamp", "")))
    if ts is None:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - ts <= timedelta(hours=hours)


def _kernel_mt5_ok(proc: dict[str, object]) -> bool:
    """Trust live bot MT5 session — never steal IPC from dashboard polls."""
    if not proc.get("kernel_bot"):
        return False
    try:
        from tradingbot.adapters.mt5_utils import is_mt5_lock_held_by_other

        if is_mt5_lock_held_by_other():
            return True
    except Exception:
        pass
    report = _load_startup_report()
    if not _startup_report_fresh(report):
        return False
    return bool(report and report.get("mt5_connected"))


def _mt5_process_running() -> bool:
    from tradingbot.adapters.mt5_utils import _is_terminal_process_running

    return _is_terminal_process_running()


def _account_line_from_live_cache(*, max_age_sec: int = 120) -> str | None:
    path = ROOT / "data" / "live_account.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        ts = _parse_ts(str(data.get("updated_at", "")))
        if ts is not None:
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - ts).total_seconds()
            if age > max_age_sec:
                return None
        bal = data.get("balance")
        eq = data.get("equity")
        profit = data.get("profit")
        if bal is None:
            return None
        return (
            f"ACCOUNT|{round(float(bal), 2)}|"
            f"{round(float(eq), 2) if eq is not None else '-'}|"
            f"{round(float(profit), 2) if profit is not None else '-'}"
        )
    except Exception:
        return None


def _account_line_from_report(*, label: str = "-") -> str | None:
    report = _load_startup_report()
    if not _startup_report_fresh(report, hours=48):
        return None
    bal = (report or {}).get("account_balance")
    eq = (report or {}).get("account_equity")
    if bal is None:
        return None
    return (
        f"ACCOUNT|{round(float(bal), 2)}|"
        f"{round(float(eq), 2) if eq is not None else '-'}|{label}"
    )


def _account_line(*, kernel_mt5_ok: bool = False, bot_running: bool = False) -> str | None:
    try:
        from tradingbot.adapters.mt5_utils import is_mt5_lock_held_by_other

        if bot_running or (is_mt5_lock_held_by_other() and kernel_mt5_ok):
            report = _load_startup_report() or {}
            bal = report.get("account_balance")
            eq = report.get("account_equity")
            if bal is not None:
                return f"ACCOUNT|{round(float(bal), 2)}|{round(float(eq), 2) if eq is not None else '-'}|-"
            return "ACCOUNT|live|-|-"

        if is_mt5_lock_held_by_other():
            return None

        if not _mt5_process_running() and not kernel_mt5_ok:
            return None
        import MetaTrader5 as mt5

        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.adapters.mt5_utils import attach_mt5_session

        cfg = load_legacy_config()
        if not attach_mt5_session(cfg, strict_account=False, use_lock=False):
            if not kernel_mt5_ok:
                return None
        acc = mt5.account_info()
        if acc is None:
            if kernel_mt5_ok:
                report = _load_startup_report() or {}
                bal = report.get("account_balance")
                if bal is not None:
                    return f"ACCOUNT|{round(float(bal), 2)}|-|-"
            return None
        return (
            f"ACCOUNT|{round(acc.balance, 2)}|{round(acc.equity, 2)}|"
            f"{round(acc.profit, 2)}"
        )
    except Exception:
        return None


def _latest_backtest_line() -> str | None:
    reports_dir = ROOT / "reports"
    if not reports_dir.is_dir():
        return None
    candidates = sorted(
        reports_dir.glob("backtest_range_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return None
    try:
        data = json.loads(candidates[0].read_text(encoding="utf-8"))
        rows = data.get("results") or []
        total_trades = sum(int(r.get("range_trades", 0)) for r in rows)
        net = 0.0
        for row in rows:
            rm = row.get("range_metrics") or {}
            net += float(rm.get("net_profit") or 0.0)
        tag = candidates[0].stem.replace("backtest_range_", "")[:40]
        return f"BT|{tag}|trades={total_trades}|net={round(net, 2)}"
    except Exception:
        return None


def _watchdog_log_line() -> str | None:
    path = ROOT / "logs" / "watchdog.log"
    if not path.is_file():
        return None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in reversed(lines[-30:]):
            line = line.strip()
            if line:
                safe = _ascii_safe(line.replace("|", "/"))
                return f"LOG|watchdog|{safe[:180]}"
    except OSError:
        pass
    return None


def _watchdog_restart_alerts() -> list[Alert]:
    """Warn when bot keeps exiting cleanly (often MT5 IPC conflict from dashboard)."""
    path = ROOT / "logs" / "watchdog.log"
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    unexpected = 0
    last_ts: datetime | None = None
    for line in text.splitlines():
        if "Unexpected clean exit" not in line:
            continue
        ts_raw = line.split("|", 1)[0].strip()
        ts = _parse_ts(ts_raw)
        if ts is None:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts >= cutoff:
            unexpected += 1
            last_ts = ts
    if unexpected >= 2:
        when = last_ts.strftime("%H:%M UTC") if last_ts else "recent"
        return [
            (
                "warn",
                "BOT_RESTART_LOOP",
                f"Bot exited cleanly {unexpected}x in last hour (last {when}) — check MT5 IPC",
            )
        ]
    return []


def _ascii_safe(text: str) -> str:
    """HTA/VBScript فقط ASCII را درست می‌خواند — جزئیات انگلیسی."""
    return text.encode("ascii", errors="replace").decode("ascii")


def _mt5_alerts(*, kernel_mt5_ok: bool = False) -> list[Alert]:
    alerts: list[Alert] = []
    if kernel_mt5_ok:
        report = _load_startup_report() or {}
        if report.get("autotrading_ready") is False:
            alerts.append(
                (
                    "critical",
                    "TRADE_NOT_ALLOWED",
                    "AutoTrading OFF in MT5 (from startup report)",
                )
            )
        return alerts

    try:
        from tradingbot.adapters.mt5_utils import is_mt5_lock_held_by_other

        if is_mt5_lock_held_by_other():
            return alerts
    except Exception:
        pass

    if not _mt5_process_running():
        alerts.append(
            (
                "warn",
                "MT5_CLOSED",
                "MT5 not running — open terminal manually then Ctrl+E",
            )
        )
        return alerts

    try:
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.adapters.mt5_health import check_autotrading_ready, check_mt5_health
        from tradingbot.adapters.mt5_utils import attach_mt5_session
        from tradingbot.adapters.symbols import resolve_broker_symbol
        from tradingbot.config.live import PRIMARY_SYMBOL

        cfg = load_legacy_config()
        if not attach_mt5_session(cfg, strict_account=False, use_lock=False):
            alerts.append(
                (
                    "critical",
                    "MT5_DISCONNECTED",
                    "MT5 terminal not connected",
                )
            )
            return alerts

        sym = (cfg.get("SYMBOLS") or [PRIMARY_SYMBOL])[0]
        broker = resolve_broker_symbol(sym, cfg)

        auto_ok, auto_msg = check_autotrading_ready(sym, config=cfg)
        if not auto_ok:
            if "10027" in auto_msg or "AutoTrading OFF" in auto_msg:
                alerts.append(
                    (
                        "critical",
                        "TRADE_NOT_ALLOWED",
                        _ascii_safe(auto_msg),
                    )
                )
            return alerts

        health = check_mt5_health(broker, max_tick_age_sec=120.0)
        if not health.connected:
            alerts.append(
                (
                    "critical",
                    "MT5_DISCONNECTED",
                    _ascii_safe(f"MT5 health: {health.reason}"),
                )
            )
        elif health.reason != "ok":
            alerts.append(
                (
                    "warn",
                    "HEALTH_FAIL",
                    _ascii_safe(f"MT5 health: {health.reason}"),
                )
            )
    except ImportError:
        alerts.append(
            (
                "critical",
                "MT5_DISCONNECTED",
                "MetaTrader5 package not installed",
            )
        )
    except Exception as e:
        alerts.append(
            (
                "critical",
                "MT5_DISCONNECTED",
                _ascii_safe(f"MT5 check error: {e}"),
            )
        )
    return alerts


def _journal_alerts() -> list[Alert]:
    alerts: list[Alert] = []
    journal = ROOT / "data" / "trade_journal.db"
    if not journal.exists():
        return alerts

    try:
        conn = sqlite3.connect(journal)
        cur = conn.cursor()
        cur.execute(
            "SELECT ts, market, state, detail FROM cycle_events ORDER BY id DESC LIMIT 40"
        )
        rows = cur.fetchall()
        conn.close()
    except Exception as e:
        return [("error", "JOURNAL_ERROR", _ascii_safe(f"journal read error: {e}"))]

    seen: set[str] = set()
    for ts, market, state, detail in rows:
        if not _recent(ts):
            continue
        detail = detail or ""
        st = (state or "").lower()

        if st == "mt5_disconnected" and "MT5_DISCONNECTED" not in seen:
            seen.add("MT5_DISCONNECTED")
            alerts.append(
                (
                    "critical",
                    "MT5_DISCONNECTED",
                    _ascii_safe(f"bot: MT5 disconnected - {detail or 'ensure_connected failed'}"),
                )
            )
        elif st == "health_fail" and "HEALTH_FAIL" not in seen:
            seen.add("HEALTH_FAIL")
            alerts.append(
                (
                    "warn",
                    "HEALTH_FAIL",
                    _ascii_safe(f"bot: health check - {detail or 'failed'}"),
                )
            )
        elif st in ("emergency_stop", "emergency") and "EMERGENCY_STOP" not in seen:
            seen.add("EMERGENCY_STOP")
            alerts.append(
                (
                    "critical",
                    "EMERGENCY_STOP",
                    _ascii_safe(f"kernel emergency stop - {detail or market}"),
                )
            )
        elif st == "blocked" and detail:
            low = detail.lower()
            if any(k in low for k in ("error", "fail", "exception")) and "BOT_ERROR" not in seen:
                seen.add("BOT_ERROR")
                alerts.append(
                    (
                        "error",
                        "BOT_ERROR",
                        _ascii_safe(f"cycle error - {detail[:200]}"),
                    )
                )

    return alerts


def _alerts_log_alerts(*, kernel_bot: bool = False) -> list[Alert]:
    alerts: list[Alert] = []
    path = ROOT / "logs" / "alerts.log"
    if not path.is_file():
        return alerts

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]
    except OSError:
        return alerts

    recent_success = any(
        "LiveRunner started" in ln or "STARTUP OK" in ln for ln in lines
    )

    for line in reversed(lines):
        upper = line.upper()
        if "KILL SWITCH" in upper:
            alerts.append(
                (
                    "critical",
                    "KILL_SWITCH",
                    _ascii_safe(
                        line.split("|", 1)[-1].strip() if "|" in line else line.strip()
                    ),
                )
            )
            break
        if "EMERGENCY_STOP" in upper or "EMERGENCY STOP" in upper:
            alerts.append(
                (
                    "critical",
                    "EMERGENCY_STOP",
                    _ascii_safe(
                        line.split("|", 1)[-1].strip() if "|" in line else line.strip()
                    ),
                )
            )
            break

    for line in reversed(lines):
        if line.startswith("CRITICAL |") or line.startswith("ERROR |"):
            msg = line.split("|", 1)[-1].strip()
            if "KILL SWITCH" in msg.upper():
                continue
            if "Startup refused" in msg and recent_success:
                continue
            if kernel_bot and recent_success and "Startup refused" in msg:
                continue
            alerts.append(("error", "BOT_ERROR", _ascii_safe(msg)))
            break

    return alerts


def _dedupe_alerts(items: list[Alert]) -> list[Alert]:
    """یک هشدار per code — شدیدترین severity برنده می‌شود."""
    order = {"critical": 0, "error": 1, "warn": 2}
    best: dict[str, Alert] = {}
    for severity, code, message in items:
        cur = best.get(code)
        if cur is None or order.get(severity, 9) < order.get(cur[0], 9):
            best[code] = (severity, code, message)
    return list(best.values())


def _demo_note_line() -> str | None:
    try:
        from tradingbot.domain.filter_policy import demo_session_override_active

        if demo_session_override_active():
            return (
                "NOTE|DEMO: session filter DISABLED for demo testing — "
                "set DEMO_DISABLE_SESSION_FILTER=false before live"
            )
    except Exception:
        pass
    return None


def _engine_dashboard_lines() -> list[str]:
    path = ROOT / "logs" / "engines" / "dashboard_latest.json"
    if not path.is_file():
        return []
    lines: list[str] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        for key, eng in (data.get("engines") or {}).items():
            m = eng.get("metrics") or {}
            lines.append(
                "ENGINE|"
                f"{key}|"
                f"{eng.get('current_state', '-')}|"
                f"enabled={1 if eng.get('enabled') else 0}|"
                f"accept={round(float(m.get('acceptance_rate', 0)) * 100, 2)}|"
                f"trades={m.get('executed_trades', 0)}|"
                f"PF={m.get('PF', 0)}|"
                f"ExpR={m.get('expectancy_R', 0)}"
            )
        drift = (data.get("global_flags") or {}).get("drift_detail") or {}
        if drift.get("drift_detected"):
            lines.append(
                f"META|drift|live={drift.get('live_mean_prob', '-')}|"
                f"oos={drift.get('oos_reference', '-')}"
            )
    except Exception as e:
        lines.append(f"ENGINE|error|read failed|{e}")
    return lines


def _router_signal_lines(limit: int = 5) -> list[str]:
    path = ROOT / "logs" / "router_decisions.jsonl"
    if not path.is_file():
        return []
    lines: list[str] = []
    try:
        raw = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for row in raw[-limit:]:
            if not row.strip():
                continue
            rec = json.loads(row)
            lines.append(
                "SIGNAL|"
                f"{rec.get('timestamp', '-')}|"
                f"PA={rec.get('pa_signal', 'HOLD')}|"
                f"VOL={rec.get('vol_signal', 'HOLD')}|"
                f"ADP={rec.get('adaptive_signal', 'HOLD')}|"
                f"SEL={rec.get('selected_engine', 'NONE')}|"
                f"{rec.get('selected_direction', 'HOLD')}"
            )
    except Exception:
        pass
    return lines


def _automation_lines(proc: dict[str, object]) -> list[str]:
    return [
        "TASK|watchdog|"
        f"{'RUNNING' if proc.get('watchdog_running') else 'OFF'}|pid={proc.get('watchdog_pid') or '-'}",
        "TASK|bot_loop|"
        f"{'RUNNING' if proc.get('bot_running') else 'OFF'}|pid={proc.get('bot_pid') or '-'}",
        "TASK|eod_close|ON|23:55 UTC",
        "TASK|meta_gate|ON|threshold=0.38",
        "TASK|pa_lock|ON|VOL/Adaptive log-only",
    ]


HTA_CACHE = ROOT / "data" / "hta_dashboard_snapshot.txt"


def _emit(lines: list[str]) -> None:
    text = "\n".join(_ascii_safe(ln) for ln in lines) + "\n"
    sys.stdout.write(text)
    try:
        HTA_CACHE.parent.mkdir(parents=True, exist_ok=True)
        HTA_CACHE.write_text(text, encoding="ascii", errors="replace")
        import importlib.util

        for mod_name, rel in (
            ("hta_html_fragments", "hta_html_fragments.py"),
            ("generate_dashboard_live_html", "generate_dashboard_live_html.py"),
        ):
            mod_path = ROOT / "scripts" / rel
            spec = importlib.util.spec_from_file_location(mod_name, mod_path)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                if mod_name == "hta_html_fragments":
                    mod.write_hta_html_fragments(lines, ROOT)
                else:
                    mod.write_dashboard_live_html(lines, ROOT)
    except Exception:
        pass


def _journal_cycle_lines(limit: int = 4) -> list[str]:
    journal = ROOT / "data" / "trade_journal.db"
    if not journal.is_file():
        return ["CYCLE|-|-|no_data|journal missing"]
    lines: list[str] = []
    try:
        conn = sqlite3.connect(f"file:{journal}?mode=ro", uri=True, timeout=2.0)
        cur = conn.cursor()
        cur.execute(
            "SELECT ts, market, state, detail FROM cycle_events ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        for ts, market, state, detail in cur.fetchall():
            lines.append(f"CYCLE|{ts}|{market}|{state}|{detail or ''}")
        conn.close()
    except Exception as e:
        lines.append(f"ERR|journal:{e}")
    return lines or ["CYCLE|-|-|no_data|empty"]


def _main_body_bot_live(proc: dict[str, object]) -> int:
    """Dashboard poll while bot runs — zero MT5 imports/calls (IPC safe)."""
    lines: list[str] = []
    kernel_running = bool(proc["kernel_running"])
    lines.append(f"STATE|{'RUNNING' if kernel_running else 'STOPPED'}")
    lines.append(f"UTC|{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(
        "KERNEL|"
        f"{'RUNNING' if kernel_running else 'STOPPED'}"
        f"|watchdog={'RUNNING' if proc['kernel_watchdog'] else 'STOPPED'}"
        f"|bot={'RUNNING' if proc['kernel_bot'] else 'STOPPED'}"
    )
    lines.append(
        f"WATCHDOG|{'RUNNING' if proc['watchdog_running'] else 'STOPPED'}"
        f"|pid={proc['watchdog_pid'] or '-'}"
    )
    lines.append(
        f"BOT|{'RUNNING' if proc['bot_running'] else 'STOPPED'}"
        f"|pid={proc['bot_pid'] or '-'}"
    )

    report = _load_startup_report() or {}
    bal = report.get("account_balance")
    eq = report.get("account_equity")
    live = _account_line_from_live_cache(max_age_sec=86400)
    if live:
        lines.append(live)
    elif bal is not None:
        lines.append(
            f"ACCOUNT|{round(float(bal), 2)}|"
            f"{round(float(eq), 2) if eq is not None else '-'}|-"
        )
    else:
        lines.append("ACCOUNT|live|-|-")
        cached = _account_line_from_report(label="-")
        if cached:
            lines[-1] = cached

    log_line = _watchdog_log_line()
    if log_line:
        lines.append(log_line)

    lines.append("ML|VOL_REGIME|config=ATR2.5_RR0.8|vol=1")
    lines.append("PROP|none|none")
    lines.append("SPREAD|-|pips")
    drift_path = ROOT / "logs" / "drift_report.json"
    if drift_path.is_file():
        try:
            drift = json.loads(drift_path.read_text(encoding="utf-8"))
            lines.append(
                f"DRIFT|{drift.get('status', 'unknown')}|"
                f"trades={drift.get('live_trades', '-')}|"
                f"PF={drift.get('live_pf', '-')}|WR={drift.get('live_win_rate', '-')}"
            )
        except Exception:
            lines.append("DRIFT|cached|read error")
    else:
        lines.append("DRIFT|pending|run live ops or verify_phase4")

    note = _demo_note_line()
    if note:
        lines.append(note)
    lines.extend(_engine_dashboard_lines())
    lines.extend(_automation_lines(proc))
    lines.extend(_router_signal_lines())

    restart_alerts = _watchdog_restart_alerts()
    for severity, code, message in restart_alerts:
        lines.append(f"ALERT|{severity}|{code}|{_ascii_safe(message)}")
    lines.extend(_journal_cycle_lines())
    _emit(lines)
    return 0


def _main_body() -> int:
    lines: list[str] = []
    proc = _process_state()
    if proc.get("kernel_bot"):
        return _main_body_bot_live(proc)

    kernel_running = bool(proc["kernel_running"])
    lines.append(f"STATE|{'RUNNING' if kernel_running else 'STOPPED'}")
    lines.append(f"UTC|{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(
        "KERNEL|"
        f"{'RUNNING' if kernel_running else 'STOPPED'}"
        f"|watchdog={'RUNNING' if proc['kernel_watchdog'] else 'STOPPED'}"
        f"|bot={'RUNNING' if proc['kernel_bot'] else 'STOPPED'}"
    )
    lines.append(
        f"WATCHDOG|{'RUNNING' if proc['watchdog_running'] else 'STOPPED'}"
        f"|pid={proc['watchdog_pid'] or '-'}"
    )
    lines.append(
        f"BOT|{'RUNNING' if proc['bot_running'] else 'STOPPED'}"
        f"|pid={proc['bot_pid'] or '-'}"
    )

    kernel_mt5_ok = _kernel_mt5_ok(proc)
    bot_running = bool(proc.get("kernel_bot"))
    account = _account_line(kernel_mt5_ok=kernel_mt5_ok, bot_running=bot_running)
    if not account:
        account = _account_line_from_report(label="-")
    if account:
        lines.append(account)

    bt = _latest_backtest_line()
    if bt:
        lines.append(bt)

    log_line = _watchdog_log_line()
    if log_line:
        lines.append(log_line)

    try:
        from tradingbot.config.live import get_live_config
        from tradingbot.config.prop_presets import active_preset_name
        from tradingbot.services.live_reporting import current_spread_pips, journal_summary

        live_cfg = get_live_config()
        vol_on = bool(live_cfg.get("VOL_REGIME_ENABLED", False))
        cfg_id = live_cfg.get("VOL_REGIME_CONFIG_ID", "ATR2.5_RR0.8")
        if vol_on:
            lines.append(f"ML|VOL_REGIME|config={cfg_id}|vol=1")
        else:
            lines.append("ML|OFF|vol=0")

        preset = active_preset_name()
        preset_label = str(live_cfg.get("PROP_FIRM_NAME") or preset or "none")
        lines.append(f"PROP|{preset}|{preset_label}")

        j = journal_summary(ROOT, day=datetime.now(timezone.utc))
        slip_avg = j.get("slippage_avg_pips")
        slip_max = j.get("slippage_max_pips")
        slip_n = int(j.get("executions_total") or 0)
        lines.append(
            f"SLIP|avg={slip_avg if slip_avg is not None else '-'}|"
            f"max={slip_max if slip_max is not None else '-'}|n={slip_n}"
        )

        spread = None
        if not bot_running:
            spread = current_spread_pips(live_cfg)
        lines.append(f"SPREAD|{spread if spread is not None else '-'}|pips")

        drift_path = ROOT / "logs" / "drift_report.json"
        if drift_path.is_file():
            try:
                drift = json.loads(drift_path.read_text(encoding="utf-8"))
                d_status = str(drift.get("status") or "unknown")
                d_trades = drift.get("live_trades", "-")
                d_pf = drift.get("live_pf", "-")
                d_wr = drift.get("live_win_rate", "-")
                lines.append(f"DRIFT|{d_status}|trades={d_trades}|PF={d_pf}|WR={d_wr}")
                if d_status in ("warn", "critical"):
                    for alert in drift.get("alerts") or []:
                        lines.append(f"ALERT|{d_status}|DRIFT|{_ascii_safe(str(alert))}")
            except Exception as e:
                lines.append(f"DRIFT|error|{_ascii_safe(str(e))}")
        else:
            lines.append("DRIFT|pending|run live ops or verify_phase4")
    except Exception as e:
        lines.append(f"ML|ERROR|{e}")

    note = _demo_note_line()
    if note:
        lines.append(note)
    lines.extend(_engine_dashboard_lines())
    lines.extend(_automation_lines(proc))
    lines.extend(_router_signal_lines())

    live_alerts = _mt5_alerts(kernel_mt5_ok=kernel_mt5_ok)
    journal_alerts = _journal_alerts()
    log_alerts = _alerts_log_alerts(kernel_bot=bool(proc.get("kernel_bot")))
    restart_alerts = _watchdog_restart_alerts()
    live_codes = {code for _, code, _ in live_alerts}
    all_alerts = _dedupe_alerts(
        live_alerts + journal_alerts + log_alerts + restart_alerts
    )
    if kernel_mt5_ok:
        all_alerts = [
            a
            for a in all_alerts
            if not (
                a[1] == "MT5_DISCONNECTED"
                or (a[1] == "BOT_ERROR" and "Startup refused" in a[2])
            )
        ]
    if "MT5_DISCONNECTED" not in live_codes:
        all_alerts = [a for a in all_alerts if a[1] != "MT5_DISCONNECTED"]
    if "HEALTH_FAIL" not in live_codes:
        all_alerts = [a for a in all_alerts if a[1] != "HEALTH_FAIL"]
    all_alerts = _dedupe_alerts(all_alerts)
    for severity, code, message in all_alerts:
        safe = _ascii_safe(message.replace("|", "/").replace("\n", " ").strip())
        lines.append(f"ALERT|{severity}|{code}|{safe}")

    journal = ROOT / "data" / "trade_journal.db"
    if journal.exists():
        try:
            conn = sqlite3.connect(journal)
            cur = conn.cursor()
            cur.execute(
                "SELECT ts, market, state, detail FROM cycle_events ORDER BY id DESC LIMIT 4"
            )
            for ts, market, state, detail in cur.fetchall():
                lines.append(f"CYCLE|{ts}|{market}|{state}|{detail or ''}")
            conn.close()
        except Exception as e:
            lines.append(f"ERR|journal:{e}")
    else:
        lines.append("CYCLE|-|-|no_data|journal missing")

    _emit(lines)
    return 0


def main() -> int:
    try:
        return _main_body()
    except Exception as e:
        lines = [
            "STATE|STOPPED",
            f"UTC|{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}",
            f"ALERT|error|BOT_ERROR|status_snapshot failed: {e}",
        ]
        _emit(lines)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

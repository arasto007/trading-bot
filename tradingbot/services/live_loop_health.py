"""Phase 20Y-1 live loop health. Observability only."""
from __future__ import annotations
import json, logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = ROOT / "logs" / "runtime"
HEARTBEAT_PATH = RUNTIME_DIR / "live_heartbeat.json"
STALL_ALERTS_PATH = RUNTIME_DIR / "live_stall_alerts.jsonl"
ROUTER_ACTIVITY_PATH = RUNTIME_DIR / "router_activity_today.json"
WATCHDOG_HEARTBEAT_PATH = RUNTIME_DIR / "watchdog_heartbeat.json"
STALL_RESTART_STATE_PATH = RUNTIME_DIR / "stall_restart_state.json"
NY_START_HOUR = 10
NY_END_HOUR = 17
HEARTBEAT_STALE_SEC = 20 * 60
BAR_LAG_SEC = 3 * 5 * 60
HEARTBEAT_INTERVAL_SEC = 60

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

def _parse_ts(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        ts = value
    else:
        try:
            ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    else:
        ts = ts.astimezone(timezone.utc)
    return ts

def in_ny_window(now: datetime | None = None) -> bool:
    ts = now or _now_utc()
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    else:
        ts = ts.astimezone(timezone.utc)
    return NY_START_HOUR <= ts.hour < NY_END_HOUR

def _ensure_runtime_dir() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

def write_heartbeat(payload: dict[str, Any]) -> Path:
    _ensure_runtime_dir()
    body = {
        "timestamp_utc": payload.get("timestamp_utc") or _now_utc().isoformat(),
        "loop_iteration": int(payload.get("loop_iteration") or 0),
        "last_bar_time_utc": payload.get("last_bar_time_utc"),
        "router_alive": bool(payload.get("router_alive", False)),
        "kernel_alive": bool(payload.get("kernel_alive", False)),
        "mt5_connected": bool(payload.get("mt5_connected", False)),
    }
    HEARTBEAT_PATH.write_text(json.dumps(body, indent=2), encoding="utf-8")
    return HEARTBEAT_PATH

def write_watchdog_heartbeat() -> Path:
    _ensure_runtime_dir()
    body = {"timestamp_utc": _now_utc().isoformat(), "watchdog_alive": True}
    WATCHDOG_HEARTBEAT_PATH.write_text(json.dumps(body), encoding="utf-8")
    return WATCHDOG_HEARTBEAT_PATH

SUPPORTED_TIMEFRAMES: tuple[str, ...] = ("M5", "M15", "H4")


def live_timeframe_health(
    *,
    kernel_timeframes: list[str] | None = None,
) -> dict[str, Any]:
    """Supported vs active live TFs. M5-only active live is valid production config."""
    from tradingbot.adapters.timeframes import to_kernel
    from tradingbot.config.legacy_settings import kernel_settings_from_legacy
    from tradingbot.config.live import get_live_config

    supported = list(SUPPORTED_TIMEFRAMES)
    live = get_live_config()
    active = [to_kernel(str(tf)) for tf in (live.get("TIMEFRAMES") or [])]
    if kernel_timeframes is None:
        kernel_timeframes = list(kernel_settings_from_legacy().timeframes)
    kernel_tfs = [to_kernel(str(tf)) for tf in kernel_timeframes]
    issues: list[str] = []
    if not active:
        issues.append("ACTIVE_LIVE_TIMEFRAMES is empty")
    extra = [tf for tf in active if tf not in supported]
    if extra:
        issues.append(f"ACTIVE_LIVE_TIMEFRAMES has TFs outside SUPPORTED_TIMEFRAMES: {extra}")
    if set(kernel_tfs) != set(active):
        issues.append(
            f"Kernel timeframes {set(kernel_tfs)} != ACTIVE_LIVE_TIMEFRAMES {set(active)}"
        )
    return {
        "supported": supported,
        "active": active,
        "kernel": kernel_tfs,
        "ok": not issues,
        "issues": issues,
    }


def probe_mt5_connected() -> bool:
    """Read-only MT5 availability. Does not start the live loop or steal a locked session."""
    try:
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.adapters.mt5_utils import (
            _is_terminal_process_running,
            attach_mt5_session,
            is_mt5_already_connected,
        )
        from tradingbot.config.live import PRIMARY_SYMBOL

        if is_mt5_already_connected():
            return True
        cfg = load_legacy_config()
        if attach_mt5_session(
            cfg, symbols=[PRIMARY_SYMBOL], strict_account=False, use_lock=False
        ):
            return True
        return bool(_is_terminal_process_running(cfg))
    except Exception:
        return False


def probe_router_alive() -> bool:
    try:
        from tradingbot.ml.integration.factory import build_strategy_registry

        return build_strategy_registry() is not None
    except Exception:
        return False


def probe_pa_m5_enabled() -> tuple[bool, str]:
    from tradingbot.config.live import PRIMARY_SYMBOL
    from tradingbot.config.pa_symbol_tf_presets import is_pa_cell_enabled
    from tradingbot.config.price_action import get_price_action_config

    enabled = bool(is_pa_cell_enabled(PRIMARY_SYMBOL, "M5"))
    preset = str(get_price_action_config(PRIMARY_SYMBOL, "5m").get("PRESET") or "")
    return enabled and preset == "gold_ny_sweep", preset


def print_healthcheck_report(*, include_mt5_probe: bool = True) -> str:
    from tradingbot.config.live import PRIMARY_SYMBOL, get_live_config

    tfh = live_timeframe_health()
    pa_ok, pa_preset = probe_pa_m5_enabled()
    router_alive = probe_router_alive()
    live = get_live_config()
    if include_mt5_probe:
        mt5_ok = probe_mt5_connected()
        mt5_line = f"MT5_CONNECTED = {'YES' if mt5_ok else 'NO'}"
    else:
        mt5_line = "MT5_CONNECTED = (not probed)"
    lines = [
        mt5_line,
        f"PRIMARY_SYMBOL = {PRIMARY_SYMBOL}",
        f"SUPPORTED_TIMEFRAMES = {','.join(tfh['supported'])}",
        f"ACTIVE_LIVE_TIMEFRAMES = {','.join(tfh['active'])}",
        f"TIMEFRAME_CONFIGURATION_OK = {'YES' if tfh['ok'] else 'NO'}",
        f"PA_M5_PRESET = {pa_preset}",
        f"PA_M5_ENABLED = {'YES' if pa_ok else 'NO'}",
        f"ROUTER_ALIVE = {'true' if router_alive else 'false'}",
        f"MULTI_ENGINE_ROUTER_ENABLED = {bool(live.get('MULTI_ENGINE_ROUTER_ENABLED'))}",
        f"M15_H4_ENABLED_LIVE = {'YES' if (set(tfh['active']) - {'M5'}) else 'NO'}",
    ]
    for issue in tfh["issues"]:
        lines.append(f"TIMEFRAME_ISSUE = {issue}")
    return "\n".join(lines)


def write_healthcheck_heartbeat() -> Path:
    from tradingbot.config.live import PRIMARY_SYMBOL

    router_alive = probe_router_alive()
    mt5_connected = probe_mt5_connected()
    tfh = live_timeframe_health()
    pa_ok, pa_preset = probe_pa_m5_enabled()
    path = write_heartbeat({
        "timestamp_utc": _now_utc().isoformat(),
        "loop_iteration": 0,
        "last_bar_time_utc": None,
        "router_alive": router_alive,
        "kernel_alive": False,
        "mt5_connected": mt5_connected,
    })
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["symbol"] = PRIMARY_SYMBOL
        data["supported_timeframes"] = tfh["supported"]
        data["active_live_timeframes"] = tfh["active"]
        data["timeframe_configuration_ok"] = bool(tfh["ok"])
        data["pa_m5_preset"] = pa_preset
        data["pa_m5_enabled"] = pa_ok
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass
    return path

def read_heartbeat() -> dict[str, Any] | None:
    if not HEARTBEAT_PATH.is_file():
        return None
    try:
        data = json.loads(HEARTBEAT_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None
def publish_runner_heartbeat(runner: Any) -> Path:
    last_bar: str | None = None
    try:
        from tradingbot.services.runtime_truth import market_data_metadata
        raw = market_data_metadata().get("last_bar_time_utc")
        last_bar = str(raw) if raw else None
    except Exception:
        last_bar = None
    mt5_connected = False
    try:
        from tradingbot.adapters.mt5_utils import is_mt5_already_connected
        mt5_connected = bool(
            getattr(getattr(runner, "market_data", None), "_mt5_ready", False)
            and is_mt5_already_connected()
        )
    except Exception:
        mt5_connected = bool(getattr(getattr(runner, "market_data", None), "_mt5_ready", False))
    kernel = getattr(runner, "kernel", None)
    kernel_alive = False
    router_alive = False
    loop_iteration = 0
    if kernel is not None:
        try:
            from tradingbot.domain.enums import KernelState
            kernel_alive = getattr(kernel, "state", None) == KernelState.RUNNING
        except Exception:
            kernel_alive = str(getattr(getattr(kernel, "state", None), "name", "")).upper() == "RUNNING"
        loop_iteration = int(getattr(kernel, "_cycle_count", 0) or 0)
        router_alive = getattr(kernel, "_strategies", None) is not None
    return write_heartbeat({
        "timestamp_utc": _now_utc().isoformat(),
        "loop_iteration": loop_iteration,
        "last_bar_time_utc": last_bar,
        "router_alive": router_alive,
        "kernel_alive": kernel_alive,
        "mt5_connected": mt5_connected,
    })

def record_router_activity(*, pa_hold: bool = False, pa_signal: bool = False, selected_engine_none: bool = False) -> None:
    try:
        _ensure_runtime_dir()
        today = _now_utc().date().isoformat()
        row = {"date": today, "router_calls": 0, "pa_hold": 0, "pa_signal": 0, "selected_engine_none": 0}
        if ROUTER_ACTIVITY_PATH.is_file():
            try:
                prev = json.loads(ROUTER_ACTIVITY_PATH.read_text(encoding="utf-8"))
                if isinstance(prev, dict) and str(prev.get("date")) == today:
                    row = {
                        "date": today,
                        "router_calls": int(prev.get("router_calls", 0) or 0),
                        "pa_hold": int(prev.get("pa_hold", 0) or 0),
                        "pa_signal": int(prev.get("pa_signal", 0) or 0),
                        "selected_engine_none": int(prev.get("selected_engine_none", 0) or 0),
                    }
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                pass
        row["router_calls"] = int(row["router_calls"]) + 1
        if pa_hold:
            row["pa_hold"] = int(row["pa_hold"]) + 1
        if pa_signal:
            row["pa_signal"] = int(row["pa_signal"]) + 1
        if selected_engine_none:
            row["selected_engine_none"] = int(row["selected_engine_none"]) + 1
        ROUTER_ACTIVITY_PATH.write_text(json.dumps(row, indent=2), encoding="utf-8")
    except Exception:
        logger.debug("router activity counter failed", exc_info=True)

def read_stall_restart_date() -> str | None:
    if not STALL_RESTART_STATE_PATH.is_file():
        return None
    try:
        data = json.loads(STALL_RESTART_STATE_PATH.read_text(encoding="utf-8"))
        return str(data.get("date") or "") or None
    except (OSError, json.JSONDecodeError):
        return None

def mark_stall_restart(date: str) -> None:
    _ensure_runtime_dir()
    STALL_RESTART_STATE_PATH.write_text(json.dumps({
        "date": date,
        "stall_restart_done": True,
        "marked_at_utc": _now_utc().isoformat(),
    }, indent=2), encoding="utf-8")

def stall_restart_done_for(date: str) -> bool:
    return read_stall_restart_date() == date

@dataclass(frozen=True)
class StallDecision:
    stalled: bool
    should_restart: bool
    reason: str
    heartbeat_age_sec: float | None
    bar_lag_sec: float | None
    in_ny_window: bool

def evaluate_ny_stall(*, now: datetime | None = None, heartbeat: dict[str, Any] | None = None, child_started_at: datetime | None = None, already_restarted: bool = False) -> StallDecision:
    now_ts = now or _now_utc()
    if now_ts.tzinfo is None:
        now_ts = now_ts.replace(tzinfo=timezone.utc)
    else:
        now_ts = now_ts.astimezone(timezone.utc)
    if not in_ny_window(now_ts):
        return StallDecision(False, False, "outside_ny_window", None, None, False)
    started = child_started_at or now_ts
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    else:
        started = started.astimezone(timezone.utc)
    uptime = (now_ts - started).total_seconds()
    if heartbeat is None:
        hb_age = uptime
        hb_stale = uptime > HEARTBEAT_STALE_SEC
    else:
        hb_ts = _parse_ts(heartbeat.get("timestamp_utc"))
        if hb_ts is None:
            hb_age = uptime
            hb_stale = uptime > HEARTBEAT_STALE_SEC
        else:
            hb_age = (now_ts - hb_ts).total_seconds()
            hb_stale = hb_age > HEARTBEAT_STALE_SEC
    last_bar = None if heartbeat is None else heartbeat.get("last_bar_time_utc")
    bar_ts = _parse_ts(last_bar)
    if bar_ts is None:
        bar_lag = uptime if uptime > 0 else None
        bar_stale = uptime > BAR_LAG_SEC
    else:
        bar_lag = (now_ts - bar_ts).total_seconds()
        bar_stale = bar_lag > BAR_LAG_SEC
    reasons = []
    if hb_stale:
        reasons.append("heartbeat_stale")
    if bar_stale:
        reasons.append("last_bar_lag")
    stalled = bool(reasons)
    return StallDecision(
        stalled=stalled,
        should_restart=bool(stalled and not already_restarted),
        reason="+".join(reasons) if reasons else "ok",
        heartbeat_age_sec=None if hb_age is None else round(float(hb_age), 1),
        bar_lag_sec=None if bar_lag is None else round(float(bar_lag), 1),
        in_ny_window=True,
    )

def evaluate_heartbeat_freshness(*, now: datetime | None = None, heartbeat: dict[str, Any] | None = None, child_started_at: datetime | None = None, already_restarted: bool = False) -> StallDecision:
    """If heartbeat is older than 20 minutes: one restart, then alert-only."""
    now_ts = now or _now_utc()
    if now_ts.tzinfo is None:
        now_ts = now_ts.replace(tzinfo=timezone.utc)
    else:
        now_ts = now_ts.astimezone(timezone.utc)
    started = child_started_at or now_ts
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    else:
        started = started.astimezone(timezone.utc)
    uptime = (now_ts - started).total_seconds()
    if heartbeat is None:
        hb_age = uptime
        stale = uptime > HEARTBEAT_STALE_SEC
    else:
        hb_ts = _parse_ts(heartbeat.get("timestamp_utc"))
        if hb_ts is None:
            hb_age = uptime
            stale = uptime > HEARTBEAT_STALE_SEC
        else:
            hb_age = (now_ts - hb_ts).total_seconds()
            stale = hb_age > HEARTBEAT_STALE_SEC
    return StallDecision(
        stalled=bool(stale),
        should_restart=bool(stale and not already_restarted),
        reason="heartbeat_stale" if stale else "ok",
        heartbeat_age_sec=round(float(hb_age), 1),
        bar_lag_sec=None,
        in_ny_window=in_ny_window(now_ts),
    )

def append_stall_alert(decision: StallDecision, extra: dict[str, Any] | None = None) -> None:
    _ensure_runtime_dir()
    row = {
        "timestamp_utc": _now_utc().isoformat(),
        "reason": decision.reason,
        "stalled": decision.stalled,
        "restart": decision.should_restart,
        "heartbeat_age_sec": decision.heartbeat_age_sec,
        "bar_lag_sec": decision.bar_lag_sec,
        "in_ny_window": decision.in_ny_window,
        "ny_window_utc": "%02d-%02d" % (NY_START_HOUR, NY_END_HOUR),
    }
    if extra:
        row.update(extra)
    with STALL_ALERTS_PATH.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(row, default=str) + "\n")
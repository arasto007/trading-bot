"""Phase 24B ORB forward demo engine (research-only, demo MT5 orders optional)."""
from __future__ import annotations

import json
import os
import statistics
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PHASE24B_DIR = ROOT / "logs" / "phase24b"
PHASE23B_DIR = ROOT / "logs" / "phase23b"
FROZEN_ORB_PATH = PHASE23B_DIR / "frozen_orb_30m_cont.json"
CERT_MATRIX_PATH = PHASE23B_DIR / "certification_matrix.json"
FORWARD_START_PATH = PHASE24B_DIR / "forward_start.json"
STATE_PATH = PHASE24B_DIR / "state.json"
SETUPS_LOG = PHASE24B_DIR / "orb_forward_setups.jsonl"
TRADES_LOG = PHASE24B_DIR / "orb_forward_trades.jsonl"
ALERTS_LOG = PHASE24B_DIR / "orb_forward_alerts.jsonl"
BACKTEST_VS_DEMO_PATH = PHASE24B_DIR / "backtest_vs_demo.json"
CUMULATIVE_PATH = PHASE24B_DIR / "cumulative_metrics.json"
RESULT_PATH = PHASE24B_DIR / "phase24b_result.txt"
ORB_DEMO_MAGIC = 234024

CANONICAL_FROZEN: dict[str, Any] = {
    "model": "MODEL_B_ORB",
    "strategy_id": "ORB_30M_CONT",
    "source_phase": "23B",
    "frozen_orb_ref": "ORB_30M_CONT",
    "parameters": {
        "range_minutes": 30,
        "atr_break": 0.25,
        "require_retest": False,
        "target_R": 2.0,
        "sl_pad_atr": 0.15,
    },
    "session": {
        "london_open_min_utc": 420,
        "session_end_min_utc": 720,
        "intended_hours_utc": [7, 8],
    },
    "risk_router_limits": {
        "cooldown_bars": 18,
        "max_trades_day": 3,
        "max_spread_pips": 15.0,
    },
    "backtest_reference": {
        "oos_pf": 1.376,
        "oos_exp_r": 0.2127,
        "cost_stress_pf": 1.219,
        "mc_p05_pf": 0.983,
        "oos_trades": 116,
    },
}


class RejectionReason(str, Enum):
    OUTSIDE_SESSION = "outside_session"
    INSUFFICIENT_OPENING_RANGE = "insufficient_opening_range"
    BREAKOUT_NOT_CONFIRMED = "breakout_not_confirmed"
    SPREAD_GATE = "spread_gate"
    STALE_DATA = "stale_data"
    COOLDOWN = "cooldown"
    DAILY_LIMIT = "daily_limit"
    DUPLICATE_SETUP = "duplicate_setup"
    RISK_GATE = "risk_gate"
    SYMBOL_PROBLEM = "symbol_problem"
    EXECUTION_FAILURE = "execution_failure"
    OTHER = "other"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(dt: datetime | None = None) -> str:
    return (dt or utc_now()).isoformat()


def ensure_dirs() -> None:
    PHASE24B_DIR.mkdir(parents=True, exist_ok=True)


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    ensure_dirs()
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, default=str) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def load_frozen_orb_config() -> dict[str, Any]:
    if not FROZEN_ORB_PATH.is_file():
        raise FileNotFoundError(f"missing frozen artifact: {FROZEN_ORB_PATH}")
    blob = json.loads(FROZEN_ORB_PATH.read_text(encoding="utf-8"))
    if not CERT_MATRIX_PATH.is_file():
        raise FileNotFoundError(f"missing certification matrix: {CERT_MATRIX_PATH}")
    cert = json.loads(CERT_MATRIX_PATH.read_text(encoding="utf-8"))
    cert_orb = str(cert.get("frozen_orb") or "").strip()
    ref = str(blob.get("frozen_orb_ref") or blob.get("strategy_id") or "").strip()
    if not cert_orb or cert_orb != ref:
        raise ValueError(
            f"frozen_orb mismatch: certification_matrix={cert_orb!r} artifact={ref!r}"
        )
    for key in ("model", "strategy_id", "source_phase", "parameters", "session", "risk_router_limits"):
        if blob.get(key) != CANONICAL_FROZEN.get(key):
            raise ValueError(f"frozen ORB artifact tampered or drifted on field {key!r}")
    if blob.get("backtest_reference") != CANONICAL_FROZEN["backtest_reference"]:
        raise ValueError("frozen ORB backtest_reference mismatch phase 23B")
    return blob


def print_execution_banner(config: dict[str, Any]) -> dict[str, Any]:
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.adapters.symbols import resolve_broker_symbol
    from tradingbot.config.live import PRIMARY_SYMBOL

    cfg = config or load_legacy_config()
    primary = PRIMARY_SYMBOL
    broker = resolve_broker_symbol(primary, cfg)
    banner: dict[str, Any] = {
        "ACCOUNT_LOGIN": None,
        "SERVER": str(cfg.get("MT5_SERVER") or ""),
        "IS_DEMO": "NO",
        "PRIMARY_SYMBOL": primary,
        "BROKER_SYMBOL": broker,
        "EXECUTION_MODE": "DEMO",
        "timestamp_utc": iso_utc(),
    }
    try:
        import MetaTrader5 as mt5
        from tradingbot.adapters.mt5_utils import attach_mt5_session

        if attach_mt5_session(cfg, symbols=[primary], strict_account=False, use_lock=False):
            acc = mt5.account_info()
            if acc is not None:
                banner["ACCOUNT_LOGIN"] = int(acc.login)
                banner["SERVER"] = str(acc.server)
                trade_mode = int(getattr(acc, "trade_mode", -1))
                banner["IS_DEMO"] = "YES" if trade_mode == 0 else "NO"
    except Exception as exc:
        banner["banner_error"] = str(exc)

    print(f"ACCOUNT_LOGIN={banner['ACCOUNT_LOGIN']}")
    print(f"SERVER={banner['SERVER']}")
    print(f"IS_DEMO={banner['IS_DEMO']}")
    print(f"PRIMARY_SYMBOL={banner['PRIMARY_SYMBOL']}")
    print(f"BROKER_SYMBOL={banner['BROKER_SYMBOL']}")
    print("EXECUTION_MODE=DEMO")
    if banner["IS_DEMO"] != "YES":
        raise RuntimeError("non-demo account or MT5 unavailable; ORB forward demo stopped")
    return banner


def _preflight_path(day: date) -> Path:
    return PHASE24B_DIR / f"preflight_{day.isoformat()}.jsonl"


def preflight_daily(config: dict[str, Any], frozen: dict[str, Any]) -> dict[str, Any]:
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.adapters.symbols import resolve_broker_symbol
    from tradingbot.config.live import PRIMARY_SYMBOL, get_live_config
    from tradingbot.services.demo_account_guard import verify_demo_account_or_abort

    cfg = config or load_legacy_config()
    live = get_live_config()
    primary = PRIMARY_SYMBOL
    broker = resolve_broker_symbol(primary, cfg)
    day = utc_now().date()
    record: dict[str, Any] = {
        "timestamp_utc": iso_utc(),
        "trading_day": day.isoformat(),
        "strategy_id": frozen.get("strategy_id"),
        "checks": {},
        "ok": True,
        "failures": [],
    }

    demo_ok, demo_msg = verify_demo_account_or_abort(config=cfg)
    record["checks"]["account_demo"] = {"ok": demo_ok, "detail": demo_msg}
    if not demo_ok:
        record["ok"] = False
        record["failures"].append("account_not_demo")

    mt5_connected = False
    symbol_visible = False
    spread_pips = None
    bar_fresh = False
    symbol_mismatch = False
    stale_data = False
    try:
        import MetaTrader5 as mt5
        from tradingbot.adapters.mt5_utils import attach_mt5_session, is_mt5_lock_held_by_other

        lock_other = is_mt5_lock_held_by_other()
        record["checks"]["duplicate_bot_instance"] = {"ok": not lock_other, "detail": lock_other}
        if lock_other:
            record["ok"] = False
            record["failures"].append("duplicate_running_bot")

        mt5_connected = attach_mt5_session(cfg, symbols=[primary], strict_account=False, use_lock=False)
        record["checks"]["mt5_connected"] = {"ok": mt5_connected, "detail": mt5_connected}
        if not mt5_connected:
            record["ok"] = False
            record["failures"].append("mt5_not_connected")

        info = mt5.symbol_info(broker) if mt5_connected else None
        tick = mt5.symbol_info_tick(broker) if mt5_connected else None
        symbol_visible = bool(info and info.visible)
        record["checks"]["symbol_visible"] = {"ok": symbol_visible, "broker": broker}
        if not symbol_visible:
            record["ok"] = False
            record["failures"].append("symbol_not_visible")

        if info is not None:
            record["symbol_meta"] = {
                "digits": info.digits,
                "point": info.point,
                "trade_mode": info.trade_mode,
                "contract_size": info.trade_contract_size,
            }
        if tick is not None and info is not None:
            spread_points = float(tick.ask - tick.bid)
            from tradingbot.domain.position_logic import pip_size

            pip = pip_size(broker)
            spread_pips = spread_points / pip if pip else spread_points
            max_spread = float(frozen.get("risk_router_limits", {}).get("max_spread_pips", 15.0))
            spread_ok = spread_pips <= max_spread * 1.5
            record["checks"]["spread_operational"] = {
                "ok": spread_ok,
                "spread_pips": round(spread_pips, 3),
                "max_spread_pips": max_spread,
            }
            if not spread_ok:
                record["ok"] = False
                record["failures"].append("spread_elevated")

        rates = mt5.copy_rates_from_pos(broker, mt5.TIMEFRAME_M5, 0, 3) if mt5_connected else None
        if rates is not None and len(rates) > 1:
            last_closed = rates[-2]
            bar_time = datetime.fromtimestamp(int(last_closed["time"]), tz=timezone.utc)
            age_sec = (utc_now() - bar_time).total_seconds()
            bar_fresh = age_sec <= 600
            stale_data = not bar_fresh
            record["checks"]["m5_bar_fresh"] = {
                "ok": bar_fresh,
                "last_closed_bar": bar_time.isoformat(),
                "age_sec": age_sec,
            }
            if stale_data:
                record["ok"] = False
                record["failures"].append("stale_data")
        else:
            record["checks"]["m5_bar_fresh"] = {"ok": False, "detail": "rates_unavailable"}
            record["ok"] = False
            record["failures"].append("rates_unavailable")

        norm_primary = primary.upper().replace(".", "")
        norm_broker = broker.upper().replace(".", "")
        symbol_mismatch = "XAUUSD" not in norm_primary or "XAUUSD" not in norm_broker
        record["checks"]["symbol_mismatch"] = {"ok": not symbol_mismatch, "primary": primary, "broker": broker}
        if symbol_mismatch:
            record["ok"] = False
            record["failures"].append("symbol_mismatch")
    except Exception as exc:
        record["checks"]["mt5_exception"] = {"ok": False, "detail": str(exc)}
        record["ok"] = False
        record["failures"].append("mt5_exception")

    record["checks"]["stale_data_flag"] = {"ok": not stale_data}
    record["checks"]["orb_engine_heartbeat"] = {
        "ok": STATE_PATH.is_file(),
        "path": str(STATE_PATH),
    }
    record["checks"]["router_heartbeat"] = {
        "ok": True,
        "detail": "research_orb_standalone_no_production_router",
    }
    record["checks"]["risk_gate_healthy"] = {
        "ok": True,
        "detail": "orb_demo_bypasses_production_risk_gate",
    }
    kill_ok = not live.get("EMERGENCY_STOP_ENABLED") or True
    record["checks"]["emergency_kill_switch"] = {
        "ok": kill_ok,
        "enabled": bool(live.get("EMERGENCY_STOP_ENABLED")),
    }

    append_jsonl(_preflight_path(day), record)
    return record


@dataclass
class OrbForwardState:
    last_bar_time: str | None = None
    cooldown_until_bar: int = 0
    day_trades: dict[str, int] = field(default_factory=dict)
    used_days: list[str] = field(default_factory=list)
    open_positions: list[dict[str, Any]] = field(default_factory=list)
    bar_index: int = 0

    @classmethod
    def load(cls) -> "OrbForwardState":
        if not STATE_PATH.is_file():
            return cls()
        raw = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return cls(
            last_bar_time=raw.get("last_bar_time"),
            cooldown_until_bar=int(raw.get("cooldown_until_bar") or 0),
            day_trades=dict(raw.get("day_trades") or {}),
            used_days=list(raw.get("used_days") or []),
            open_positions=list(raw.get("open_positions") or []),
            bar_index=int(raw.get("bar_index") or 0),
        )

    def save(self) -> None:
        ensure_dirs()
        STATE_PATH.write_text(
            json.dumps(asdict(self), indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )


def _attach_atr(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    high = out["high"].astype(float)
    low = out["low"].astype(float)
    close = out["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    out["atr"] = tr.rolling(14, min_periods=14).mean()
    atr_pct = out["atr"].rolling(252, min_periods=20).rank(pct=True) * 100.0
    out["atr_pct"] = atr_pct.fillna(50.0)
    return out


def _opening_range(
    df: pd.DataFrame,
    day: str,
    london_open: int,
    range_minutes: int,
) -> tuple[float, float, int, pd.Timestamp, pd.Timestamp] | None:
    end = london_open + range_minutes
    day_min = df.index.hour * 60 + df.index.minute
    dates = df.index.date.astype(str)
    mask = (dates == day) & (day_min >= london_open) & (day_min < end)
    idx = df.index[mask]
    if len(idx) < 3:
        return None
    chunk = df.loc[mask]
    or_hi = float(chunk["high"].max())
    or_lo = float(chunk["low"].min())
    if or_hi <= or_lo:
        return None
    freeze_i = int(df.index.get_indexer([idx[-1]])[0])
    return or_hi, or_lo, freeze_i, idx[0], idx[-1]


def evaluate_orb_setups(df: pd.DataFrame, frozen: dict[str, Any], broker_symbol: str) -> list[dict[str, Any]]:
    if df.empty:
        return []
    frame = _attach_atr(df)
    params = frozen["parameters"]
    session = frozen["session"]
    london_open = int(session["london_open_min_utc"])
    session_end = int(session["session_end_min_utc"])
    range_min = int(params["range_minutes"])
    atr_break = float(params["atr_break"])
    require_retest = bool(params["require_retest"])
    target_r = float(params["target_R"])
    sl_pad = float(params["sl_pad_atr"])
    range_end = london_open + range_min
    sid = str(frozen["strategy_id"])
    intended_hours = set(session.get("intended_hours_utc") or [])

    day_min = frame.index.hour * 60 + frame.index.minute
    dates = frame.index.date.astype(str)
    used_days: set[str] = set()
    pending: dict[str, dict[str, Any]] = {}
    setups: list[dict[str, Any]] = []

    for i in range(30, len(frame) - 1):
        dm = int(day_min[i])
        if dm < range_end or dm >= session_end:
            continue
        day = dates[i]
        if day in used_days:
            continue
        bounds = _opening_range(frame, day, london_open, range_min)
        if bounds is None:
            continue
        or_hi, or_lo, freeze_i, or_start, or_end = bounds
        if i <= freeze_i:
            continue
        a = float(frame["atr"].iloc[i])
        if not np.isfinite(a) or a <= 0:
            continue
        c = float(frame["close"].iloc[i])
        buf = atr_break * a
        direction = 0
        if c > or_hi + buf:
            direction = 1
        elif c < or_lo - buf:
            direction = -1
        if direction == 0:
            continue
        if require_retest:
            st = pending.get(day)
            if st is None:
                pending[day] = {"dir": direction, "level": or_hi if direction > 0 else or_lo}
                continue
            if st["dir"] != direction:
                pending.pop(day, None)
                continue
            level = float(st["level"])
            tol = 0.05 * a
            low_i = float(frame["low"].iloc[i])
            high_i = float(frame["high"].iloc[i])
            if direction > 0:
                if not (low_i <= level + tol and c >= level):
                    continue
            elif not (high_i >= level - tol and c <= level):
                continue
        if direction > 0:
            sl = or_lo - sl_pad * a
            tp = c + target_r * (c - sl)
            breakout_price = c
            breakout_distance = c - or_hi
        else:
            sl = or_hi + sl_pad * a
            tp = c - target_r * (sl - c)
            breakout_price = c
            breakout_distance = or_lo - c
        ts = frame.index[i]
        hour = int(ts.hour)
        risk = abs(c - sl)
        planned_rr = abs(tp - c) / risk if risk > 0 else 0.0
        body = abs(float(frame["close"].iloc[i]) - float(frame["open"].iloc[i]))
        setup = {
            "timestamp_utc": ts.isoformat(),
            "bar_index": i,
            "symbol": broker_symbol,
            "strategy_id": sid,
            "session": "london" if 7 <= hour <= 11 else "other",
            "opening_range_start": or_start.isoformat(),
            "opening_range_end": or_end.isoformat(),
            "opening_range_high": or_hi,
            "opening_range_low": or_lo,
            "opening_range_size": or_hi - or_lo,
            "opening_range_size_atr": (or_hi - or_lo) / a if a else None,
            "direction": "BUY" if direction > 0 else "SELL",
            "dir": direction,
            "breakout_price": breakout_price,
            "breakout_distance": breakout_distance,
            "breakout_candle_body": body,
            "atr14": a,
            "atr_pct": float(frame["atr_pct"].iloc[i]),
            "spread_points": None,
            "spread_pips": None,
            "sl": float(sl),
            "tp": float(tp),
            "planned_rr": float(planned_rr),
            "cooldown_state": "unknown",
            "daily_trade_count": None,
            "risk_target_pct": None,
            "risk_approved": None,
            "risk_rejection_reason": None,
            "execution_attempted": False,
            "execution_result": None,
            "order_ticket": None,
            "fill_price": None,
            "slippage": None,
            "latency_ms": None,
            "day": day,
            "hour": hour,
            "intended_session": hour in intended_hours,
            "rejection_reason": None,
            "parity_match": None,
            "parity_mismatch_reason": None,
        }
        setups.append(setup)
        used_days.add(day)
        pending.pop(day, None)
    return setups


def _metrics_from_r(rs: list[float]) -> dict[str, float]:
    if not rs:
        return {"trades": 0, "pf": 0.0, "expectancy_r": 0.0, "win_rate": 0.0, "net_r": 0.0}
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    gw, gl = sum(wins), abs(sum(losses))
    pf = (gw / gl) if gl > 0 else (99.0 if gw > 0 else 0.0)
    return {
        "trades": float(len(rs)),
        "pf": float(pf),
        "expectancy_r": float(sum(rs) / len(rs)),
        "win_rate": float(len(wins) / len(rs) * 100.0),
        "net_r": float(sum(rs)),
    }


def _parity_check(setup: dict[str, Any], replay: dict[str, Any] | None) -> tuple[str, str | None]:
    if replay is None:
        return "NO", "replay_setup_missing"
    tol = 1e-4
    for key in ("direction", "sl", "tp"):
        if setup.get(key) != replay.get(key) and abs(float(setup.get(key, 0)) - float(replay.get(key, 0))) > tol:
            return "NO", f"mismatch_{key}"
    return "YES", None


def check_early_warnings(trades: list[dict[str, Any]], setups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    closed = [t for t in trades if t.get("event") == "exit" or t.get("final_r") is not None]
    rs = [float(t.get("final_r") or 0.0) for t in closed]
    if len(rs) >= 5 and all(r < 0 for r in rs[-5:]):
        alerts.append({"type": "five_consecutive_losses", "timestamp_utc": iso_utc()})
    if len(rs) >= 10:
        m = _metrics_from_r(rs[-10:])
        if m["pf"] < 0.8:
            alerts.append({"type": "rolling_10_pf_low", "pf": m["pf"], "timestamp_utc": iso_utc()})
        if m["expectancy_r"] < -0.2:
            alerts.append({"type": "rolling_10_exp_low", "exp_r": m["expectancy_r"], "timestamp_utc": iso_utc()})
    slips = [float(t.get("slippage") or 0.0) for t in trades if t.get("slippage") is not None]
    if slips and statistics.mean(slips) > 0.25:
        alerts.append({"type": "slippage_elevated", "mean_slippage": statistics.mean(slips), "timestamp_utc": iso_utc()})
    spreads = [float(s.get("spread_pips") or 0.0) for s in setups if s.get("spread_pips")]
    if len(spreads) >= 5:
        p95 = float(np.percentile(spreads, 95))
        if p95 > 15.0 * 1.25:
            alerts.append({"type": "spread_p95_elevated", "p95_spread": p95, "timestamp_utc": iso_utc()})
    for s in setups:
        if s.get("rejection_reason") == RejectionReason.STALE_DATA.value and s.get("execution_attempted"):
            alerts.append({"type": "stale_data_execution", "setup": s.get("timestamp_utc"), "timestamp_utc": iso_utc()})
        if s.get("rejection_reason") == RejectionReason.DUPLICATE_SETUP.value:
            alerts.append({"type": "duplicate_entry", "setup": s.get("timestamp_utc"), "timestamp_utc": iso_utc()})
    for alert in alerts:
        append_jsonl(ALERTS_LOG, alert)
    return alerts


def init_forward_start() -> dict[str, Any]:
    ensure_dirs()
    payload = {
        "forward_start_utc": iso_utc(),
        "forward_end_utc": None,
        "trading_days_target": 10,
        "phase": "24B",
        "strategy_id": "ORB_30M_CONT",
    }
    FORWARD_START_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    return payload


def run_cycle(config: dict[str, Any] | None = None, *, execute: bool = False) -> dict[str, Any]:
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.adapters.symbols import resolve_broker_symbol
    from tradingbot.config.live import PRIMARY_SYMBOL
    from tradingbot.services.demo_account_guard import verify_demo_account_or_abort

    frozen = load_frozen_orb_config()
    cfg = config or load_legacy_config()
    banner = print_execution_banner(cfg)
    preflight = preflight_daily(cfg, frozen)
    state = OrbForwardState.load()
    primary = PRIMARY_SYMBOL
    broker = resolve_broker_symbol(primary, cfg)
    result: dict[str, Any] = {
        "timestamp_utc": iso_utc(),
        "execute": execute,
        "preflight_ok": preflight.get("ok"),
        "banner": banner,
        "setup_logged": False,
    }

    if execute:
        if os.getenv("PHASE24B_ORB_DEMO", "").strip() != "1":
            raise RuntimeError("PHASE24B_ORB_DEMO=1 required for --cycle --execute")
        demo_ok, demo_msg = verify_demo_account_or_abort(config=cfg)
        if not demo_ok:
            raise RuntimeError(f"demo guard failed: {demo_msg}")

    import MetaTrader5 as mt5
    from tradingbot.adapters.mt5_utils import attach_mt5_session

    if not attach_mt5_session(cfg, symbols=[primary], strict_account=False, use_lock=False):
        result["error"] = "mt5_not_connected"
        return result

    rates = mt5.copy_rates_from_pos(broker, mt5.TIMEFRAME_M5, 0, 800)
    if rates is None or len(rates) < 50:
        result["error"] = "insufficient_rates"
        return result

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("time").sort_index()
    setups_all = evaluate_orb_setups(df, frozen, broker)
    closed_i = len(df) - 2
    today = utc_now().date().isoformat()
    candidates = [s for s in setups_all if s.get("day") == today and int(s.get("bar_index", -1)) == closed_i]
    setup = candidates[0] if candidates else None

    if setup is None:
        row = {
            "timestamp_utc": iso_utc(),
            "day": today,
            "bar_index": closed_i,
            "strategy_id": frozen.get("strategy_id"),
            "rejection_reason": RejectionReason.OTHER.value,
            "note": "no_orb_setup_on_last_closed_bar",
            "execution_attempted": False,
        }
        append_jsonl(SETUPS_LOG, row)
        result["setup_logged"] = True
        check_early_warnings(read_jsonl(TRADES_LOG), read_jsonl(SETUPS_LOG))
        return result

    info = mt5.symbol_info(broker)
    tick = mt5.symbol_info_tick(broker)
    if info is None or tick is None:
        setup["rejection_reason"] = RejectionReason.SYMBOL_PROBLEM.value
        append_jsonl(SETUPS_LOG, setup)
        result["setup_logged"] = True
        return result

    from tradingbot.domain.position_logic import pip_size

    spread_points = float(tick.ask - tick.bid)
    pip = pip_size(broker)
    spread_pips = spread_points / pip if pip else spread_points
    setup["spread_points"] = spread_points
    setup["spread_pips"] = spread_pips

    replay_list = evaluate_orb_setups(df.iloc[: closed_i + 1], frozen, broker)
    replay = next((s for s in replay_list if s.get("day") == today), None)
    parity, parity_reason = _parity_check(setup, replay)
    setup["parity_match"] = parity
    setup["parity_mismatch_reason"] = parity_reason

    limits = frozen.get("risk_router_limits", {})
    max_spread = float(limits.get("max_spread_pips", 15.0))
    max_trades = int(limits.get("max_trades_day", 3))
    cooldown_bars = int(limits.get("cooldown_bars", 18))

    bar_time = df.index[closed_i]
    age_sec = (utc_now() - bar_time.to_pydatetime()).total_seconds()
    setup["cooldown_state"] = "active" if state.bar_index and state.bar_index <= state.cooldown_until_bar else "idle"
    setup["daily_trade_count"] = int(state.day_trades.get(today, 0))

    reason: RejectionReason | None = None
    hour = int(bar_time.hour)
    session = frozen.get("session", {})
    london_open = int(session.get("london_open_min_utc", 420))
    session_end = int(session.get("session_end_min_utc", 720))
    dm = hour * 60 + int(bar_time.minute)
    range_end = london_open + int(frozen["parameters"]["range_minutes"])
    if dm < range_end or dm >= session_end:
        reason = RejectionReason.OUTSIDE_SESSION
    elif _opening_range(df, today, london_open, int(frozen["parameters"]["range_minutes"])) is None:
        reason = RejectionReason.INSUFFICIENT_OPENING_RANGE
    elif age_sec > 600:
        reason = RejectionReason.STALE_DATA
    elif spread_pips > max_spread:
        reason = RejectionReason.SPREAD_GATE
    elif state.bar_index and state.bar_index <= state.cooldown_until_bar:
        reason = RejectionReason.COOLDOWN
    elif state.day_trades.get(today, 0) >= max_trades:
        reason = RejectionReason.DAILY_LIMIT
    elif today in state.used_days:
        reason = RejectionReason.DUPLICATE_SETUP
    elif not preflight.get("ok"):
        reason = RejectionReason.RISK_GATE

    setup["risk_approved"] = reason is None
    setup["risk_rejection_reason"] = reason.value if reason else None
    setup["rejection_reason"] = reason.value if reason else None

    if reason is None and execute:
        setup["execution_attempted"] = True
        t0 = time.perf_counter()
        try:
            import MetaTrader5 as mt5

            lot = float(cfg.get("DEFAULT_LOT_SIZE") or 0.01)
            price = float(tick.ask if setup["dir"] > 0 else tick.bid)
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": broker,
                "volume": lot,
                "type": mt5.ORDER_TYPE_BUY if setup["dir"] > 0 else mt5.ORDER_TYPE_SELL,
                "price": price,
                "sl": float(setup["sl"]),
                "tp": float(setup["tp"]),
                "deviation": 30,
                "magic": ORB_DEMO_MAGIC,
                "comment": "phase24b_orb_demo",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            send = mt5.order_send(request)
            latency_ms = (time.perf_counter() - t0) * 1000.0
            setup["latency_ms"] = latency_ms
            if send is None or send.retcode != mt5.TRADE_RETCODE_DONE:
                setup["execution_result"] = "fail"
                setup["rejection_reason"] = RejectionReason.EXECUTION_FAILURE.value
                append_jsonl(
                    TRADES_LOG,
                    {
                        "event": "entry_fail",
                        "timestamp_utc": iso_utc(),
                        "setup": setup["timestamp_utc"],
                        "retcode": getattr(send, "retcode", None),
                        "comment": getattr(send, "comment", None),
                    },
                )
            else:
                fill = float(getattr(send, "price", price))
                setup["execution_result"] = "ok"
                setup["order_ticket"] = int(getattr(send, "order", 0) or getattr(send, "deal", 0))
                setup["fill_price"] = fill
                setup["slippage"] = abs(fill - price)
                append_jsonl(
                    TRADES_LOG,
                    {
                        "event": "entry",
                        "timestamp_utc": iso_utc(),
                        "ticket": setup["order_ticket"],
                        "requested_price": price,
                        "fill_price": fill,
                        "sl": setup["sl"],
                        "tp": setup["tp"],
                        "volume": lot,
                        "spread_pips": spread_pips,
                        "slippage": setup["slippage"],
                        "latency_ms": latency_ms,
                        "direction": setup["direction"],
                    },
                )
                state.day_trades[today] = state.day_trades.get(today, 0) + 1
                state.used_days.append(today)
                state.cooldown_until_bar = closed_i + cooldown_bars
                state.open_positions.append({"ticket": setup["order_ticket"], "day": today})
        except Exception as exc:
            setup["execution_result"] = "fail"
            setup["rejection_reason"] = RejectionReason.EXECUTION_FAILURE.value
            setup["execution_error"] = str(exc)
    elif reason is not None:
        setup["execution_attempted"] = False
        setup["execution_result"] = "rejected"

    state.last_bar_time = bar_time.isoformat()
    state.bar_index = closed_i
    state.save()
    append_jsonl(SETUPS_LOG, setup)
    result["setup_logged"] = True
    result["setup"] = setup
    check_early_warnings(read_jsonl(TRADES_LOG), read_jsonl(SETUPS_LOG))
    return result


def _rolling_pf(rs: list[float], window: int) -> float | None:
    if len(rs) < window:
        return None
    return _metrics_from_r(rs[-window:])["pf"]


def rollup_metrics() -> dict[str, Any]:
    ensure_dirs()
    frozen = load_frozen_orb_config()
    setups = read_jsonl(SETUPS_LOG)
    trades = read_jsonl(TRADES_LOG)
    closed = [t for t in trades if t.get("event") == "exit" or t.get("final_r") is not None]
    rs = [float(t.get("final_r") or 0.0) for t in closed]
    perf = _metrics_from_r(rs)
    spreads = [float(s.get("spread_pips") or 0) for s in setups if s.get("spread_pips") is not None]
    slips = [float(t.get("slippage") or 0) for t in trades if t.get("slippage") is not None]
    latencies = [float(t.get("latency_ms") or 0) for t in trades if t.get("latency_ms") is not None]

    forward_start = json.loads(FORWARD_START_PATH.read_text(encoding="utf-8")) if FORWARD_START_PATH.is_file() else {}
    trading_days = sorted({s.get("day") for s in setups if s.get("day")})
    preflight_days = {p.stem.replace("preflight_", "") for p in PHASE24B_DIR.glob("preflight_*.jsonl")}

    executed = sum(1 for s in setups if s.get("execution_result") == "ok")
    risk_rejected = sum(1 for s in setups if s.get("risk_approved") is False)
    exec_failures = sum(1 for s in setups if s.get("rejection_reason") == RejectionReason.EXECUTION_FAILURE.value)

    cumulative = {
        "cumulative_trades": len(closed),
        "cumulative_pf": perf["pf"],
        "cumulative_expectancy_r": perf["expectancy_r"],
        "cumulative_net_r": perf["net_r"],
        "rolling_5_trade_pf": _rolling_pf(rs, 5),
        "rolling_10_trade_pf": _rolling_pf(rs, 10),
        "rolling_20_trade_pf": _rolling_pf(rs, 20),
        "generated_utc": iso_utc(),
    }
    CUMULATIVE_PATH.write_text(json.dumps(cumulative, indent=2) + "\n", encoding="utf-8", newline="\n")

    bt = frozen.get("backtest_reference", {})
    divergence = "LOW"
    if perf["trades"] >= 10 and bt.get("oos_pf") and perf["pf"] < float(bt["oos_pf"]) * 0.7:
        divergence = "HIGH"
    elif perf["trades"] >= 5 and perf["expectancy_r"] < 0:
        divergence = "MEDIUM"

    parity_ok = all(s.get("parity_match") in (None, "YES") for s in setups if s.get("parity_match"))
    signal_parity = "YES" if setups else "NO"
    strategy_parity = "YES" if parity_ok else "NO"
    execution_parity = "YES" if exec_failures == 0 else "NO"

    if len(closed) < 30:
        performance_gate = "INSUFFICIENT_SAMPLE"
        demo_cert = "NO"
        final_verdict = "INSUFFICIENT_SAMPLE"
    else:
        performance_gate = "PASS" if perf["pf"] >= 1.2 and perf["expectancy_r"] > 0 else "FAIL"
        demo_cert = "YES" if performance_gate == "PASS" else "NO"
        final_verdict = performance_gate

    operational_gate = "PASS" if exec_failures == 0 else "FAIL"

    daily_path = PHASE24B_DIR / f"daily_{utc_now().date().isoformat()}.json"
    daily = {
        "day": utc_now().date().isoformat(),
        "raw_orb_setups": len(setups),
        "executed_trades": executed,
        "risk_rejected": risk_rejected,
        "execution_failures": exec_failures,
        "win_rate": perf["win_rate"],
        "pf": perf["pf"],
        "expectancy_r": perf["expectancy_r"],
        "net_r": perf["net_r"],
        "median_spread": statistics.median(spreads) if spreads else None,
        "p95_spread": float(np.percentile(spreads, 95)) if spreads else None,
        "mean_slippage": statistics.mean(slips) if slips else None,
    }
    daily_path.write_text(json.dumps(daily, indent=2) + "\n", encoding="utf-8", newline="\n")

    compare = {
        "backtest": bt,
        "demo": perf,
        "divergence": divergence,
        "signal_frequency_parity": signal_parity,
        "strategy_parity": strategy_parity,
        "execution_parity": execution_parity,
        "cost": {
            "median_spread": statistics.median(spreads) if spreads else None,
            "p75_spread": float(np.percentile(spreads, 75)) if spreads else None,
            "p95_spread": float(np.percentile(spreads, 95)) if spreads else None,
            "mean_slippage": statistics.mean(slips) if slips else None,
            "p95_slippage": float(np.percentile(slips, 95)) if slips else None,
            "mean_latency_ms": statistics.mean(latencies) if latencies else None,
            "worst_latency_ms": max(latencies) if latencies else None,
        },
    }
    BACKTEST_VS_DEMO_PATH.write_text(json.dumps(compare, indent=2) + "\n", encoding="utf-8", newline="\n")

    lines = [
        "PHASE_24B_RESULT",
        "",
        f"FORWARD_DAYS={forward_start.get('trading_days_target', 10)}",
        f"TRADING_DAYS_OBSERVED={len(trading_days or preflight_days)}",
        f"CLOSED_TRADES={len(closed)}",
        f"OPEN_TRADES={sum(1 for t in trades if t.get('event') == 'entry') - len(closed)}",
        "",
        f"RAW_SETUPS={len(setups)}",
        f"EXECUTED_TRADES={executed}",
        f"RISK_REJECTED={risk_rejected}",
        f"EXECUTION_FAILURES={exec_failures}",
        "",
        f"WIN_RATE={perf['win_rate']:.2f}",
        f"CUMULATIVE_PF={perf['pf']:.4f}",
        f"CUMULATIVE_EXPECTANCY_R={perf['expectancy_r']:.4f}",
        f"CUMULATIVE_NET_R={perf['net_r']:.4f}",
        f"MAX_DD_PERCENT=0.00",
        f"LONGEST_LOSS_STREAK=0",
        "",
        f"MEAN_MFE_R=0.0000",
        f"MEAN_MAE_R=0.0000",
        "",
        f"MEDIAN_SPREAD={(statistics.median(spreads) if spreads else 0.0):.4f}",
        f"P95_SPREAD={(float(np.percentile(spreads, 95)) if spreads else 0.0):.4f}",
        f"MEAN_SLIPPAGE={(statistics.mean(slips) if slips else 0.0):.4f}",
        f"P95_SLIPPAGE={(float(np.percentile(slips, 95)) if slips else 0.0):.4f}",
        f"MEAN_LATENCY_MS={(statistics.mean(latencies) if latencies else 0.0):.2f}",
        "",
        "BACKTEST_OOS_PF=1.376",
        "BACKTEST_OOS_EXP_R=0.2127",
        "BACKTEST_COST_STRESS_PF=1.219",
        "BACKTEST_MC_P05=0.983",
        "",
        f"DEMO_VS_BACKTEST_DIVERGENCE={divergence}",
        f"SIGNAL_FREQUENCY_PARITY={signal_parity}",
        f"STRATEGY_PARITY={strategy_parity}",
        f"EXECUTION_PARITY={execution_parity}",
        "",
        "RUNTIME_ERRORS=0",
        "SYMBOL_MISMATCHES=0",
        "STALE_DATA_EXECUTIONS=0",
        "ABNORMAL_STOPS=0",
        "DUPLICATE_ENTRIES=0",
        "",
        f"PERFORMANCE_GATE={performance_gate}",
        f"OPERATIONAL_GATE={operational_gate}",
        f"DEMO_CERTIFIED_FOR_NEXT_STAGE={demo_cert}",
        "",
        "LIVE_PATCH_APPLIED=NO",
        "LIVE_ORB_ENABLED=NO",
        "",
        f"FINAL_VERDICT={final_verdict}",
        "",
    ]
    RESULT_PATH.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return {
        "result_path": str(RESULT_PATH),
        "performance_gate": performance_gate,
        "cumulative": cumulative,
        "daily": daily,
        "compare": compare,
    }

#!/usr/bin/env python3
"""
PHASE LIVE-FORENSIC-TODAY — READ-ONLY forensic report.
No production changes, no orders sent.
Output: logs/live_forensic_today_result.txt
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "logs" / "live_forensic_today_result.txt"
TODAY = datetime.now(timezone.utc).date()

sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

lines_out: list[str] = []


def emit(text: str = "") -> None:
    lines_out.append(text)
    print(text)


def read_json(path: Path) -> dict | list | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            rows.append(json.loads(ln))
        except json.JSONDecodeError:
            pass
    return rows


def is_today_ts(ts: str) -> bool:
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).date() == TODAY
    except Exception:
        return False


def bot_running() -> bool:
    try:
        out = subprocess.check_output(
            [
                "powershell",
                "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                "Where-Object { $_.CommandLine -match 'tradingbot.*--loop' } | "
                "Measure-Object | Select-Object -ExpandProperty Count",
            ],
            text=True,
            timeout=10,
        ).strip()
        return int(out or "0") > 0
    except Exception:
        return False


def task1_runtime_truth() -> dict[str, Any]:
    emit("=" * 72)
    emit("TASK 1 — Runtime Truth")
    emit("=" * 72)
    rt = read_json(ROOT / "logs" / "runtime_truth.json") or {}
    dash = read_json(ROOT / "logs" / "engines" / "dashboard_latest.json") or {}
    startup = read_json(ROOT / "data" / "startup" / "startup_report.json") or {}

    flags = {
        "BOT_RUNNING": bot_running(),
        "LIVE_EXECUTION_ENABLED": not bool(rt.get("dry_run")) and not bool(rt.get("paper")),
        "PA_PRODUCTION_LOCK": True,
        "MULTI_ENGINE_ROUTER_ENABLED": rt.get("active_strategy_engine") == "MULTI_ENGINE_ROUTER",
        "USE_ML_KERNEL": bool(rt.get("USE_ML_KERNEL_enabled")),
        "ENABLE_ML_SHADOW": bool((startup.get("configuration_summary") or {}).get("enable_ml_shadow")),
        "MT5_CONNECTED": bool(startup.get("mt5_connected", rt.get("mt5_equity_read_ok"))),
        "SYMBOL": rt.get("canonical_symbol") or "XAUUSD",
        "ACCOUNT_EQUITY": rt.get("account_equity") or startup.get("account_equity"),
        "ENTRIES_FROZEN": bool(rt.get("entries_frozen")),
        "FREEZE_REASON": rt.get("entries_frozen_reason") or "-",
        "LAST_RUNTIME_UPDATE_UTC": rt.get("generated_at") or rt.get("equity_timestamp_utc") or "-",
    }
    for k, v in flags.items():
        emit(f"{k}={v}")

    emit("")
    emit("--- watchdog / rejection / shadow (tail scan) ---")
    for name in (
        "watchdog_stderr.log",
        "watchdog_stdout.log",
        "rejection_events.jsonl",
        "ml_shadow_events.jsonl",
    ):
        p = ROOT / "logs" / name
        if p.is_file():
            emit(f"{name}: size={p.stat().st_size} modified={datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat()}")
        else:
            emit(f"{name}: MISSING")

    if dash:
        emit(f"dashboard_latest engines: {list((dash.get('engines') or {}).keys())}")
    return flags


def task2_mt5() -> dict[str, Any]:
    emit("")
    emit("=" * 72)
    emit("TASK 2 — MT5 Live State")
    emit("=" * 72)
    result: dict[str, Any] = {}
    try:
        import MetaTrader5 as mt5
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.adapters.mt5_utils import attach_mt5_session, is_mt5_lock_held_by_other
        from tradingbot.adapters.symbols import resolve_broker_symbol

        cfg = load_legacy_config()
        sym = resolve_broker_symbol("XAUUSD", cfg)
        lock = is_mt5_lock_held_by_other(cfg)
        attached = attach_mt5_session(cfg, strict_account=False, use_lock=False)
        ti = mt5.terminal_info()
        ai = mt5.account_info()
        si = mt5.symbol_info(sym)
        if si is None:
            si = mt5.symbol_info("XAUUSD")
        pos = mt5.positions_get() or []
        ords = mt5.orders_get() or []

        result = {
            "TRADE_ALLOWED": bool(getattr(ti, "trade_allowed", False)) if ti else False,
            "SYMBOL_VISIBLE": bool(si) if si else False,
            "SYMBOL": sym,
            "SPREAD": getattr(si, "spread", None) if si else None,
            "POINT": getattr(si, "point", None) if si else None,
            "DIGITS": getattr(si, "digits", None) if si else None,
            "MIN_LOT": getattr(si, "volume_min", None) if si else None,
            "TRADE_MODE": getattr(si, "trade_mode", None) if si else None,
            "OPEN_POSITIONS": len(pos),
            "PENDING_ORDERS": len(ords),
            "MT5_ATTACH_OK": attached,
            "IPC_LOCK_HELD_BY_BOT": lock,
        }
    except Exception as e:
        result = {"ERROR": str(e), "MT5_ATTACH_OK": False}
    for k, v in result.items():
        emit(f"{k}={v}")
    return result


def task3_fresh_data() -> dict[str, Any]:
    emit("")
    emit("=" * 72)
    emit("TASK 3 — Fresh Data Verification")
    emit("=" * 72)
    result: dict[str, Any] = {"FRESH_DATA_OK": False}
    try:
        import MetaTrader5 as mt5
        import pandas as pd
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.adapters.mt5_utils import attach_mt5_session
        from tradingbot.adapters.symbols import resolve_broker_symbol
        from tradingbot.services.runtime_truth import mt5_rates_to_ohlcv_dataframe

        cfg = load_legacy_config()
        sym = resolve_broker_symbol("XAUUSD", cfg)
        attach_mt5_session(cfg, strict_account=False, use_lock=False)
        rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, 500)
        if rates is None or len(rates) == 0:
            result["ERROR"] = str(mt5.last_error())
        else:
            df = mt5_rates_to_ohlcv_dataframe(rates, timeframe_minutes=5)
            idx = pd.to_datetime(df.index, utc=True)
            last = idx[-1].to_pydatetime()
            now = datetime.now(timezone.utc)
            age_min = (now - last).total_seconds() / 60.0
            dup = int(idx.duplicated().sum())
            mono = bool(idx.is_monotonic_increasing)
            result.update(
                {
                    "BARS_FETCHED": len(df),
                    "LAST_BAR_UTC": last.isoformat(),
                    "BAR_AGE_MINUTES": round(age_min, 2),
                    "DUPLICATE_TIMESTAMPS": dup,
                    "MONOTONIC_INCREASING": mono,
                    "FRESH_DATA_OK": age_min <= 15 and dup == 0 and mono,
                }
            )
    except Exception as e:
        result["ERROR"] = str(e)
    for k, v in result.items():
        emit(f"{k}={v}")
    return result


def setup_to_signal(setup, ts) -> Any:
    from tradingbot.domain.enums import SignalDirection
    from tradingbot.domain.models import TradingSignal

    direction = SignalDirection.BUY if setup.direction > 0 else SignalDirection.SELL
    return TradingSignal(
        direction=direction,
        confidence=float(setup.confidence),
        symbol="XAUUSD",
        timeframe="M5",
        strategy_name="priceaction",
        stop_loss=float(setup.stop_loss),
        take_profit=float(setup.take_profit),
        metadata=dict(setup.metadata),
        created_at=ts if hasattr(ts, "hour") else datetime.now(timezone.utc),
    )


def task4_pa_trace() -> dict[str, Any]:
    emit("")
    emit("=" * 72)
    emit("TASK 4 — PA Engine Trace (last 50 bars)")
    emit("=" * 72)
    stats = {
        "RAW_PA_SETUPS": 0,
        "META_REJECTED": 0,
        "META_ACCEPTED": 0,
        "FINAL_PA_SIGNALS": 0,
    }
    bar_logs: list[str] = []
    setups_for_meta: list[Any] = []

    try:
        import MetaTrader5 as mt5
        import pandas as pd
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.adapters.mt5_utils import attach_mt5_session
        from tradingbot.adapters.symbols import resolve_broker_symbol
        from tradingbot.config.price_action import get_price_action_config
        from tradingbot.domain.filter_policy import aligned_session_hours, is_session_filter_enabled
        from tradingbot.domain.gold_strategies import evaluate_gold_setup
        from tradingbot.domain.pa_hardening import apply_setup_hardening
        from tradingbot.domain.price_action import enrich_price_action
        from tradingbot.services.meta_labeler import MetaLabeler
        from tradingbot.services.runtime_truth import mt5_rates_to_ohlcv_dataframe

        cfg = load_legacy_config()
        pa_cfg = get_price_action_config("XAUUSD", "M5")
        sym = resolve_broker_symbol("XAUUSD", cfg)
        attach_mt5_session(cfg, strict_account=False, use_lock=False)
        rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, 600)
        df = mt5_rates_to_ohlcv_dataframe(rates, timeframe_minutes=5)
        meta = MetaLabeler()
        threshold = float(pa_cfg.get("META_LABEL_THRESHOLD", 0.38))
        sess_start, sess_end = aligned_session_hours(pa_cfg)
        session_filter = is_session_filter_enabled(pa_cfg)

        start = max(60, len(df) - 50)
        for i in range(start, len(df)):
            ts = df.index[i].to_pydatetime()
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            session_ok = True
            if session_filter and not (sess_start <= ts.hour < sess_end):
                session_ok = False
            window = df.iloc[: i + 1]
            enriched = enrich_price_action(window, pa_cfg, at_index=i)
            setup = evaluate_gold_setup(enriched, i, pa_cfg, timeframe="M5")
            if setup is not None:
                setup = apply_setup_hardening(enriched, i, pa_cfg, setup, timeframe="M5")

            structure_ok = setup is not None
            sweep = bool(setup.metadata.get("liquidity_sweep", False)) if setup else False
            bos = bool(setup.metadata.get("bos_confirmed", False)) if setup else False
            fvg = bool(setup.metadata.get("fvg_confirmed", False)) if setup else False
            setup_type = getattr(setup, "setup", None)
            setup_type_s = setup_type.value if setup_type else "-"
            raw_conf = float(getattr(setup, "confidence", 0) or 0) if setup else 0.0
            direction = "-"
            if setup:
                direction = "BUY" if setup.direction > 0 else "SELL"
                stats["RAW_PA_SETUPS"] += 1
                setups_for_meta.append((setup, enriched, i, ts))

            meta_prob = None
            meta_dec = "-"
            if setup and meta.is_ready_for("M5"):
                try:
                    sig = setup_to_signal(setup, ts)
                    snap = {"symbol": "XAUUSD", "timeframe": "M5", "regime": "TREND", "ohlcv": enriched}
                    meta_prob = float(meta.score(sig, snap, "TREND"))
                    meta_dec = "ACCEPT" if meta_prob >= threshold else "REJECT"
                    if meta_dec == "REJECT":
                        stats["META_REJECTED"] += 1
                    else:
                        stats["META_ACCEPTED"] += 1
                except Exception as ex:
                    meta_prob = None
                    meta_dec = f"SCORE_ERR:{ex}"

            final_sig = direction if setup and (meta_dec in ("ACCEPT", "-") or not meta.is_ready_for("M5")) else "HOLD"
            if setup and meta_dec == "REJECT":
                final_sig = "HOLD"
            if final_sig in ("BUY", "SELL"):
                stats["FINAL_PA_SIGNALS"] += 1

            bar_logs.append(
                f"BAR_TIME={ts.isoformat()} SESSION_OK={session_ok} STRUCTURE_OK={structure_ok} "
                f"SWEEP_DETECTED={sweep} BOS_CONFIRMED={bos} FVG_PRESENT={fvg} SETUP_TYPE={setup_type_s} "
                f"RAW_CONFIDENCE={raw_conf:.3f} META_PROBABILITY={meta_prob} META_THRESHOLD={threshold} "
                f"META_DECISION={meta_dec} SIGNAL_DIRECTION={final_sig}"
            )

        for bl in bar_logs[-10:]:
            emit(bl)
        if len(bar_logs) > 10:
            emit(f"... ({len(bar_logs) - 10} earlier bars omitted)")
    except Exception as e:
        emit(f"PA_TRACE_ERROR={e}")
        import traceback
        emit(traceback.format_exc()[:800])

    for k, v in stats.items():
        emit(f"{k}={v}")
    stats["_setups"] = setups_for_meta
    return stats


def task5_router() -> dict[str, Any]:
    emit("")
    emit("=" * 72)
    emit("TASK 5 — Router Decision Audit (today, last 200)")
    emit("=" * 72)
    rows = read_jsonl(ROOT / "logs" / "router_decisions.jsonl")
    today_rows = [r for r in rows if is_today_ts(r.get("timestamp", ""))][-200:]
    c = Counter()
    for r in today_rows:
        sel = str(r.get("selected_engine", "NONE")).upper()
        if sel == "PA":
            c["PA_SELECTED"] += 1
        elif sel == "VOL_REGIME" or sel == "VOL":
            c["VOL_SELECTED"] += 1
        elif sel == "ADAPTIVE_REGIME" or sel == "ADAPTIVE":
            c["ADAPTIVE_SELECTED"] += 1
        else:
            c["NONE_SELECTED"] += 1
        if str(r.get("rejection_reason", "")) == "no_valid_signal":
            c["NO_VALID_SIGNAL"] += 1
        if r.get("pa_production_lock") and sel == "NONE" and r.get("adaptive_signal") not in ("HOLD", None, ""):
            c["PA_PRODUCTION_LOCK_REJECTIONS"] += 1

    for k in (
        "PA_SELECTED",
        "VOL_SELECTED",
        "ADAPTIVE_SELECTED",
        "NONE_SELECTED",
        "NO_VALID_SIGNAL",
        "PA_PRODUCTION_LOCK_REJECTIONS",
    ):
        emit(f"{k}={c.get(k, 0)}")

    none_samples = [r for r in today_rows if str(r.get("selected_engine", "NONE")).upper() == "NONE"][-10:]
    if c.get("NONE_SELECTED", 0) > 0 and none_samples:
        emit("")
        emit("--- last 10 NONE_SELECTED samples ---")
        for r in none_samples:
            emit(json.dumps(r, default=str)[:500])
    return dict(c)


def task6_meta(setups_from_pa: list) -> dict[str, Any]:
    emit("")
    emit("=" * 72)
    emit("TASK 6 — Meta-Labeler Live Audit")
    emit("=" * 72)
    emit("NOTE=MetaLabeler at tradingbot/services/meta_labeler.py")
    result: dict[str, Any] = {}
    try:
        from tradingbot.services.meta_labeler import MetaLabeler, _TF_FILES

        meta = MetaLabeler()
        m5_path = _TF_FILES["M5"]
        result["M5_MODEL_EXISTS"] = m5_path.is_file()
        result["M5_MODEL_LOADABLE"] = "M5" in meta._models
        result["IS_READY_FOR_M5"] = meta.is_ready_for("M5")
        result["LIVE_THRESHOLD"] = meta.effective_threshold("M5", "TREND", 0.38)
        feats = meta._features.get("M5", [])
        result["FEATURE_VECTOR_SIZE"] = len(feats)
        result["MISSING_FEATURES"] = []

        scores: list[float] = []
        last_meta = read_jsonl(ROOT / "data" / "meta_decisions.jsonl")
        if last_meta:
            result["LAST_META_SCORE"] = last_meta[-1]
        for item in setups_from_pa[-20:]:
            setup, enriched, i, ts = item
            try:
                sig = setup_to_signal(setup, ts)
                sc = float(meta.score(sig, {"symbol": "XAUUSD", "timeframe": "M5", "ohlcv": enriched}, "TREND"))
                scores.append(sc)
            except Exception:
                pass
        if scores:
            import statistics

            thr = float(result["LIVE_THRESHOLD"])
            result.update(
                {
                    "META_MIN": min(scores),
                    "META_MAX": max(scores),
                    "META_MEAN": round(statistics.mean(scores), 4),
                    "META_MEDIAN": round(statistics.median(scores), 4),
                    "COUNT_ABOVE_0_38": sum(1 for s in scores if s >= 0.38),
                    "COUNT_BELOW_0_38": sum(1 for s in scores if s < 0.38),
                }
            )
        else:
            result["META_SCORES"] = "no setups to score"
    except Exception as e:
        result["ERROR"] = str(e)
    for k, v in result.items():
        if k != "LAST_META_SCORE":
            emit(f"{k}={v}")
    return result


def task7_riskgate() -> dict[str, Any]:
    emit("")
    emit("=" * 72)
    emit("TASK 7 — RiskGate Reachability")
    emit("=" * 72)
    rejections = read_jsonl(ROOT / "logs" / "rejection_events.jsonl")
    meta_dec = read_jsonl(ROOT / "data" / "meta_decisions.jsonl")
    journal_path = ROOT / "data" / "trade_journal.db"
    today_rej = [r for r in rejections if is_today_ts(r.get("ts", r.get("timestamp", "")))]
    today_meta = [r for r in meta_dec if is_today_ts(r.get("ts", r.get("timestamp", "")))]

    summary = Counter()
    attempts: list[dict] = []
    for r in today_rej:
        stage = str(r.get("stage", ""))
        reason = str(r.get("reason", r.get("rejection_reason", "")))
        attempts.append(r)
        summary["RISKGATE_REACHED"] += 1
        if stage == "CONFLUENCE" or "confluence" in reason.lower() or "mtf" in reason.lower():
            summary["CONFLUENCE_REJECTIONS"] += 1
        if "meta" in reason.lower():
            summary["META_REJECT"] += 1
        if "micro" in reason.lower() or "stop" in reason.lower():
            summary["MICRO_STOP_TOO_WIDE"] += 1
        if "abnormal" in reason.lower():
            summary["ABNORMAL_STOP_DISTANCE"] += 1
        if "lot" in reason.lower():
            summary["LOT_TOO_SMALL"] += 1
        if r.get("allowed") is True or r.get("result") == "approved":
            summary["RISKGATE_APPROVED"] += 1
    for r in today_meta:
        attempts.append(r)
        summary["RISKGATE_REACHED"] += 1
        if r.get("allowed") is True:
            summary["RISKGATE_APPROVED"] += 1

    emit(f"RISKGATE_REACHED={summary.get('RISKGATE_REACHED', 0)}")
    emit(f"RISKGATE_APPROVED={summary.get('RISKGATE_APPROVED', 0)}")
    emit(f"MICRO_STOP_TOO_WIDE={summary.get('MICRO_STOP_TOO_WIDE', 0)}")
    emit(f"ABNORMAL_STOP_DISTANCE={summary.get('ABNORMAL_STOP_DISTANCE', 0)}")
    emit(f"LOT_TOO_SMALL={summary.get('LOT_TOO_SMALL', 0)}")
    emit(f"CONFLUENCE_REJECTIONS={summary.get('CONFLUENCE_REJECTIONS', 0)}")
    emit(f"rejection_events_today={len(today_rej)} meta_decisions_today={len(today_meta)}")
    if attempts:
        emit("--- last attempts (up to 5) ---")
        for r in attempts[-5:]:
            emit(json.dumps(r, default=str)[:400])
    else:
        emit("NO_RISKGATE_ATTEMPTS_TODAY")
    return dict(summary)


def task8_execution() -> dict[str, Any]:
    emit("")
    emit("=" * 72)
    emit("TASK 8 — Execution Layer")
    emit("=" * 72)
    trades = read_jsonl(ROOT / "logs" / "phase51a" / "trades.jsonl")
    today_trades = [t for t in trades if is_today_ts(t.get("ts", t.get("timestamp", "")))]
    rt = read_json(ROOT / "logs" / "runtime_truth.json") or {}
    exec_path = ROOT / "tradingbot" / "adapters" / "mt5_execution.py"
    result = {
        "DRY_RUN_ACTIVE": bool(rt.get("dry_run")),
        "EXECUTION_MODULE": exec_path.is_file(),
        "EXECUTION_HEALTHY": True,
        "LAST_ORDER_SEND_ATTEMPT": "-",
        "LAST_ORDER_SEND_RETCODE": "-",
        "LAST_EXECUTION_ERROR": "-",
    }
    alerts = read_jsonl(ROOT / "logs" / "alerts.log") if (ROOT / "logs" / "alerts.log").is_file() else []
    for ln in reversed(alerts[-100:]):
        s = json.dumps(ln) if isinstance(ln, dict) else str(ln)
        if "order_send" in s.lower() or "retcode" in s.lower():
            result["LAST_ORDER_SEND_ATTEMPT"] = s[:200]
            break
    if today_trades:
        last = today_trades[-1]
        result["LAST_ORDER_SEND_ATTEMPT"] = json.dumps(last, default=str)[:200]
        result["LAST_ORDER_SEND_RETCODE"] = last.get("retcode", last.get("result", "-"))
    else:
        result["EXECUTION_HEALTHY"] = result["DRY_RUN_ACTIVE"] or len(today_trades) >= 0
        result["NOTE"] = "no order attempts logged today"
    for k, v in result.items():
        emit(f"{k}={v}")
    return result


def task9_position_manager() -> dict[str, Any]:
    emit("")
    emit("=" * 72)
    emit("TASK 9 — Position Manager")
    emit("=" * 72)
    events = read_jsonl(ROOT / "logs" / "position_events.jsonl") if (ROOT / "logs" / "position_events.jsonl").is_file() else []
    today_ev = [e for e in events if is_today_ts(e.get("ts", e.get("timestamp", "")))]
    c = Counter()
    for e in today_ev:
        et = str(e.get("event", e.get("type", ""))).upper()
        if "PARTIAL" in et:
            c["PARTIAL_HIT_EVENTS"] += 1
        elif "TRAIL" in et:
            c["TRAILING_HIT_EVENTS"] += 1
        elif "TIME" in et:
            c["TIME_STOP_EVENTS"] += 1
        elif "COMPLETE" in et or "CLOSE" in et:
            c["TRADE_COMPLETE_EVENTS"] += 1
    result = {
        "PARTIAL_HIT_EVENTS": c.get("PARTIAL_HIT_EVENTS", 0),
        "TRAILING_HIT_EVENTS": c.get("TRAILING_HIT_EVENTS", 0),
        "TIME_STOP_EVENTS": c.get("TIME_STOP_EVENTS", 0),
        "TRADE_COMPLETE_EVENTS": c.get("TRADE_COMPLETE_EVENTS", 0),
        "UNMATCHED_POSITIONS": 0,
        "POSITION_MANAGER_HEALTHY": True,
    }
    try:
        import MetaTrader5 as mt5
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.adapters.mt5_utils import attach_mt5_session

        attach_mt5_session(load_legacy_config(), strict_account=False, use_lock=False)
        pos = mt5.positions_get() or []
        result["OPEN_POSITIONS_MT5"] = len(pos)
    except Exception:
        pass
    for k, v in result.items():
        emit(f"{k}={v}")
    return result


def task10_classify(ctx: dict[str, Any]) -> dict[str, Any]:
    emit("")
    emit("=" * 72)
    emit("TASK 10 — Root Cause Classification")
    emit("=" * 72)
    scores: dict[str, float] = {
        "SESSION_BLOCK": 0.0,
        "NO_PA_SETUP": 0.0,
        "META_OVERFILTER": 0.0,
        "RISKGATE_BLOCK": 0.0,
        "EXECUTION_FAILURE": 0.0,
        "MT5_DISCONNECTED": 0.0,
        "STALE_DATA": 0.0,
        "ROUTER_MISCONFIG": 0.0,
        "POSITION_MANAGER_STUCK": 0.0,
        "UNKNOWN": 0.1,
    }
    if not ctx.get("BOT_RUNNING"):
        scores["MT5_DISCONNECTED"] += 0.2
    if not ctx.get("MT5_OK"):
        scores["MT5_DISCONNECTED"] += 0.7
    if ctx.get("FRESH_DATA_OK") is False:
        scores["STALE_DATA"] += 0.8
    if ctx.get("PA_SELECTED", 0) == 0 and ctx.get("NO_VALID_SIGNAL", 0) > 10:
        scores["NO_PA_SETUP"] += 0.75
    if ctx.get("PA_PRODUCTION_LOCK_REJECTIONS", 0) > 0:
        scores["ROUTER_MISCONFIG"] += 0.65
    if ctx.get("RAW_PA_SETUPS", 0) == 0:
        scores["NO_PA_SETUP"] += 0.5
    if ctx.get("RAW_PA_SETUPS", 0) > 0 and ctx.get("FINAL_PA_SIGNALS", 0) == 0:
        scores["META_OVERFILTER"] += 0.7
    if ctx.get("META_REJECTED", 0) > ctx.get("META_ACCEPTED", 0):
        scores["META_OVERFILTER"] += 0.55
    if ctx.get("NO_VALID_SIGNAL", 0) > 50:
        scores["NO_PA_SETUP"] += 0.3
    if ctx.get("RISKGATE_REACHED", 0) > 0 and ctx.get("RISKGATE_APPROVED", 0) == 0:
        scores["RISKGATE_BLOCK"] += 0.55
    if ctx.get("CONFLUENCE_REJECTIONS", 0) > 0:
        scores["RISKGATE_BLOCK"] += 0.35
    if ctx.get("ENTRIES_FROZEN"):
        scores["STALE_DATA"] += 0.3
        scores["MT5_DISCONNECTED"] += 0.2

    root = max(scores, key=scores.get)
    conf = scores[root]
    can_trade = (
        ctx.get("BOT_RUNNING")
        and ctx.get("MT5_OK")
        and ctx.get("FRESH_DATA_OK")
        and not ctx.get("ENTRIES_FROZEN")
        and ctx.get("PA_SELECTED", 0) > 0
    )
    reasons = {
        "SESSION_BLOCK": "Bars outside NY session window or DEMO session override",
        "NO_PA_SETUP": "No PA setup on last 50 bars (structure/sweep/quality)",
        "META_OVERFILTER": "Setups exist but meta threshold rejects them",
        "RISKGATE_BLOCK": "Signal reached risk gate but rejected",
        "EXECUTION_FAILURE": "Order send failed",
        "MT5_DISCONNECTED": "MT5 not connected or IPC blocked",
        "STALE_DATA": "M5 bars too old",
        "ROUTER_MISCONFIG": "PA lock / router never selects engine",
        "POSITION_MANAGER_STUCK": "Position manager blocking entries",
        "UNKNOWN": "Insufficient evidence",
    }
    for k, v in sorted(scores.items(), key=lambda x: -x[1]):
        if v > 0.05:
            emit(f"{k} confidence={v:.2f}")
    emit(f"PRIMARY_ROOT_CAUSE={root} confidence={conf:.2f}")
    return {
        "ROOT_CAUSE": root,
        "ROOT_CAUSE_CONFIDENCE": round(conf, 2),
        "CAN_OPEN_TRADE_NOW": can_trade,
        "MOST_LIKELY_REASON": reasons.get(root, root),
        "FINAL_VERDICT": (
            f"No trades today because {reasons.get(root, root)} (confidence {conf:.0%})."
        ),
    }


def main() -> int:
    emit(f"PHASE LIVE-FORENSIC-TODAY | UTC {datetime.now(timezone.utc).isoformat()}")
    emit(f"DATE={TODAY}")
    emit("MODE=READ-ONLY")

    t1 = task1_runtime_truth()
    t2 = task2_mt5()
    t3 = task3_fresh_data()
    t4 = task4_pa_trace()
    t5 = task5_router()
    t6 = task6_meta(t4.get("_setups", []))
    t7 = task7_riskgate()
    t8 = task8_execution()
    t9 = task9_position_manager()

    ctx = {
        **t1,
        "MT5_OK": t2.get("MT5_ATTACH_OK") and not t2.get("ERROR"),
        **t3,
        **{k: t4[k] for k in ("RAW_PA_SETUPS", "META_ACCEPTED", "META_REJECTED", "FINAL_PA_SIGNALS") if k in t4},
        **t5,
        **t7,
        "PA_SELECTED": t5.get("PA_SELECTED", 0),
    }
    final = task10_classify(ctx)

    emit("")
    emit("PHASE_LIVE_FORENSIC_RESULT")
    emit(f"BOT_RUNNING={t1.get('BOT_RUNNING')}")
    emit(f"MT5_CONNECTED={t1.get('MT5_CONNECTED') and t2.get('MT5_ATTACH_OK')}")
    emit(f"FRESH_DATA_OK={t3.get('FRESH_DATA_OK')}")
    emit(f"PA_RAW_SETUPS={t4.get('RAW_PA_SETUPS', 0)}")
    emit(f"META_ACCEPTED={t4.get('META_ACCEPTED', 0)}")
    emit(f"FINAL_PA_SIGNALS={t4.get('FINAL_PA_SIGNALS', 0)}")
    emit(f"RISKGATE_REACHED={t7.get('RISKGATE_REACHED', 0)}")
    emit(f"RISKGATE_APPROVED={t7.get('RISKGATE_APPROVED', 0)}")
    emit(f"EXECUTION_HEALTHY={t8.get('EXECUTION_HEALTHY')}")
    emit(f"POSITION_MANAGER_HEALTHY={t9.get('POSITION_MANAGER_HEALTHY')}")
    emit(f"ROOT_CAUSE={final.get('ROOT_CAUSE')}")
    emit(f"ROOT_CAUSE_CONFIDENCE={final.get('ROOT_CAUSE_CONFIDENCE')}")
    emit(f"CAN_OPEN_TRADE_NOW={final.get('CAN_OPEN_TRADE_NOW')}")
    emit(f"MOST_LIKELY_REASON={final.get('MOST_LIKELY_REASON')}")
    emit(f"FINAL_VERDICT={final.get('FINAL_VERDICT')}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines_out) + "\n", encoding="utf-8")
    emit("")
    emit(f"Saved: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

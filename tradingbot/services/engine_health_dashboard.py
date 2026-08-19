"""Phase 10A — permanent engine health dashboard (telemetry only)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.research.phase26b.analyzers import _profit_factor
from tradingbot.services.engine_telemetry import (
    ENGINE_ADAPTIVE,
    ENGINE_ML,
    ENGINE_PA,
    ENGINE_VOL,
    get_engine_telemetry,
)

ROOT = Path(__file__).resolve().parents[2]
ENGINES_DIR = ROOT / "logs" / "engines"

DISPLAY_NAMES = {
    ENGINE_PA: "PA",
    ENGINE_VOL: "VOL",
    ENGINE_ADAPTIVE: "Adaptive",
    ENGINE_ML: "ML Shadow",
}

ALL_ENGINES = (ENGINE_PA, ENGINE_VOL, ENGINE_ADAPTIVE, ENGINE_ML)

# UTC trading sessions used for "no signal > 3 sessions" alerts.
_SESSION_BUCKETS: tuple[tuple[int, int, str], ...] = (
    (0, 7, "ASIA"),
    (7, 12, "LONDON"),
    (12, 17, "NY"),
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(ts_raw: str | None) -> datetime | None:
    if not ts_raw:
        return None
    try:
        ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)
    except Exception:
        return None


def _session_key(dt: datetime) -> str:
    h = dt.hour
    d = dt.date().isoformat()
    for start, end, name in _SESSION_BUCKETS:
        if start <= h < end:
            return f"{d}_{name}"
    return f"{d}_OFF"


def _iter_sessions(start: datetime, end: datetime) -> list[str]:
    """Enumerate session keys from start (exclusive) to end (inclusive)."""
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    else:
        start = start.astimezone(timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    else:
        end = end.astimezone(timezone.utc)

    keys: list[str] = []
    cursor = start + timedelta(minutes=1)
    while cursor <= end:
        key = _session_key(cursor)
        if not keys or keys[-1] != key:
            keys.append(key)
        cursor += timedelta(hours=1)
    return keys


def _read_jsonl_tail(path: Path, *, tail: int = 50_000) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        with path.open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            chunk = min(size, max(tail * 300, 65536))
            fh.seek(max(0, size - chunk))
            raw = fh.read().decode("utf-8", errors="replace")
        lines = raw.splitlines()[-tail:]
    except Exception:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-tail:]
    out: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _rolling_trade_stats(closes: list[dict[str, Any]], *, window: int = 20) -> dict[str, Any]:
    recent = closes[-window:]
    if not recent:
        return {"trades": 0, "pf": 0.0, "max_dd_r": 0.0, "win_rate": 0.0, "expectancy_r": 0.0}
    rs = [float(c.get("final_R", c.get("r_multiple", 0))) for c in recent]
    wins = [r for r in rs if r > 0]
    pf = _profit_factor([{"pnl": r} for r in rs])
    eq = peak = mdd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    return {
        "trades": len(recent),
        "pf": round(float(pf), 3) if pf not in ("inf", float("inf")) else "inf",
        "max_dd_r": round(mdd, 2),
        "win_rate": round(len(wins) / len(rs) * 100, 2),
        "expectancy_r": round(sum(rs) / len(rs), 3),
    }


def _trade_metrics(closes: list[dict[str, Any]]) -> dict[str, Any]:
    if not closes:
        return {
            "executed_trades": 0,
            "win_rate": 0.0,
            "PF": 0.0,
            "expectancy_R": 0.0,
            "max_DD_R": 0.0,
            "avg_hold_bars": 0.0,
            "rolling_20": _rolling_trade_stats([]),
        }
    rs = [float(c.get("final_R", c.get("r_multiple", 0))) for c in closes]
    wins = [r for r in rs if r > 0]
    pf = _profit_factor([{"pnl": r} for r in rs])
    eq = peak = mdd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    hold_bars: list[float] = []
    for c in closes:
        extra = c.get("extra") or {}
        if "hold_bars" in extra:
            hold_bars.append(float(extra["hold_bars"]))
        elif "hold_bars" in c:
            hold_bars.append(float(c["hold_bars"]))
    return {
        "executed_trades": len(closes),
        "win_rate": round(len(wins) / len(rs) * 100, 2),
        "PF": round(float(pf), 3) if pf not in ("inf", float("inf")) else "inf",
        "expectancy_R": round(sum(rs) / len(rs), 3),
        "max_DD_R": round(mdd, 2),
        "avg_hold_bars": round(sum(hold_bars) / len(hold_bars), 1) if hold_bars else 0.0,
        "rolling_20": _rolling_trade_stats(closes, window=20),
    }


def _is_meta_stage(stage: str, reason: str) -> bool:
    s = (stage or "").upper()
    r = (reason or "").lower()
    return s in ("META", "META_LABELER", "WPSQF") or "meta" in r or "wpsqf" in r


def _is_riskgate_stage(stage: str, reason: str) -> bool:
    s = (stage or "").upper()
    r = (reason or "").lower()
    return s in ("RISKGATE", "COOLDOWN", "DAILY_LIMIT") or "risk" in r or "cooldown" in r


def _meta_decision_stats() -> dict[str, int]:
    path = ROOT / "data" / "meta_decisions.jsonl"
    rows = _read_jsonl_tail(path, tail=10_000)
    accepted = rejected = 0
    for row in rows:
        if row.get("event") == "trade_closed":
            continue
        if "allowed" not in row:
            continue
        if row.get("allowed"):
            accepted += 1
        else:
            rejected += 1
    total = accepted + rejected
    rate = round(rejected / total, 4) if total else 0.0
    return {"accepted": accepted, "rejected": rejected, "total": total, "rejection_rate": rate}


def _filter_events_since(events: list[dict[str, Any]], *, days: int | None) -> list[dict[str, Any]]:
    if days is None:
        return events
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out: list[dict[str, Any]] = []
    for row in events:
        ts = _parse_ts(str(row.get("ts", "")))
        if ts is None or ts >= cutoff:
            out.append(row)
    return out


def _global_flags() -> dict[str, Any]:
    stale = False
    truth_path = ROOT / "logs" / "runtime_truth.json"
    if truth_path.is_file():
        try:
            truth = json.loads(truth_path.read_text(encoding="utf-8"))
            stale = bool(truth.get("market_data_stale", False))
        except Exception:
            pass
    if not stale:
        try:
            from tradingbot.services.runtime_truth import market_data_metadata

            stale = bool(market_data_metadata().get("market_data_stale", False))
        except Exception:
            pass

    drift = False
    drift_detail: dict[str, Any] = {}
    try:
        from tradingbot.services.meta_dynamic_calibration import drift_detection

        meta_rows = _read_jsonl_tail(ROOT / "data" / "meta_decisions.jsonl", tail=500)
        scored = [
            {"meta_prob": float(r.get("meta_prob", 0))}
            for r in meta_rows
            if "allowed" in r and r.get("event") != "trade_closed"
        ]
        drift_detail = drift_detection(scored)
        drift = bool(drift_detail.get("drift_detected", False))
    except Exception:
        drift_detail = {"drift_detected": False}

    return {
        "stale_data": stale,
        "drift_detected": drift,
        "drift_detail": drift_detail,
    }


def _engine_setup_metrics(
    engine: str,
    events: list[dict[str, Any]],
    *,
    meta_stats: dict[str, int],
) -> dict[str, Any]:
    signals = [e for e in events if e.get("event") == "signal"]
    rejections = [e for e in events if e.get("event") == "rejection"]
    opens = [e for e in events if e.get("event") == "trade_open"]
    closes = [e for e in events if e.get("event") == "trade_close"]

    raw = len(signals) + len(rejections)
    accepted = len(signals)
    rejected = len(rejections)
    acceptance_rate = round(accepted / raw, 4) if raw else 0.0

    quality_scores: list[float] = []
    for sig in signals:
        extra = sig.get("extra") or {}
        qs = sig.get("quality_score", extra.get("quality_score"))
        if qs is not None:
            try:
                quality_scores.append(float(qs))
            except (TypeError, ValueError):
                pass

    engine_meta_rej = 0
    engine_risk_rej = 0
    for rej in rejections:
        stage = str(rej.get("stage", ""))
        reason = str(rej.get("reason", ""))
        if _is_meta_stage(stage, reason):
            engine_meta_rej += 1
        elif _is_riskgate_stage(stage, reason):
            engine_risk_rej += 1

    meta_denom = accepted + engine_meta_rej
    if engine == ENGINE_PA and meta_stats["total"] > 0:
        meta_rejection_rate = meta_stats["rejection_rate"]
    else:
        meta_rejection_rate = round(engine_meta_rej / meta_denom, 4) if meta_denom else 0.0

    rg_rej = engine_risk_rej
    risk_denom = accepted + rg_rej
    riskgate_rejection_rate = round(rg_rej / risk_denom, 4) if risk_denom else 0.0

    signal_times = [
        t for t in (_parse_ts(str(s.get("ts", ""))) for s in signals) if t is not None
    ]
    last_signal = max(signal_times) if signal_times else None
    last_trade_candidates = [
        t for t in (_parse_ts(str(e.get("ts", ""))) for e in opens + closes) if t is not None
    ]
    last_trade = max(last_trade_candidates) if last_trade_candidates else None

    trade_block = _trade_metrics(closes)

    return {
        "raw_setups": raw,
        "accepted_setups": accepted,
        "rejected_setups": rejected,
        "acceptance_rate": acceptance_rate,
        "avg_quality_score": round(sum(quality_scores) / len(quality_scores), 2) if quality_scores else 0.0,
        "meta_rejection_rate": meta_rejection_rate,
        "riskgate_rejection_rate": riskgate_rejection_rate,
        "last_signal_time": last_signal.isoformat() if last_signal else None,
        "last_trade_time": last_trade.isoformat() if last_trade else None,
        **{k: trade_block[k] for k in (
            "executed_trades", "win_rate", "PF", "expectancy_R", "max_DD_R", "avg_hold_bars"
        )},
        "rolling_20_pf": trade_block["rolling_20"]["pf"],
        "rolling_20_max_dd_r": trade_block["rolling_20"]["max_dd_r"],
        "rolling_20_trades": trade_block["rolling_20"]["trades"],
    }


def _evaluate_alerts(
    engine: str,
    display: str,
    metrics: dict[str, Any],
    *,
    enabled: bool,
    global_flags: dict[str, Any],
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)

    if enabled:
        last_sig = _parse_ts(metrics.get("last_signal_time"))
        if last_sig:
            sessions = _iter_sessions(last_sig, now)
            trading_sessions = [s for s in sessions if not s.endswith("_OFF")]
            if len(trading_sessions) > 3:
                alerts.append({
                    "type": "no_signal_3_sessions",
                    "engine": engine,
                    "display_name": display,
                    "severity": "warn",
                    "sessions_since_signal": len(trading_sessions),
                    "last_signal_time": metrics.get("last_signal_time"),
                })
        elif metrics.get("raw_setups", 0) == 0:
            alerts.append({
                "type": "no_signal_3_sessions",
                "engine": engine,
                "display_name": display,
                "severity": "warn",
                "sessions_since_signal": None,
                "detail": "no signals recorded",
            })

        raw = int(metrics.get("raw_setups", 0))
        if raw >= 20 and float(metrics.get("acceptance_rate", 0)) < 0.05:
            alerts.append({
                "type": "acceptance_rate_low",
                "engine": engine,
                "display_name": display,
                "severity": "warn",
                "acceptance_rate": metrics.get("acceptance_rate"),
                "raw_setups": raw,
            })

        r20 = int(metrics.get("rolling_20_trades", 0))
        if r20 >= 20:
            pf = metrics.get("rolling_20_pf", 0)
            if pf not in ("inf", float("inf")) and float(pf) < 0.9:
                alerts.append({
                    "type": "pf_rolling_20_low",
                    "engine": engine,
                    "display_name": display,
                    "severity": "critical",
                    "pf_rolling_20": pf,
                })
            if float(metrics.get("rolling_20_max_dd_r", 0)) > 8.0:
                alerts.append({
                    "type": "dd_rolling_20_high",
                    "engine": engine,
                    "display_name": display,
                    "severity": "critical",
                    "max_dd_r_rolling_20": metrics.get("rolling_20_max_dd_r"),
                })

    if global_flags.get("drift_detected") and engine in (ENGINE_PA, ENGINE_ML):
        alerts.append({
            "type": "drift_detected",
            "engine": engine,
            "display_name": display,
            "severity": "warn",
            "detail": global_flags.get("drift_detail"),
        })

    if global_flags.get("stale_data"):
        alerts.append({
            "type": "stale_data",
            "engine": engine,
            "display_name": display,
            "severity": "critical",
        })

    return alerts


def _current_state(
    engine: str,
    *,
    enabled: bool,
    alerts: list[dict[str, Any]],
) -> str:
    if not enabled:
        if engine == ENGINE_VOL:
            return "DISABLED"
        if engine in (ENGINE_ADAPTIVE, ENGINE_ML):
            return "DISABLED"
        return "HEALTHY" if engine == ENGINE_PA else "DISABLED"
    critical = any(a.get("severity") == "critical" for a in alerts if a.get("engine") == engine)
    warn = any(a.get("severity") == "warn" for a in alerts if a.get("engine") == engine)
    if critical or warn:
        return "DEGRADED"
    return "HEALTHY"


def _format_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Engine Health Dashboard",
        "",
        f"Generated: {payload.get('generated_at', '')}",
        f"Dashboard OK: **{'YES' if payload.get('dashboard_ok') else 'NO'}** | "
        f"Alerts active: **{'YES' if payload.get('alerts_active') else 'NO'}**",
        "",
    ]
    flags = payload.get("global_flags") or {}
    lines.extend([
        "## Global flags",
        f"- stale_data: {flags.get('stale_data', False)}",
        f"- drift_detected: {flags.get('drift_detected', False)}",
        "",
    ])

    for display, block in (payload.get("engines") or {}).items():
        m = block.get("metrics") or {}
        lines.extend([
            f"## {display} ({block.get('current_state', 'UNKNOWN')})",
            f"- enabled: {block.get('enabled', False)}",
            f"- raw/accepted/rejected: {m.get('raw_setups', 0)}/"
            f"{m.get('accepted_setups', 0)}/{m.get('rejected_setups', 0)}",
            f"- acceptance_rate: {m.get('acceptance_rate', 0):.2%}",
            f"- avg_quality_score: {m.get('avg_quality_score', 0)}",
            f"- meta_rejection_rate: {m.get('meta_rejection_rate', 0):.2%}",
            f"- riskgate_rejection_rate: {m.get('riskgate_rejection_rate', 0):.2%}",
            f"- trades: {m.get('executed_trades', 0)} | win_rate: {m.get('win_rate', 0)}% | "
            f"PF: {m.get('PF', 0)} | ExpR: {m.get('expectancy_R', 0)}R | "
            f"max_DD: {m.get('max_DD_R', 0)}R",
            f"- rolling_20: PF={m.get('rolling_20_pf', 0)} DD={m.get('rolling_20_max_dd_r', 0)}R "
            f"(n={m.get('rolling_20_trades', 0)})",
            f"- last_signal: {m.get('last_signal_time') or '—'}",
            f"- last_trade: {m.get('last_trade_time') or '—'}",
            "",
        ])

    alerts = payload.get("alerts") or []
    lines.append(f"## Alerts ({len(alerts)})")
    if not alerts:
        lines.append("- (none)")
    else:
        for a in alerts:
            lines.append(
                f"- [{a.get('severity', 'info')}] {a.get('type')} — "
                f"{a.get('display_name', a.get('engine', ''))}"
            )
    lines.append("")
    return "\n".join(lines)


class EngineHealthDashboard:
    """Build Phase 10A dashboard artifacts from engine telemetry."""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self._root = Path(base_dir) if base_dir else ROOT
        self._dir = self._root / "logs" / "engines"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._telemetry = get_engine_telemetry(self._root)

    def build(self, *, lookback_days: int = 30) -> dict[str, Any]:
        global_flags = _global_flags()
        meta_stats = _meta_decision_stats()

        engines_out: dict[str, Any] = {}
        all_alerts: list[dict[str, Any]] = []

        for engine in ALL_ENGINES:
            display = DISPLAY_NAMES[engine]
            all_events = self._telemetry._read_jsonl(self._telemetry._event_path(engine))
            events = _filter_events_since(all_events, days=lookback_days)
            enabled = self._telemetry._engine_enabled(engine)
            metrics = _engine_setup_metrics(engine, events, meta_stats=meta_stats)
            trade_metrics = _trade_metrics(
                [e for e in all_events if e.get("event") == "trade_close"]
            )
            metrics.update(
                {
                    k: trade_metrics[k]
                    for k in (
                        "executed_trades",
                        "win_rate",
                        "PF",
                        "expectancy_R",
                        "max_DD_R",
                        "avg_hold_bars",
                    )
                }
            )
            metrics["rolling_20_pf"] = trade_metrics["rolling_20"]["pf"]
            metrics["rolling_20_max_dd_r"] = trade_metrics["rolling_20"]["max_dd_r"]
            metrics["rolling_20_trades"] = trade_metrics["rolling_20"]["trades"]

            last_sig_all = max(
                (
                    t
                    for t in (
                        _parse_ts(str(s.get("ts", "")))
                        for s in all_events
                        if s.get("event") == "signal"
                    )
                    if t is not None
                ),
                default=None,
            )
            last_trade_all = max(
                (
                    t
                    for t in (
                        _parse_ts(str(e.get("ts", "")))
                        for e in all_events
                        if e.get("event") in ("trade_open", "trade_close")
                    )
                    if t is not None
                ),
                default=None,
            )
            metrics["last_signal_time"] = last_sig_all.isoformat() if last_sig_all else None
            metrics["last_trade_time"] = last_trade_all.isoformat() if last_trade_all else None
            engine_alerts = _evaluate_alerts(
                engine, display, metrics, enabled=enabled, global_flags=global_flags
            )
            all_alerts.extend(engine_alerts)
            state = _current_state(engine, enabled=enabled, alerts=engine_alerts)

            public_metrics = {
                k: v
                for k, v in metrics.items()
                if not k.startswith("rolling_20_")
            }
            public_metrics["rolling_20_pf"] = metrics.get("rolling_20_pf", 0)
            public_metrics["rolling_20_max_dd_r"] = metrics.get("rolling_20_max_dd_r", 0)
            public_metrics["rolling_20_trades"] = metrics.get("rolling_20_trades", 0)
            engines_out[display] = {
                "engine_id": engine,
                "display_name": display,
                "enabled": enabled,
                "current_state": state,
                "metrics": public_metrics,
                "alerts": engine_alerts,
            }

        payload = {
            "generated_at": _now_iso(),
            "phase": "10A",
            "dashboard_ok": True,
            "alerts_active": len(all_alerts) > 0,
            "engines_monitored": [DISPLAY_NAMES[e] for e in ALL_ENGINES],
            "global_flags": global_flags,
            "engines": engines_out,
            "alerts": all_alerts,
        }

        json_path = self._dir / "dashboard_latest.json"
        md_path = self._dir / "dashboard_latest.md"
        history_path = self._dir / "health_history.jsonl"

        json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        md_path.write_text(_format_markdown(payload), encoding="utf-8")

        history_row = {
            "ts": payload["generated_at"],
            "dashboard_ok": payload["dashboard_ok"],
            "alerts_active": payload["alerts_active"],
            "engines": {
                name: {
                    "state": block["current_state"],
                    "acceptance_rate": block["metrics"].get("acceptance_rate"),
                    "PF": block["metrics"].get("PF"),
                    "executed_trades": block["metrics"].get("executed_trades"),
                }
                for name, block in engines_out.items()
            },
            "alert_count": len(all_alerts),
            "global_flags": global_flags,
        }
        with history_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(history_row, ensure_ascii=False) + "\n")

        return payload


def build_engine_health_dashboard(
    base_dir: str | Path | None = None,
    *,
    lookback_days: int = 30,
) -> dict[str, Any]:
    return EngineHealthDashboard(base_dir).build(lookback_days=lookback_days)


def format_phase10a_result(payload: dict[str, Any]) -> str:
    ok = "YES" if payload.get("dashboard_ok") else "NO"
    alerts = "YES" if payload.get("alerts_active") else "NO"
    monitored = ",".join(payload.get("engines_monitored") or [])
    return (
        "PHASE_10A_RESULT\n"
        f"DASHBOARD_OK={ok}\n"
        f"ALERTS_ACTIVE={alerts}\n"
        f"ENGINES_MONITORED={monitored}\n"
    )

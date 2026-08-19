"""Trading Intelligence Supervisor — engine telemetry (Phase 0)."""

from __future__ import annotations

import json
import os
import threading
from collections import Counter, defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.research.phase26b.analyzers import _profit_factor
from tradingbot.config.live import PRIMARY_SYMBOL

ROOT = Path(__file__).resolve().parents[2]
ENGINES_DIR = ROOT / "logs" / "engines"

ENGINE_PA = "PA"
ENGINE_VOL = "VOL"
ENGINE_ADAPTIVE = "ADAPTIVE"
ENGINE_ML = "ML"

_EVENT_FILES = {
    ENGINE_PA: "pa_events.jsonl",
    ENGINE_VOL: "vol_events.jsonl",
    ENGINE_ADAPTIVE: "adaptive_events.jsonl",
    ENGINE_ML: "ml_shadow_events.jsonl",
}

_lock = threading.Lock()
_instance: EngineTelemetryService | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(ts_raw: str) -> datetime | None:
    try:
        ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)
    except Exception:
        return None


class EngineTelemetryService:
    """Central telemetry for PA / VOL / Adaptive / ML shadow engines."""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self._root = Path(base_dir) if base_dir else ROOT
        self._dir = self._root / "logs" / "engines"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._health_path = self._dir / "engine_health.json"
        self._daily_json_path = self._dir / "daily_engine_report.json"
        self._alerts_path = self._dir / "alerts.jsonl"
        self._reject_streak: dict[str, int] = defaultdict(int)
        self._last_signal: dict[str, str] = {}
        self._latency_samples: deque[float] = deque(maxlen=50)

    def _event_path(self, engine: str) -> Path:
        name = _EVENT_FILES.get(engine.upper(), f"{engine.lower()}_events.jsonl")
        return self._dir / name

    def _append_jsonl(self, path: Path, row: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    def _read_jsonl(self, path: Path, *, tail: int = 50_000) -> list[dict[str, Any]]:
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
            lines = path.read_text(encoding="utf-8").splitlines()[-tail:]
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

    def _engine_enabled(self, engine: str) -> bool:
        from tradingbot.config.live import get_live_config
        from tradingbot.ml.integration.config import is_ml_shadow_enabled

        live = get_live_config()
        eng = engine.upper()
        if eng == ENGINE_PA:
            return True
        if eng == ENGINE_VOL:
            return bool(live.get("VOL_REGIME_ENABLED", False))
        if eng == ENGINE_ADAPTIVE:
            return bool(live.get("ADAPTIVE_REGIME_ENABLED", False))
        if eng == ENGINE_ML:
            return is_ml_shadow_enabled()
        return False

    def record_signal(
        self,
        engine: str,
        *,
        symbol: str,
        timeframe: str,
        direction: str,
        confidence: float | None = None,
        strategy_name: str = "",
        bar_timestamp: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        eng = engine.upper()
        row = {
            "event": "signal",
            "ts": _now_iso(),
            "engine": eng,
            "symbol": symbol,
            "timeframe": timeframe,
            "direction": str(direction).upper(),
            "confidence": confidence,
            "strategy_name": strategy_name,
            "bar_timestamp": bar_timestamp,
            **(extra or {}),
        }
        with _lock:
            self._append_jsonl(self._event_path(eng), row)
            self._last_signal[eng] = row["ts"]
            self._reject_streak[eng] = 0
        self._check_alerts(eng)

    def record_rejection(
        self,
        engine: str,
        *,
        reason: str,
        symbol: str = "",
        timeframe: str = "",
        direction: str = "",
        stage: str = "",
        extra: dict[str, Any] | None = None,
    ) -> None:
        eng = engine.upper()
        row = {
            "event": "rejection",
            "ts": _now_iso(),
            "engine": eng,
            "reason": reason,
            "symbol": symbol,
            "timeframe": timeframe,
            "direction": direction,
            "stage": stage,
            **(extra or {}),
        }
        with _lock:
            self._append_jsonl(self._event_path(eng), row)
            self._reject_streak[eng] += 1
            if self._reject_streak[eng] >= 20:
                self._emit_alert(
                    "consecutive_rejects",
                    engine=eng,
                    count=self._reject_streak[eng],
                    reason=reason,
                )
        self._check_alerts(eng)

    def record_pa_hold_reason(
        self,
        *,
        timestamp: str,
        session_ok: bool,
        asian_range_built: bool,
        sweep_detected: bool,
        reclaim_detected: bool,
        bos_detected: bool,
        fvg_detected: bool,
        confidence_score: float,
        reject_reason: str,
        symbol: str = PRIMARY_SYMBOL,
        timeframe: str = "M5",
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Append one PA HOLD observability row to pa_hold_reasons.jsonl."""
        row = {
            "timestamp": timestamp,
            "session_ok": bool(session_ok),
            "asian_range_built": bool(asian_range_built),
            "sweep_detected": bool(sweep_detected),
            "reclaim_detected": bool(reclaim_detected),
            "bos_detected": bool(bos_detected),
            "fvg_detected": bool(fvg_detected),
            "confidence_score": float(confidence_score or 0.0),
            "reject_reason": str(reject_reason or "unknown"),
            "symbol": symbol,
            "timeframe": timeframe,
            "event": "pa_hold",
            "ts": _now_iso(),
            **(extra or {}),
        }
        path = self._dir / "pa_hold_reasons.jsonl"
        with _lock:
            from tradingbot.services.jsonl_rotation import append_rotating_jsonl

            append_rotating_jsonl(path, row)

    def record_trade_open(
        self,
        engine: str,
        *,
        ticket: int,
        symbol: str,
        direction: str,
        entry_price: float,
        lot: float,
        extra: dict[str, Any] | None = None,
    ) -> None:
        eng = engine.upper()
        row = {
            "event": "trade_open",
            "ts": _now_iso(),
            "engine": eng,
            "ticket": int(ticket),
            "symbol": symbol,
            "direction": str(direction).upper(),
            "entry_price": round(float(entry_price), 5),
            "lot": round(float(lot), 4),
            **(extra or {}),
        }
        with _lock:
            self._append_jsonl(self._event_path(eng), row)

    def record_trade_close(
        self,
        engine: str,
        *,
        ticket: int,
        symbol: str,
        direction: str,
        pnl_usd: float,
        pnl_r: float,
        exit_reason: str = "",
        extra: dict[str, Any] | None = None,
    ) -> None:
        eng = engine.upper()
        row = {
            "event": "trade_close",
            "ts": _now_iso(),
            "engine": eng,
            "ticket": int(ticket),
            "symbol": symbol,
            "direction": str(direction).upper(),
            "pnl_usd": round(float(pnl_usd), 2),
            "final_R": round(float(pnl_r), 4),
            "exit_reason": exit_reason,
            **(extra or {}),
        }
        with _lock:
            self._append_jsonl(self._event_path(eng), row)
            if float(pnl_r) < 0:
                self._check_dd_alert(eng)

    def record_latency(self, *, stage: str, elapsed_sec: float, symbol: str = "") -> None:
        with _lock:
            self._latency_samples.append(float(elapsed_sec))
        if elapsed_sec > 2.0:
            self._emit_alert(
                "latency_high",
                stage=stage,
                elapsed_sec=round(elapsed_sec, 3),
                symbol=symbol,
            )

    def record_market_data_stale(self, *, symbol: str, stale: bool = True) -> None:
        if stale:
            self._emit_alert("market_data_stale", symbol=symbol, stale=True)

    def _check_dd_alert(self, engine: str) -> None:
        metrics = self._compute_trade_metrics(engine, days=7)
        if float(metrics.get("max_dd_r_30d", 0)) > 5.0:
            self._emit_alert(
                "max_dd_exceeded",
                engine=engine,
                max_dd_r=metrics.get("max_dd_r_30d"),
            )

    def _emit_alert(self, alert_type: str, **fields: Any) -> None:
        row = {"alert": alert_type, "ts": _now_iso(), **fields}
        with _lock:
            self._append_jsonl(self._alerts_path, row)

    def _check_alerts(self, engine: str) -> None:
        last = self._last_signal.get(engine)
        if last:
            ts = _parse_ts(last)
            if ts and datetime.now(timezone.utc) - ts > timedelta(hours=24):
                self._emit_alert("no_signal_24h", engine=engine, last_signal=last)
        metrics = self._compute_trade_metrics(engine, days=7)
        pf = float(metrics.get("pf_30d", 0) or 0)
        if metrics.get("trades_30d", 0) >= 5 and pf < 0.8:
            self._emit_alert("weekly_pf_low", engine=engine, pf=pf)

    def _events_since(self, engine: str, hours: float) -> list[dict[str, Any]]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        rows = self._read_jsonl(self._event_path(engine))
        out: list[dict[str, Any]] = []
        for r in rows:
            ts = _parse_ts(str(r.get("ts", "")))
            if ts and ts >= cutoff:
                out.append(r)
        return out

    def _compute_trade_metrics(self, engine: str, *, days: int = 30) -> dict[str, Any]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        closes = [
            r for r in self._read_jsonl(self._event_path(engine))
            if r.get("event") == "trade_close"
            and (lambda t: t and t >= cutoff)(_parse_ts(str(r.get("ts", ""))))
        ]
        if not closes:
            return {
                "trades_30d": 0,
                "win_rate_30d": 0.0,
                "pf_30d": 0.0,
                "expectancy_r_30d": 0.0,
                "max_dd_r_30d": 0.0,
            }
        rs = [float(c.get("final_R", 0)) for c in closes]
        wins = [r for r in rs if r > 0]
        pf = _profit_factor([{"pnl": r} for r in rs])
        eq = peak = mdd = 0.0
        for r in rs:
            eq += r
            peak = max(peak, eq)
            mdd = max(mdd, peak - eq)
        return {
            "trades_30d": len(closes),
            "win_rate_30d": round(len(wins) / len(rs) * 100, 2),
            "pf_30d": round(float(pf), 3) if pf not in ("inf", float("inf")) else "inf",
            "expectancy_r_30d": round(sum(rs) / len(rs), 3),
            "max_dd_r_30d": round(mdd, 2),
        }

    def _engine_health_row(self, engine: str) -> dict[str, Any]:
        events_24h = self._events_since(engine, 24)
        signals_24h = sum(1 for e in events_24h if e.get("event") == "signal")
        rejects_24h = sum(1 for e in events_24h if e.get("event") == "rejection")
        trades_24h = sum(1 for e in events_24h if e.get("event") == "trade_open")
        metrics = self._compute_trade_metrics(engine, days=30)
        ratio = round(trades_24h / signals_24h, 4) if signals_24h else 0.0
        enabled = self._engine_enabled(engine)
        last_sig = self._last_signal.get(engine, "")
        healthy = enabled and (
            not last_sig
            or (lambda t: t and datetime.now(timezone.utc) - t < timedelta(hours=48))(
                _parse_ts(last_sig)
            )
        )
        if engine == ENGINE_VOL and not enabled:
            healthy = True  # research-only, not broken
        if engine == ENGINE_ADAPTIVE and not enabled:
            healthy = False  # flagged needs redesign when off
        return {
            "engine_name": engine,
            "enabled": enabled,
            "healthy": healthy,
            "last_signal_time": last_sig or None,
            "signals_generated_24h": signals_24h,
            "signals_rejected_24h": rejects_24h,
            "trades_executed_24h": trades_24h,
            "win_rate_30d": metrics["win_rate_30d"],
            "pf_30d": metrics["pf_30d"],
            "expectancy_r_30d": metrics["expectancy_r_30d"],
            "max_dd_r_30d": metrics["max_dd_r_30d"],
            "signal_to_trade_ratio": ratio,
        }

    def update_engine_health(self) -> dict[str, Any]:
        health = {
            "updated_at": _now_iso(),
            "engines": [
                self._engine_health_row(ENGINE_PA),
                self._engine_health_row(ENGINE_VOL),
                self._engine_health_row(ENGINE_ADAPTIVE),
                self._engine_health_row(ENGINE_ML),
            ],
        }
        try:
            from tradingbot.services.runtime_truth import get_runtime_truth

            truth = get_runtime_truth()
            if truth.get("market_data_stale"):
                self.record_market_data_stale(symbol=str(truth.get("symbol", PRIMARY_SYMBOL)))
                for row in health["engines"]:
                    row["market_data_stale"] = True
        except Exception:
            pass
        with _lock:
            self._health_path.write_text(json.dumps(health, indent=2), encoding="utf-8")
        return health

    def build_daily_report(self, *, day: datetime | None = None) -> dict[str, Any]:
        from tradingbot.services.daily_engine_report import format_daily_engine_report

        day_dt = (day or datetime.now(timezone.utc)).replace(hour=0, minute=0, second=0, microsecond=0)
        date_str = day_dt.strftime("%Y-%m-%d")
        report: dict[str, Any] = {
            "date": date_str,
            "generated_at": _now_iso(),
            "engines": {},
            "alerts_24h": [],
            "warnings": [],
        }

        for engine in (ENGINE_PA, ENGINE_VOL, ENGINE_ADAPTIVE, ENGINE_ML):
            events = self._read_jsonl(self._event_path(engine))
            day_events = [
                e for e in events
                if (lambda t: t and t.date() == day_dt.date())(_parse_ts(str(e.get("ts", ""))))
            ]
            setups = sum(1 for e in day_events if e.get("event") == "signal")
            trades = sum(1 for e in day_events if e.get("event") == "trade_close")
            rejections = [e for e in day_events if e.get("event") == "rejection"]
            top_reject = Counter(str(r.get("reason", "unknown")) for r in rejections).most_common(5)
            closes = [e for e in day_events if e.get("event") == "trade_close"]
            rs = [float(c.get("final_R", 0)) for c in closes]
            wins = [r for r in rs if r > 0]
            pf = _profit_factor([{"pnl": r} for r in rs]) if rs else 0.0
            eq = peak = mdd = 0.0
            for r in rs:
                eq += r
                peak = max(peak, eq)
                mdd = max(mdd, peak - eq)
            health = self._engine_health_row(engine)
            report["engines"][engine] = {
                "setups": setups,
                "trades": trades,
                "rejections": len(rejections),
                "win_rate_pct": round(len(wins) / len(rs) * 100, 2) if rs else 0.0,
                "pf": round(float(pf), 3) if pf not in ("inf", float("inf")) else "inf",
                "expectancy_r": round(sum(rs) / len(rs), 3) if rs else 0.0,
                "max_dd_r": round(mdd, 2),
                "top_rejection_reasons": [{"reason": r, "count": c} for r, c in top_reject],
                "health": health,
            }

        alerts = self._read_jsonl(self._alerts_path, tail=500)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        report["alerts_24h"] = [
            a for a in alerts
            if (lambda t: t and t >= cutoff)(_parse_ts(str(a.get("ts", ""))))
        ]

        with _lock:
            self._daily_json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            txt_path = self._dir / f"daily_{date_str}.txt"
            txt_path.write_text(format_daily_engine_report(report), encoding="utf-8")
        return report


def get_engine_telemetry(base_dir: str | Path | None = None) -> EngineTelemetryService:
    global _instance
    if _instance is None:
        _instance = EngineTelemetryService(base_dir)
    return _instance


def resolve_engine_name(name: str) -> str:
    s = str(name or "").upper()
    if "VOL" in s:
        return ENGINE_VOL
    if "ADAPTIVE" in s:
        return ENGINE_ADAPTIVE
    if "ML" in s or "SHADOW" in s:
        return ENGINE_ML
    return ENGINE_PA


def resolve_engine_from_signal(signal: Any) -> str:
    meta = dict(getattr(signal, "metadata", None) or {})
    eng = str(meta.get("selected_engine") or meta.get("router_engine") or "").upper()
    if eng in ("PA", "PRICEACTION", "PRICE_ACTION"):
        return ENGINE_PA
    if "VOL" in eng:
        return ENGINE_VOL
    if "ADAPTIVE" in eng:
        return ENGINE_ADAPTIVE
    name = str(getattr(signal, "strategy_name", "") or "").lower()
    if "vol" in name:
        return ENGINE_VOL
    if "adaptive" in name:
        return ENGINE_ADAPTIVE
    if name in ("priceaction", "pa", "combined"):
        return ENGINE_PA
    return ENGINE_PA


def init_engine_log_structure(base_dir: str | Path | None = None) -> Path:
    """Create logs/engines/ and required empty files."""
    root = Path(base_dir) if base_dir else ROOT
    d = root / "logs" / "engines"
    d.mkdir(parents=True, exist_ok=True)
    for fname in (
        "pa_events.jsonl",
        "vol_events.jsonl",
        "adaptive_events.jsonl",
        "ml_shadow_events.jsonl",
        "pa_hold_reasons.jsonl",
        "alerts.jsonl",
    ):
        p = d / fname
        if not p.exists():
            p.touch()
    health = d / "engine_health.json"
    if not health.exists():
        health.write_text(json.dumps({"engines": [], "updated_at": _now_iso()}, indent=2), encoding="utf-8")
    daily = d / "daily_engine_report.json"
    if not daily.exists():
        daily.write_text(json.dumps({"date": "", "engines": {}}, indent=2), encoding="utf-8")
    return d

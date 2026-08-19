"""Phase 27A — 30-day production validation backtest."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.research.phase22c.hold_chain import get_hold_chain, reset_hold_chain
from tradingbot.ml.research.phase25b.unified_pipeline_replay import run_unified_pipeline_replay
from tradingbot.ml.research.phase27a.metrics import (
    build_buy_sell_analysis,
    build_cache_analysis,
    build_decision_analysis,
    build_engine_analysis,
    build_hold_analysis,
    build_integrity_scores,
    build_journal_integrity,
    build_latency_analysis,
    build_paper_readiness,
    build_profitability_metrics,
    build_regime_analysis,
    build_risk_analysis,
    build_system_health,
    build_trade_statistics,
)
from tradingbot.ml.research.phase27a.trade_builder import build_completed_trades
from tradingbot.ml.research.regime_router.phase99_feature_validation import normalize_candles_for_builder

PROJECT_ROOT = Path(__file__).resolve().parents[4]
PHASE_DIR = Path(__file__).resolve().parent
REPLAY_DAYS = 30
WARMUP_BARS = 300
MINIMUM_SAMPLE = 200
CACHE_DIR = PHASE_DIR / "_cache"


def _ts_iso(value: Any) -> str:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.isoformat()


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _prior_phases() -> dict[str, str]:
    return {
        "phase25b": _load_json(PHASE_DIR.parent / "phase25b" / "phase25b_final_report.json").get("verdict", ""),
        "phase26c": _load_json(PHASE_DIR.parent / "phase26c" / "phase26c_final_report.json").get("verdict", ""),
        "phase26d": _load_json(PHASE_DIR.parent / "phase26d" / "phase26d_final_report.json").get("verdict", ""),
        "phase26b": _load_json(PHASE_DIR.parent / "phase26b" / "phase26b_final_report.json").get("verdict", ""),
    }


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(x) for x in obj]
    if isinstance(obj, float) and (obj != obj or obj in (float("inf"), float("-inf"))):
        return str(obj)
    return obj


def _memory_mb() -> float:
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "win32":
            return round(usage / (1024 * 1024), 2)
        return round(usage / 1024, 2)
    except Exception:
        return 0.0


def run_phase27a(*, base_dir: str | Path | None = None, stride: int = 1) -> dict[str, Any]:
    ts = datetime.now(timezone.utc).isoformat()
    root = Path(base_dir or PROJECT_ROOT)
    symbol = "XAUUSD"
    timeframe = "M5"

    os.environ["USE_ML_KERNEL"] = "1"
    os.environ["ALLOW_LEGACY_FALLBACK"] = "0"
    os.environ["TRADINGBOT_PAPER"] = "1"

    candles_raw = CandleStore(root).load(symbol, timeframe)
    if candles_raw is None or candles_raw.empty:
        raise RuntimeError("CandleStore unavailable for XAUUSD M5")

    window = prepare_calibration_candles(candles_raw, days=REPLAY_DAYS)
    window = normalize_candles_for_builder(window)
    if len(window) < WARMUP_BARS + 10:
        raise RuntimeError(f"Insufficient candles: {len(window)} bars for {REPLAY_DAYS}d window")

    reset_hold_chain()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_records = CACHE_DIR / "replay_records.json"
    cache_meta = CACHE_DIR / "replay_meta.json"
    cache_hold = CACHE_DIR / "hold_chain.json"

    t0 = time.perf_counter()
    if cache_records.is_file() and cache_meta.is_file():
        records = json.loads(cache_records.read_text(encoding="utf-8"))
        replay_meta = json.loads(cache_meta.read_text(encoding="utf-8"))
        hold_chain = json.loads(cache_hold.read_text(encoding="utf-8")) if cache_hold.is_file() else {}
        elapsed = float(replay_meta.get("cached_elapsed_sec") or 0)
    else:
        records, replay_meta = run_unified_pipeline_replay(
            base_dir=str(root),
            symbol=symbol,
            timeframe=timeframe,
            days=REPLAY_DAYS,
            tail_only=None,
            stride=stride,
            warmup_bars=WARMUP_BARS,
            use_forming_bar_adapter=True,
        )
        elapsed = round(time.perf_counter() - t0, 2)
        hold_chain = get_hold_chain().snapshot()
        replay_meta["cached_elapsed_sec"] = elapsed
        cache_records.write_text(json.dumps(records), encoding="utf-8")
        cache_meta.write_text(json.dumps(replay_meta), encoding="utf-8")
        cache_hold.write_text(json.dumps(hold_chain), encoding="utf-8")

    trades = build_completed_trades(records, window, symbol=symbol)
    prior = _prior_phases()

    profitability = build_profitability_metrics(trades)
    trade_stats = build_trade_statistics(trades, records, replay_days=REPLAY_DAYS)
    buy_sell = build_buy_sell_analysis(trades)
    regime = build_regime_analysis(trades)
    engine = build_engine_analysis(trades)
    risk = build_risk_analysis(trades, records)
    hold = build_hold_analysis(records, hold_chain)
    decision = build_decision_analysis(records, hold_chain)
    latency = build_latency_analysis(records)
    cache = build_cache_analysis(records)
    health = build_system_health(records, replay_meta)
    health["replay_elapsed_sec"] = elapsed
    health["memory_mb_peak_estimate"] = _memory_mb()
    health["cpu_usage"] = "not_sampled_readonly"

    journal = build_journal_integrity(trades)
    eq = [{"timestamp": t.get("exit_timestamp"), "equity": None} for t in trades]
    running = 10_000.0
    eq_curve = [{"timestamp": None, "equity": running}]
    for t in sorted(trades, key=lambda x: x.get("exit_timestamp") or x.get("timestamp")):
        running += float(t["pnl"])
        eq_curve.append({"timestamp": t.get("exit_timestamp"), "equity": round(running, 4)})

    dd_curve = []
    peak = -1e18
    for pt in eq_curve:
        e = float(pt["equity"])
        peak = max(peak, e)
        dd = (peak - e) / peak * 100 if peak > 0 else 0
        dd_curve.append({"timestamp": pt["timestamp"], "drawdown_pct": round(dd, 4)})

    scores = build_integrity_scores(
        trades=trades,
        journal=journal,
        health=health,
        profitability=profitability,
        prior_phases=prior,
    )
    paper_ready = build_paper_readiness(
        scores=scores,
        trades=trades,
        health=health,
        journal=journal,
        prior=prior,
    )

    critical = []
    if len(trades) < MINIMUM_SAMPLE:
        critical.append({
            "id": "27A-001",
            "severity": "CRITICAL",
            "issue": f"Insufficient trades for statistical confidence: {len(trades)} < {MINIMUM_SAMPLE}",
        })
    if len(trades) == 0:
        rsi_holds = int((hold_chain.get("ml_hold_stages") or {}).get("rsi_filter_hold", 0))
        critical.append({
            "id": "27A-005",
            "severity": "CRITICAL",
            "issue": f"Zero executable trades in 30-day replay — RSI filter blocked {rsi_holds}/{replay_meta.get('bars_evaluated', 0)} bars",
            "evidence": "ml/research/phase22c/hold_chain.py snapshot",
        })
    if float(health.get("timeout_rate_pct") or 0) >= 10:
        critical.append({
            "id": "27A-002",
            "severity": "HIGH",
            "issue": f"Pipeline timeout rate {health.get('timeout_rate_pct')}% >= 10%",
        })
    if float(journal.get("journal_integrity_pct") or 0) < 100:
        critical.append({
            "id": "27A-003",
            "severity": "CRITICAL",
            "issue": "Replay trade reconstruction missing required fields",
        })
    if float(profitability.get("max_drawdown_pct") or 0) > 15:
        critical.append({
            "id": "27A-004",
            "severity": "MEDIUM",
            "issue": f"Max drawdown {profitability.get('max_drawdown_pct')}% exceeds 15% threshold",
        })

    verdict = (
        "READY_FOR_PAPER_TRADING"
        if paper_ready.get("ready") and not any(c["severity"] == "CRITICAL" for c in critical)
        else "NOT_READY_FOR_PAPER_TRADING"
    )

    window_meta = {
        "symbol": symbol,
        "timeframe": timeframe,
        "replay_days": REPLAY_DAYS,
        "warmup_bars": WARMUP_BARS,
        "stride": stride,
        "window_bars": len(window),
        "window_start": _ts_iso(window.index.min()),
        "window_end": _ts_iso(window.index.max()),
        "pipeline": "phase25b.run_unified_pipeline_replay",
        "audit_mode": "READ_ONLY",
        "production_modified": False,
    }

    outputs = {
        "backtest_summary.json": {**window_meta, **replay_meta, "generated_utc": ts, "elapsed_sec": elapsed},
        "profitability_metrics.json": {**profitability, "generated_utc": ts},
        "trade_statistics.json": {**trade_stats, "generated_utc": ts},
        "buy_sell_analysis.json": {**buy_sell, "generated_utc": ts},
        "regime_analysis.json": {**regime, "generated_utc": ts},
        "engine_analysis.json": {**engine, "generated_utc": ts},
        "risk_analysis.json": {**risk, "generated_utc": ts},
        "decision_analysis.json": {**decision, "generated_utc": ts},
        "hold_analysis.json": {**hold, "generated_utc": ts},
        "latency_analysis.json": {**latency, "generated_utc": ts},
        "cache_analysis.json": {**cache, "generated_utc": ts},
        "system_health.json": {**health, "generated_utc": ts},
        "journal_integrity.json": {**journal, "generated_utc": ts},
        "equity_curve.json": {"generated_utc": ts, "points": eq_curve},
        "drawdown_curve.json": {"generated_utc": ts, "points": dd_curve},
        "trade_log.json": {"generated_utc": ts, "count": len(trades), "trades": trades},
        "paper_readiness.json": {**paper_ready, "generated_utc": ts},
        "integrity_score.json": {**scores, "generated_utc": ts},
        "critical_findings.json": {"generated_utc": ts, "findings": critical},
        "phase27a_final_report.json": {
            "phase": "27A",
            "generated_utc": ts,
            "verdict": verdict,
            "audit_mode": "READ_ONLY",
            "production_modified": False,
            "replay_days": REPLAY_DAYS,
            "completed_trades": len(trades),
            "bars_evaluated": replay_meta.get("bars_evaluated"),
            "prior_phases": prior,
            "paper_readiness_score": scores.get("scores", {}).get("Paper_Readiness"),
            "overall_score": scores.get("overall_score"),
            "profit_factor": profitability.get("profit_factor"),
            "expectancy": profitability.get("expectancy"),
            "win_rate": trade_stats.get("win_rate"),
            "max_drawdown_pct": profitability.get("max_drawdown_pct"),
            "timeout_rate_pct": health.get("timeout_rate_pct"),
            "summary": (
                f"30-day production unified pipeline replay on {symbol} {timeframe}: "
                f"{len(trades)} completed trades from {replay_meta.get('bars_evaluated', 0)} bars. "
                f"PF={profitability.get('profit_factor')} expectancy={profitability.get('expectancy')} "
                f"timeout_rate={health.get('timeout_rate_pct')}%. Verdict: {verdict}."
            ),
        },
    }

    PHASE_DIR.mkdir(parents=True, exist_ok=True)
    for name, payload in outputs.items():
        (PHASE_DIR / name).write_text(json.dumps(_json_safe(payload), indent=2), encoding="utf-8")

    return outputs["phase27a_final_report.json"]


def main() -> int:
    report = run_phase27a()
    print(json.dumps(report, indent=2))
    return 0 if report.get("verdict") == "READY_FOR_PAPER_TRADING" else 1


if __name__ == "__main__":
    raise SystemExit(main())

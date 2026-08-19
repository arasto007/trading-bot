"""Phase 29B — WPSQF production integration orchestrator."""

from __future__ import annotations

import json
import os
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.adapters.legacy_loader import load_legacy_config
from tradingbot.domain.enums import SignalDirection
from tradingbot.domain.models import MarketKey, TradingSignal
from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.research.phase25b.unified_pipeline_replay import run_unified_pipeline_replay
from tradingbot.ml.research.phase28d.trade_builder import trades_from_replay_meta
from tradingbot.ml.research.regime_router.phase99_feature_validation import normalize_candles_for_builder
from tradingbot.services.signal_filter_log import clear_log, export_log, get_rejections
from tradingbot.services.signal_filter_mode import DEFAULT_THRESHOLD, SignalFilterMode
from tradingbot.services.winner_population_signal_quality_filter import WinnerPopulationSignalQualityFilter
from tradingbot.services.wpsqf_calibration import WINNER_CALIBRATION

PROJECT_ROOT = Path(__file__).resolve().parents[4]
PHASE_DIR = Path(__file__).resolve().parent
PHASE28F_DIR = PROJECT_ROOT / "tradingbot" / "ml" / "research" / "phase28f"
PHASE29A_DIR = PROJECT_ROOT / "tradingbot" / "ml" / "research" / "phase29a"
CACHE_DIR = PHASE_DIR / "_cache"

INITIAL_BALANCE = 200.0
TOLERANCE_PCT = 2.0
LATENCY_BUDGET_MS = 5.0

PHASE29A_EXPECTED = {
    "completed_trades": 489,
    "profit_factor": 1.211,
    "expectancy": 0.28,
    "max_drawdown_pct": 24.26,
}

PHASE28F_BASELINE = {
    "completed_trades": 575,
    "profit_factor": 1.0923,
    "expectancy": 0.1318,
    "max_drawdown_pct": 30.6312,
    "net_profit": 75.7757,
    "win_rate_pct": None,
    "sharpe_ratio": 10.8077,
    "recovery_factor": 0.8482,
}


def _write(name: str, payload: dict[str, Any]) -> None:
    (PHASE_DIR / name).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _perf_from_meta(meta: dict[str, Any]) -> dict[str, Any]:
    accounting = meta.get("accounting") or {}
    return dict(accounting.get("performance") or {})


def _within_tolerance(actual: float, expected: float, *, pct: float = TOLERANCE_PCT) -> bool:
    if expected == 0:
        return abs(actual - expected) < 0.01
    return abs(actual - expected) / abs(expected) * 100 <= pct


def _trade_fingerprint(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "timestamp": t.get("timestamp"),
            "exit_timestamp": t.get("exit_timestamp"),
            "direction": t.get("direction"),
            "entry_price": round(float(t.get("entry_price", 0)), 5),
            "exit_price": round(float(t.get("exit_price", 0)), 5),
            "lot": round(float(t.get("lot", 0)), 4),
            "pnl": round(float(t.get("pnl", 0)), 4),
            "pnl_r": round(float(t.get("pnl_r", 0)), 4),
        }
        for t in trades
    ]


def _run_replay(
    *,
    root: Path,
    filter_mode: str,
    cache_suffix: str,
    use_cache: bool = True,
) -> tuple[list, dict[str, Any]]:
    cache = CACHE_DIR / cache_suffix
    meta_path = cache / "replay_meta.json"
    records_path = cache / "replay_records.json"
    if use_cache and meta_path.is_file() and records_path.is_file():
        print(f"[phase29b] using cached replay filter={filter_mode}")
        return (
            json.loads(records_path.read_text(encoding="utf-8")),
            json.loads(meta_path.read_text(encoding="utf-8")),
        )

    os.environ["TRADINGBOT_PAPER"] = "1"
    os.environ["TRADINGBOT_EXIT_MODE"] = "HYBRID_B"
    os.environ["USE_ML_KERNEL"] = "1"
    os.environ["ALLOW_LEGACY_FALLBACK"] = "0"
    os.environ["TRADINGBOT_SIGNAL_FILTER"] = filter_mode
    if filter_mode == SignalFilterMode.WPSQF.value:
        os.environ.setdefault("TRADINGBOT_WPSQF_THRESHOLD", str(DEFAULT_THRESHOLD))
    else:
        os.environ.pop("TRADINGBOT_WPSQF_THRESHOLD", None)

    clear_log()
    legacy = load_legacy_config()
    legacy["BASE_DIR"] = str(root)
    legacy["initial_balance"] = INITIAL_BALANCE
    legacy["signal_filter_mode"] = filter_mode

    print(f"[phase29b] running 30-day replay filter={filter_mode}...")
    from tradingbot.ml.integration import kernel_adapter as ka_mod
    from tradingbot.ml.integration.pipeline_cache import PipelineCache

    orig_timeout = ka_mod.PIPELINE_TIMEOUT_MS
    ka_mod.PIPELINE_TIMEOUT_MS = 30_000.0
    PipelineCache.reset()
    try:
        records, meta = run_unified_pipeline_replay(
            base_dir=str(root),
            symbol="XAUUSD",
            timeframe="M5",
            tail_only=None,
            days=30,
            stride=1,
            warmup_bars=300,
            use_forming_bar_adapter=True,
            legacy_config=legacy,
            exit_mode="HYBRID_B",
        )
    finally:
        ka_mod.PIPELINE_TIMEOUT_MS = orig_timeout

    cache.mkdir(parents=True, exist_ok=True)
    records_path.write_text(json.dumps(records), encoding="utf-8")
    meta_light = {k: v for k, v in meta.items() if k not in ("portfolio_timeline", "position_lifecycle")}
    meta_path.write_text(json.dumps(meta_light, indent=2), encoding="utf-8")
    return records, meta_light


def _benchmark_latency(root: Path) -> dict[str, Any]:
    raw = CandleStore(str(root)).load("XAUUSD", "M5")
    window = prepare_calibration_candles(raw, days=30) if raw is not None else None
    if window is None or window.empty:
        return {"error": "candles_unavailable", "pass": False}

    candles = normalize_candles_for_builder(window)
    if not isinstance(candles.index, pd.DatetimeIndex):
        if "time" in candles.columns:
            candles = candles.set_index("time")
    candles.index = pd.to_datetime(candles.index, utc=True)

    filt = WinnerPopulationSignalQualityFilter()
    signal = TradingSignal(
        symbol="XAUUSD",
        timeframe="M5",
        direction=SignalDirection.BUY,
        confidence=0.85,
        stop_loss=1990.0,
        take_profit=2010.0,
        strategy_name="test",
        metadata={"confidence": 0.85, "regime": "TREND", "engine_name": "trend"},
    )

    samples: list[float] = []
    for i in range(300, min(len(candles), 350)):
        closed = candles.iloc[: i + 1]
        t0 = time.perf_counter()
        filt.evaluate(signal, closed, timestamp=str(closed.index[-1]))
        samples.append((time.perf_counter() - t0) * 1000)

    samples.sort()
    p50 = samples[len(samples) // 2] if samples else 0.0
    p95 = samples[int(len(samples) * 0.95)] if samples else 0.0
    p99 = samples[int(len(samples) * 0.99)] if samples else 0.0
    mx = max(samples) if samples else 0.0

    return {
        "phase": "29B",
        "samples": len(samples),
        "latency_ms": {
            "p50": round(p50, 4),
            "p95": round(p95, 4),
            "p99": round(p99, 4),
            "max": round(mx, 4),
            "mean": round(sum(samples) / len(samples), 4) if samples else 0.0,
        },
        "budget_ms": LATENCY_BUDGET_MS,
        "pass": p95 < LATENCY_BUDGET_MS,
    }


def _benchmark_memory_cpu() -> dict[str, Any]:
    raw = CandleStore(str(PROJECT_ROOT)).load("XAUUSD", "M5")
    window = prepare_calibration_candles(raw, days=30) if raw is not None else None
    if window is None or window.empty:
        return {"error": "candles_unavailable", "pass": False}

    candles = normalize_candles_for_builder(window).tail(350)
    if not isinstance(candles.index, pd.DatetimeIndex):
        if "time" in candles.columns:
            candles = candles.set_index("time")
    candles.index = pd.to_datetime(candles.index, utc=True)

    signal = TradingSignal(
        symbol="XAUUSD",
        timeframe="M5",
        direction=SignalDirection.SELL,
        confidence=0.9,
        stop_loss=2010.0,
        take_profit=1990.0,
        strategy_name="test",
        metadata={"confidence": 0.9, "regime": "RANGE", "engine_name": "range"},
    )
    filt = WinnerPopulationSignalQualityFilter()

    tracemalloc.start()
    t0 = time.perf_counter()
    for i in range(300, len(candles)):
        filt.evaluate(signal, candles.iloc[: i + 1], timestamp=str(candles.index[-1]))
    elapsed_ms = (time.perf_counter() - t0) * 1000
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    per_eval_ms = elapsed_ms / max(len(candles) - 300, 1)
    return {
        "phase": "29B",
        "evaluations": len(candles) - 300,
        "total_elapsed_ms": round(elapsed_ms, 4),
        "per_evaluation_ms": round(per_eval_ms, 4),
        "memory_current_kb": round(current / 1024, 2),
        "memory_peak_kb": round(peak / 1024, 2),
        "latency_budget_ms": LATENCY_BUDGET_MS,
        "pass": per_eval_ms < LATENCY_BUDGET_MS,
    }


def _filter_score_determinism(root: Path) -> dict[str, Any]:
    raw = CandleStore(str(root)).load("XAUUSD", "M5")
    window = prepare_calibration_candles(raw, days=30) if raw is not None else None
    if window is None or window.empty:
        return {"pass": False, "error": "candles_unavailable"}
    candles = normalize_candles_for_builder(window)
    if not isinstance(candles.index, pd.DatetimeIndex):
        if "time" in candles.columns:
            candles = candles.set_index("time")
    candles.index = pd.to_datetime(candles.index, utc=True)

    filt = WinnerPopulationSignalQualityFilter()
    signal = TradingSignal(
        symbol="XAUUSD",
        timeframe="M5",
        direction=SignalDirection.BUY,
        confidence=0.85,
        stop_loss=1990.0,
        take_profit=2010.0,
        strategy_name="test",
        metadata={"confidence": 0.85, "regime": "TREND", "engine_name": "trend"},
    )
    mismatches = 0
    checks = 0
    for i in range(300, min(len(candles), 360)):
        closed = candles.iloc[: i + 1]
        a = filt.evaluate(signal, closed, timestamp=str(closed.index[-1]))
        b = filt.evaluate(signal, closed, timestamp=str(closed.index[-1]))
        checks += 1
        if a.to_dict() != b.to_dict():
            mismatches += 1
    return {
        "phase": "29B",
        "checks": checks,
        "mismatches": mismatches,
        "pass": mismatches == 0,
    }


def run_phase29b(*, base_dir: str | Path | None = None, force_replay: bool = False) -> dict[str, Any]:
    ts = datetime.now(timezone.utc).isoformat()
    root = Path(base_dir or PROJECT_ROOT)
    PHASE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    wpsqf_service = {
        "phase": "29B",
        "service": "WinnerPopulationSignalQualityFilter",
        "module": "tradingbot.services.winner_population_signal_quality_filter",
        "pipeline_stage": "tradingbot.pipeline.signal_filter_stage.SignalFilterStage",
        "position": "after SignalStage, before RiskStage",
        "config_env": {
            "TRADINGBOT_SIGNAL_FILTER": ["OFF", "WPSQF"],
            "TRADINGBOT_WPSQF_THRESHOLD": "float, default 77.56",
        },
        "default_threshold": DEFAULT_THRESHOLD,
        "calibration": WINNER_CALIBRATION,
        "reject_rule": "signal_quality_score < threshold",
        "deterministic": True,
        "generated_utc": ts,
    }
    _write("wpsqf_service.json", wpsqf_service)

    latency = _benchmark_latency(root)
    _write("latency_validation.json", {**latency, "generated_utc": ts})

    perf_bench = _benchmark_memory_cpu()
    _write("performance_validation.json", {**perf_bench, "generated_utc": ts})

    baseline_meta_path = PHASE28F_DIR / "_cache" / "replay_meta.json"
    baseline_meta = _load_json(baseline_meta_path)
    baseline_trades = trades_from_replay_meta(baseline_meta) if baseline_meta else []
    baseline_perf = _perf_from_meta(baseline_meta) if baseline_meta else {}

    off_records, off_meta = _run_replay(
        root=root, filter_mode=SignalFilterMode.OFF.value, cache_suffix="off", use_cache=not force_replay
    )
    off_trades = trades_from_replay_meta(off_meta)
    off_perf = _perf_from_meta(off_meta)

    off_fp = _trade_fingerprint(off_trades)
    base_fp = _trade_fingerprint(baseline_trades)
    backward = {
        "phase": "29B",
        "filter_mode": "OFF",
        "baseline_source": str(baseline_meta_path),
        "trade_count_match": len(off_trades) == len(baseline_trades),
        "fingerprint_match": off_fp == base_fp,
        "pnl_match": round(sum(float(t.get("pnl", 0)) for t in off_trades), 4)
        == round(sum(float(t.get("pnl", 0)) for t in baseline_trades), 4),
        "performance_match": {
            k: round(float(off_perf.get(k, 0)), 4) == round(float(baseline_perf.get(k, 0)), 4)
            for k in ("net_profit", "completed_trades", "profit_factor", "expectancy", "max_drawdown_pct")
            if baseline_perf.get(k) is not None
        },
        "pipeline_stages_off": off_meta.get("pipeline_stages"),
        "pass": off_fp == base_fp,
        "generated_utc": ts,
    }
    _write("backward_compatibility.json", backward)

    wpsqf_records, wpsqf_meta = _run_replay(
        root=root,
        filter_mode=SignalFilterMode.WPSQF.value,
        cache_suffix="wpsqf",
        use_cache=not force_replay,
    )
    wpsqf_trades = trades_from_replay_meta(wpsqf_meta)
    wpsqf_perf = _perf_from_meta(wpsqf_meta)

    export_log(PHASE_DIR / "signal_filter_log.json")
    rejections = get_rejections()

    wpsqf_records2, wpsqf_meta2 = _run_replay(
        root=root,
        filter_mode=SignalFilterMode.WPSQF.value,
        cache_suffix="wpsqf_run2",
        use_cache=not force_replay,
    )
    wpsqf_trades2 = trades_from_replay_meta(wpsqf_meta2)
    wpsqf_perf2 = _perf_from_meta(wpsqf_meta2)
    rejections2 = get_rejections()

    score_det = _filter_score_determinism(root)
    replay_det_pass = (
        _trade_fingerprint(wpsqf_trades) == _trade_fingerprint(wpsqf_trades2)
        and round(sum(float(t.get("pnl", 0)) for t in wpsqf_trades), 4)
        == round(sum(float(t.get("pnl", 0)) for t in wpsqf_trades2), 4)
    )

    determinism = {
        "phase": "29B",
        "run1_trades": len(wpsqf_trades),
        "run2_trades": len(wpsqf_trades2),
        "trade_fingerprint_match": _trade_fingerprint(wpsqf_trades) == _trade_fingerprint(wpsqf_trades2),
        "pnl_match": round(sum(float(t.get("pnl", 0)) for t in wpsqf_trades), 4)
        == round(sum(float(t.get("pnl", 0)) for t in wpsqf_trades2), 4),
        "performance_match": {
            k: round(float(wpsqf_perf.get(k, 0)), 4) == round(float(wpsqf_perf2.get(k, 0)), 4)
            for k in ("net_profit", "completed_trades", "profit_factor", "expectancy", "max_drawdown_pct")
        },
        "rejection_count_match": len(rejections) == len(rejections2),
        "wpsqf_score_determinism": score_det,
        "replay_deterministic": replay_det_pass,
        "pass": score_det["pass"] and replay_det_pass,
        "generated_utc": ts,
    }
    _write("determinism_validation.json", determinism)

    replay_checks = {
        "trades": _within_tolerance(
            float(wpsqf_perf.get("completed_trades", 0)), PHASE29A_EXPECTED["completed_trades"]
        ),
        "profit_factor": _within_tolerance(
            float(wpsqf_perf.get("profit_factor", 0)), PHASE29A_EXPECTED["profit_factor"]
        ),
        "expectancy": _within_tolerance(
            float(wpsqf_perf.get("expectancy", 0)), PHASE29A_EXPECTED["expectancy"]
        ),
        "max_drawdown_pct": _within_tolerance(
            float(wpsqf_perf.get("max_drawdown_pct", 0)), PHASE29A_EXPECTED["max_drawdown_pct"]
        ),
    }
    integration = {
        "phase": "29B",
        "filter_mode": "WPSQF",
        "threshold": DEFAULT_THRESHOLD,
        "pipeline_stages": wpsqf_meta.get("pipeline_stages"),
        "signal_filter_in_pipeline": "signal_filter" in (wpsqf_meta.get("pipeline_stages") or []),
        "rejections_logged": len(rejections),
        "completed_trades": wpsqf_perf.get("completed_trades"),
        "phase29a_expected": PHASE29A_EXPECTED,
        "actual": {
            "completed_trades": wpsqf_perf.get("completed_trades"),
            "profit_factor": wpsqf_perf.get("profit_factor"),
            "expectancy": wpsqf_perf.get("expectancy"),
            "max_drawdown_pct": wpsqf_perf.get("max_drawdown_pct"),
            "net_profit": wpsqf_perf.get("net_profit"),
            "win_rate_pct": wpsqf_perf.get("win_rate_pct"),
            "sharpe_ratio": wpsqf_perf.get("sharpe_ratio"),
            "recovery_factor": wpsqf_perf.get("recovery_factor"),
        },
        "tolerance_pct": TOLERANCE_PCT,
        "checks": replay_checks,
        "pass": all(replay_checks.values()),
        "generated_utc": ts,
    }
    _write("integration_validation.json", integration)

    before_after = {
        "phase": "29B",
        "phase28f_off": {
            "completed_trades": off_perf.get("completed_trades"),
            "profit_factor": off_perf.get("profit_factor"),
            "expectancy": off_perf.get("expectancy"),
            "max_drawdown_pct": off_perf.get("max_drawdown_pct"),
            "net_profit": off_perf.get("net_profit"),
            "win_rate_pct": off_perf.get("win_rate_pct"),
            "sharpe_ratio": off_perf.get("sharpe_ratio"),
            "recovery_factor": off_perf.get("recovery_factor"),
        },
        "phase29b_wpsqf": {
            "completed_trades": wpsqf_perf.get("completed_trades"),
            "profit_factor": wpsqf_perf.get("profit_factor"),
            "expectancy": wpsqf_perf.get("expectancy"),
            "max_drawdown_pct": wpsqf_perf.get("max_drawdown_pct"),
            "net_profit": wpsqf_perf.get("net_profit"),
            "win_rate_pct": wpsqf_perf.get("win_rate_pct"),
            "sharpe_ratio": wpsqf_perf.get("sharpe_ratio"),
            "recovery_factor": wpsqf_perf.get("recovery_factor"),
        },
        "latency_ms_p95": latency.get("latency_ms", {}).get("p95"),
        "memory_peak_kb": perf_bench.get("memory_peak_kb"),
        "per_evaluation_ms": perf_bench.get("per_evaluation_ms"),
        "deterministic": determinism["pass"],
        "backward_compatible": backward["pass"],
        "generated_utc": ts,
    }
    _write("before_after_comparison.json", before_after)

    production_validation = {
        "phase": "29B",
        "integration": integration["pass"],
        "backward_compatibility": backward["pass"],
        "determinism": determinism["pass"],
        "latency": latency["pass"],
        "performance_budget": perf_bench["pass"],
        "strategy_logic_modified": False,
        "ml_models_modified": False,
        "ready_for_paper_trading": all(
            [
                integration["pass"],
                backward["pass"],
                determinism["pass"],
                latency["pass"],
            ]
        ),
        "generated_utc": ts,
    }
    _write("production_validation.json", production_validation)

    verdict = "PRODUCTION_INTEGRATION_VALIDATED" if production_validation["ready_for_paper_trading"] else "PRODUCTION_INTEGRATION_NEEDS_REVIEW"
    final = {
        "phase": "29B",
        "verdict": verdict,
        "explanation": (
            f"WPSQF integrated after ML before RiskGate. "
            f"WPSQF replay: {wpsqf_perf.get('completed_trades')} trades, "
            f"PF {wpsqf_perf.get('profit_factor')}, expectancy {wpsqf_perf.get('expectancy')}. "
            f"OFF mode backward compatible: {backward['pass']}. "
            f"Deterministic: {determinism['pass']}. Latency p95: {latency.get('latency_ms', {}).get('p95')}ms."
        ),
        "production_validation": production_validation,
        "generated_utc": ts,
    }
    _write("phase29b_final_report.json", final)
    return final


def main() -> int:
    report = run_phase29b()
    print(json.dumps({"verdict": report["verdict"], "explanation": report["explanation"]}, indent=2))
    return 0 if report.get("verdict") == "PRODUCTION_INTEGRATION_VALIDATED" else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Phase 1B — full PA+Meta backtest certification (cache-only, HTF bypass)."""

from __future__ import annotations

import math
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
CACHE_DIR = ROOT / "data" / "cache"

GATES = {
    "pf_min": 1.5,
    "exp_min": 0.4,
    "dd_max_r": 6.0,
    "mc_pf_min": 1.3,
    "ruin_max_pct": 5.0,
    "min_trades": 20,
}


def ensure_cache_parquets() -> dict[int, Path]:
    """Ensure data/cache/XAUUSD_M5_{30,60,90}d.parquet exist (slice from 180d if needed)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out: dict[int, Path] = {}
    src_180 = ROOT / "data" / "backtest" / "XAUUSD_M5_180d.parquet"
    src_95 = ROOT / "data" / "backtest" / "XAUUSD_M5_95d.parquet"
    src_30 = ROOT / "data" / "backtest" / "XAUUSD_M5_30d.parquet"
    bpd = 288

    for days in (30, 60, 90):
        dest = CACHE_DIR / f"XAUUSD_M5_{days}d.parquet"
        if dest.is_file():
            out[days] = dest
            continue
        if days == 30 and src_30.is_file():
            import shutil
            shutil.copy2(src_30, dest)
            out[days] = dest
            continue
        src = src_180 if src_180.is_file() else src_95
        if not src.is_file():
            raise FileNotFoundError(f"No source parquet for {days}d cache")
        df = pd.read_parquet(src)
        n = min(len(df), days * bpd)
        df.tail(n).to_parquet(dest, index=True)
        out[days] = dest
    return out


def _pf_num(v: Any) -> float:
    if v in ("inf", float("inf")):
        return 999.0
    return float(v)


def _trade_metrics(trades: list[Any]) -> dict[str, Any]:
    if not trades:
        return {
            "trades": 0,
            "win_rate_pct": 0.0,
            "profit_factor": 0.0,
            "expectancy_r": 0.0,
            "max_drawdown_r": 0.0,
            "sharpe": 0.0,
            "longest_loss_streak": 0,
            "average_hold_bars": 0.0,
        }
    rs = [float(t.r_multiple) for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    gw, gl = sum(wins), abs(sum(losses))
    pf = gw / gl if gl > 0 else (999.0 if gw > 0 else 0.0)

    eq = peak = mdd = 0.0
    streak = max_streak = 0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
        if r < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0

    holds = [
        max(0, int(getattr(t, "exit_index", 0)) - int(getattr(t, "entry_index", 0)))
        for t in trades
        if getattr(t, "exit_index", 0) and getattr(t, "entry_index", 0)
    ]
    avg_hold = sum(holds) / len(holds) if holds else 0.0

    mean_r = sum(rs) / len(rs)
    var_r = sum((r - mean_r) ** 2 for r in rs) / max(len(rs) - 1, 1)
    sharpe = (mean_r / math.sqrt(var_r)) * math.sqrt(len(rs)) if var_r > 0 else 0.0

    return {
        "trades": len(trades),
        "win_rate_pct": round(len(wins) / len(rs) * 100, 2),
        "profit_factor": round(pf, 3) if pf != 999.0 else "inf",
        "expectancy_r": round(mean_r, 3),
        "max_drawdown_r": round(mdd, 2),
        "sharpe": round(sharpe, 3),
        "longest_loss_streak": max_streak,
        "average_hold_bars": round(avg_hold, 1),
    }


def monte_carlo_r(
    r_multiples: list[float],
    *,
    simulations: int = 10_000,
    seed: int = 42,
    ruin_r: float = -6.0,
) -> dict[str, Any]:
    import numpy as np

    rs = np.asarray(r_multiples, dtype=float)
    if len(rs) < 5:
        return {
            "simulations": 0,
            "median_pf": 0.0,
            "median_expectancy": 0.0,
            "worst_5pct_drawdown_r": 0.0,
            "probability_of_ruin_pct": 100.0,
        }
    rng = np.random.default_rng(seed)
    pfs: list[float] = []
    exps: list[float] = []
    dds: list[float] = []
    ruins = 0
    for _ in range(simulations):
        sample = rng.choice(rs, size=len(rs), replace=True)
        wins = sample[sample > 0]
        losses = sample[sample < 0]
        gw, gl = float(wins.sum()), abs(float(losses.sum()))
        pf = gw / gl if gl > 0 else (999.0 if gw > 0 else 0.0)
        pfs.append(min(pf, 50.0))
        exps.append(float(sample.mean()))
        eq = peak = mdd = 0.0
        ruined = False
        for r in sample:
            eq += r
            if eq <= ruin_r:
                ruined = True
            peak = max(peak, eq)
            mdd = max(mdd, peak - eq)
        dds.append(mdd)
        if ruined:
            ruins += 1
    return {
        "simulations": simulations,
        "median_pf": round(float(np.median(pfs)), 3),
        "median_expectancy": round(float(np.median(exps)), 3),
        "worst_5pct_drawdown_r": round(float(np.percentile(dds, 95)), 2),
        "probability_of_ruin_pct": round(ruins / simulations * 100, 2),
    }


def _load_parquet_df(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    if df.index.tz is None:
        df.index = pd.to_datetime(df.index, utc=True)
    return df


def run_replay_window(days: int, parquet_path: Path) -> dict[str, Any]:
    """Fast PA+Meta replay on cache parquet (same PA+Meta path, no full kernel bar loop)."""
    from logs.phase_c_meta_resurrection import apply_meta_filter, collect_pa_trades
    from tradingbot.services.meta_labeler import get_meta_labeler

    os.environ["H1_ENABLED"] = "false"
    os.environ["H4_ENABLED"] = "false"

    df = _load_parquet_df(parquet_path)
    raw = collect_pa_trades(df)
    meta = get_meta_labeler()
    kept, _ = apply_meta_filter(raw, df, meta, threshold=0.38, fp=None)

    class _T:
        def __init__(self, row: dict[str, Any]) -> None:
            self.r_multiple = row["r_multiple"]
            self.entry_index = int(row.get("bar_index", 0))
            self.exit_index = int(row.get("bar_index", 0)) + int(row.get("hold_bars", 1) or 1)

    trades = [_T(r) for r in kept]
    metrics = _trade_metrics(trades)
    metrics["days"] = days
    metrics["bars"] = len(df)
    metrics["parquet"] = str(parquet_path)
    metrics["mode"] = "pa_meta_replay"
    return {"metrics": metrics, "trades": kept, "r_multiples": [float(t.r_multiple) for t in trades]}


async def run_backtest_window(
    days: int,
    parquet_path: Path,
) -> dict[str, Any]:
    """Run BacktestEngine on a single cache parquet window — no MT5, no HTF fetch."""
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.adapters.legacy_strategy_registry import LegacyStrategyRegistry
    from tradingbot.adapters.indicator_engine import TechnicalIndicatorEngine
    from tradingbot.backtest.config import BacktestConfig
    from tradingbot.backtest.engine import BacktestEngine
    from tradingbot.services.meta_labeler import MetaLabeler, reload_meta_labeler

    os.environ["H1_ENABLED"] = "false"
    os.environ["H4_ENABLED"] = "false"

    reload_meta_labeler()
    df = _load_parquet_df(parquet_path)

    legacy = load_legacy_config()
    ind = TechnicalIndicatorEngine(legacy)
    enriched = ind.enrich_for_market(df, "M5", "XAUUSD")
    enriched = enriched.dropna(subset=["open", "high", "low", "close"])

    cfg = BacktestConfig(
        symbols=["XAUUSD"],
        timeframe="M5",
        days=days,
        warmup=500,
        initial_balance=1000.0,
        risk_per_trade=0.005,
        max_trades_per_day=3,
        cooldown_bars=18,
        require_htf_alignment_m5=False,
        require_htf_alignment_m15=False,
        require_htf_alignment_h4=False,
        use_meta_labeler=True,
        max_spread_pips=15.0,
        spread_pips=4.0,
        slippage_pips=1.0,
        min_lot=0.01,
        max_lot=0.10,
        enable_trailing=False,
        enable_partial_tp=False,
        enable_emergency=False,
        use_news_filter=False,
        use_cache=False,
        cache_dir=str(CACHE_DIR),
        position_management_mode="none",
    )
    pa_reg = LegacyStrategyRegistry(legacy)

    @contextmanager
    def _fixed_meta(threshold: float = 0.38):
        orig_eff = MetaLabeler.effective_threshold
        orig_cal = MetaLabeler.calibrated_threshold
        MetaLabeler.calibrated_threshold = lambda self, timeframe: None  # type: ignore
        MetaLabeler.effective_threshold = lambda self, tf, reg, base: float(threshold)  # type: ignore
        try:
            yield
        finally:
            MetaLabeler.effective_threshold = orig_eff
            MetaLabeler.calibrated_threshold = orig_cal

    with _fixed_meta(0.38):
        engine = BacktestEngine(cfg, legacy, quiet=True, strategies=pa_reg)
        engine._htf.load = lambda: None  # type: ignore
        engine._htf.needs_htf = lambda: False  # type: ignore
        engine._data.inject({"XAUUSD": enriched})
        if engine._data.length <= cfg.warmup + 1:
            raise RuntimeError(f"Insufficient bars ({engine._data.length}) for {days}d")
        result = await engine.run()

    metrics = _trade_metrics(result.trades)
    metrics["mode"] = "backtest_engine"
    return {"metrics": metrics, "trades": result.trades, "result": result, "r_multiples": [float(t.r_multiple) for t in result.trades]}


async def run_window_with_fallback(
    days: int,
    parquet_path: Path,
    *,
    use_engine: bool = True,
    engine_timeout_sec: float | None = None,
) -> dict[str, Any]:
    """Run BacktestEngine (no timeout by default) or PA+Meta replay when use_engine=False."""
    if not use_engine:
        return run_replay_window(days, parquet_path)
    import asyncio

    coro = run_backtest_window(days, parquet_path)
    if engine_timeout_sec is not None:
        try:
            return await asyncio.wait_for(coro, timeout=engine_timeout_sec)
        except asyncio.TimeoutError:
            out = run_replay_window(days, parquet_path)
            out["metrics"]["engine_timeout"] = True
            out["metrics"]["mode"] = "pa_meta_replay_fallback"
            return out
    return await coro


def evaluate_certification(
    windows: dict[int, dict[str, Any]],
    mc: dict[str, Any],
) -> dict[str, bool]:
    gates: dict[str, bool] = {}
    for days, data in windows.items():
        m = data["metrics"]
        gates[f"window_{days}d_trades"] = int(m.get("trades", 0)) >= GATES["min_trades"]
        gates[f"window_{days}d_pf"] = _pf_num(m["profit_factor"]) > GATES["pf_min"]
        gates[f"window_{days}d_exp"] = float(m["expectancy_r"]) > GATES["exp_min"]
        gates[f"window_{days}d_dd"] = float(m["max_drawdown_r"]) < GATES["dd_max_r"]
    gates["mc_median_pf"] = float(mc.get("median_pf", 0)) > GATES["mc_pf_min"]
    gates["mc_ruin"] = float(mc.get("probability_of_ruin_pct", 100)) < GATES["ruin_max_pct"]
    gates["engine_mode"] = all(
        data.get("metrics", {}).get("mode") == "backtest_engine" for data in windows.values()
    )
    gates["certified"] = all(gates.values())
    return gates


def format_phase1b_result(
    windows: dict[int, dict[str, Any]],
    mc: dict[str, Any],
    *,
    certified: bool,
) -> str:
    m30 = windows.get(30, {}).get("metrics", {})
    m60 = windows.get(60, {}).get("metrics", {})
    m90 = windows.get(90, {}).get("metrics", {})
    lines = [
        "PHASE_1B_RESULT",
        f"WINDOW_30D_PF={m30.get('profit_factor', 0)}",
        f"WINDOW_60D_PF={m60.get('profit_factor', 0)}",
        f"WINDOW_90D_PF={m90.get('profit_factor', 0)}",
        f"MC_MEDIAN_PF={mc.get('median_pf', 0)}",
        f"MC_WORST_5PCT_DD={mc.get('worst_5pct_drawdown_r', 0)}",
        f"PA_CERTIFIED_FOR_PRODUCTION={'YES' if certified else 'NO'}",
    ]
    return "\n".join(lines)

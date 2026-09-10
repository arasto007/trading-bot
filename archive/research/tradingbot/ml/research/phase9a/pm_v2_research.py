"""Phase 9A — Position Management v2 research profiles and backtest helpers."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.adapters.risk_gate import (
    PositionManagementProfile,
    detect_account_tier,
    phase52a_position_management_profile,
    position_management_profile_for_tier,
)

BASELINE_36A_30D = {"pf": 2.391, "expectancy_r": 0.467, "max_dd_r": 2.14}
BASELINE_52A_30D = {"pf": 2.072, "expectancy_r": 0.281, "max_dd_r": 2.21}

PM_V2_VARIANTS: dict[str, dict[str, float | int]] = {
    "V1": {"be": 1.0, "partial": 1.2, "trail_atr": 1.0, "time_stop": 16},
    "V2": {"be": 1.0, "partial": 1.3, "trail_atr": 1.0, "time_stop": 18},
    "V3": {"be": 0.9, "partial": 1.2, "trail_atr": 0.9, "time_stop": 16},
}


def profile_for_mode(mode: str) -> PositionManagementProfile:
    m = str(mode or "").lower()
    if m == "52a":
        return phase52a_position_management_profile()
    if m.upper() in PM_V2_VARIANTS:
        return profile_for_variant(m.upper())
    tier = detect_account_tier(1000.0)
    return position_management_profile_for_tier(tier)


def profile_for_variant(name: str) -> PositionManagementProfile:
    spec = PM_V2_VARIANTS[name]
    base = position_management_profile_for_tier(detect_account_tier(1000.0))
    return PositionManagementProfile(
        breakeven_enabled=base.breakeven_enabled,
        partial_close_enabled=base.partial_close_enabled,
        atr_trailing_enabled=base.atr_trailing_enabled,
        time_exit_enabled=base.time_exit_enabled,
        breakeven_trigger_r=float(spec["be"]),
        partial_trigger_r=float(spec["partial"]),
        trailing_trigger_r=float(spec["partial"]),
        trailing_atr_multiplier=float(spec["trail_atr"]),
        trailing_min_pips=0.0,
        trailing_requires_partial=False,
        stagnation_bars_limit=int(spec["time_stop"]),
        stagnation_min_profit_r=base.stagnation_min_profit_r,
        partial_fraction=base.partial_fraction,
    )


def _pf_num(pf: Any) -> float:
    if pf in ("inf", float("inf")):
        return 999.0
    return float(pf)


@dataclass
class SimTrade:
    r_multiple: float
    entry_time: Any
    exit_time: Any
    exit_bar_index: int
    hold_bars: int = 1
    exit_reason: str = ""


def _r_list(trades: list[Any]) -> list[float]:
    out: list[float] = []
    for t in trades:
        if hasattr(t, "r_multiple"):
            out.append(float(t.r_multiple))
        else:
            out.append(float(t["r_multiple"]))
    return out


def trade_metrics(trades: list[Any], *, initial_balance: float = 1000.0) -> dict[str, Any]:
    if not trades:
        return {
            "trades": 0,
            "win_rate_pct": 0.0,
            "pf": 0.0,
            "expectancy_r": 0.0,
            "average_r": 0.0,
            "max_dd_r": 0.0,
            "average_hold_bars": 0.0,
        }
    rs = _r_list(trades)
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    gw, gl = sum(wins), abs(sum(losses))
    pf = gw / gl if gl > 0 else (999.0 if gw > 0 else 0.0)
    eq = peak = mdd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    holds: list[int] = []
    for t in trades:
        if hasattr(t, "hold_bars"):
            holds.append(max(1, int(t.hold_bars)))
            continue
        try:
            et = pd.Timestamp(t.entry_time)
            xt = pd.Timestamp(t.exit_time)
            holds.append(max(1, int(round((xt - et).total_seconds() / 300))))
        except Exception:
            holds.append(1)
    pf_out = round(pf, 3) if pf != 999.0 else "inf"
    avg_r = round(sum(rs) / len(rs), 3)
    return {
        "trades": len(trades),
        "win_rate_pct": round(len(wins) / len(rs) * 100, 2),
        "pf": pf_out,
        "expectancy_r": avg_r,
        "average_r": avg_r,
        "max_dd_r": round(mdd, 2),
        "average_hold_bars": round(sum(holds) / len(holds), 1),
    }


def monte_carlo(
    trades: list[Any],
    *,
    simulations: int = 500,
    seed: int = 42,
) -> dict[str, Any]:
    rs = np.asarray(_r_list(trades), dtype=float)
    if len(rs) < 5:
        return {"simulations": 0, "pf_median": 0.0, "exp_median": 0.0, "worst_5pct_dd_r": 0.0}
    rng = np.random.default_rng(seed)
    pfs: list[float] = []
    exps: list[float] = []
    dds: list[float] = []
    for _ in range(simulations):
        sample = rng.choice(rs, size=len(rs), replace=True)
        wins = sample[sample > 0]
        losses = sample[sample < 0]
        gw, gl = float(wins.sum()), abs(float(losses.sum()))
        pf = gw / gl if gl > 0 else (999.0 if gw > 0 else 0.0)
        pfs.append(min(pf, 50.0))
        exps.append(float(sample.mean()))
        eq = peak = mdd = 0.0
        for r in sample:
            eq += r
            peak = max(peak, eq)
            mdd = max(mdd, peak - eq)
        dds.append(mdd)
    return {
        "simulations": simulations,
        "pf_median": round(float(np.median(pfs)), 3),
        "pf_p5": round(float(np.percentile(pfs, 5)), 3),
        "pf_p95": round(float(np.percentile(pfs, 95)), 3),
        "exp_median": round(float(np.median(exps)), 3),
        "worst_5pct_dd_r": round(float(np.percentile(dds, 95)), 2),
    }


def passes_acceptance(candidate: dict[str, Any], baseline: dict[str, Any]) -> bool:
    return (
        _pf_num(candidate["pf"]) >= _pf_num(baseline["pf"])
        and float(candidate["expectancy_r"]) >= float(baseline["expectancy_r"]) + 0.05
        and float(candidate["max_dd_r"]) <= float(baseline["max_dd_r"]) + 0.5
        and float(candidate["average_r"]) > float(baseline["average_r"])
    )


def load_window_frame(days: int, *, warmup: int = 500) -> pd.DataFrame:
    from tradingbot.backtest.config import BacktestConfig
    from tradingbot.backtest.data_source import BacktestMarketData
    from tradingbot.ml.research.phase27l.exit_trace import prepare_indicator_frame

    cfg = BacktestConfig(
        symbols=["XAUUSD"],
        timeframe="M5",
        days=days + 3,
        warmup=warmup,
        use_cache=True,
    )
    md = BacktestMarketData(cfg)
    md.load()
    df = md.frame("XAUUSD")
    if df is None or df.empty:
        raise RuntimeError(f"No cached XAUUSD M5 data for {days}d window")
    return prepare_indicator_frame(df)


def _score_m5(meta, signal, snapshot, regime: str, spread: float = 4.0) -> float:
    tf = "M5"
    model = meta._models.get(tf)
    names = meta._features.get(tf)
    if model is None or not names:
        return 1.0
    feats = meta.build_features(signal, snapshot, regime, spread_pips=spread)
    row = [feats.get(n, 0.0) for n in names]
    try:
        proba = model.predict_proba([row])[0]
        return float(proba[1]) if len(proba) > 1 else float(proba[0])
    except Exception:
        return 1.0


def _map_trade_to_index(df: pd.DataFrame, bar_time: str) -> int | None:
    ts = pd.to_datetime(bar_time, utc=True)
    if df.index.tz is None:
        ts = ts.tz_localize(None) if ts.tzinfo else ts
    loc = int(df.index.searchsorted(ts, side="right")) - 1
    if loc < 0 or loc >= len(df):
        return None
    delta = abs((pd.Timestamp(df.index[loc]) - pd.Timestamp(ts)).total_seconds())
    return loc if delta <= 300 else None


def _candidates_from_pa_trades_json(
    df: pd.DataFrame,
    path: Any,
    *,
    meta_threshold: float,
) -> list[dict[str, Any]]:
    import json
    from pathlib import Path

    from tradingbot.domain.enums import SignalDirection
    from tradingbot.domain.models import TradingSignal
    from tradingbot.services.meta_labeler import get_meta_labeler

    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    meta = get_meta_labeler()
    candidates: list[dict[str, Any]] = []

    for t in raw:
        idx = _map_trade_to_index(df, str(t["bar_time"]))
        if idx is None:
            continue
        direction = SignalDirection.BUY if t["direction"] == "BUY" else SignalDirection.SELL
        sig = TradingSignal(
            direction=direction,
            confidence=float(t.get("confidence", 0.55)),
            symbol="XAUUSD",
            timeframe="5m",
            strategy_name="priceaction",
            stop_loss=float(t["stop_loss"]),
            take_profit=float(t.get("take_profit") or 0),
            metadata={
                "entry": t["entry"],
                "price": t["entry"],
                "confidence": t.get("confidence"),
                "confluence": t.get("confluence", 0),
                "setup": t.get("setup"),
            },
        )
        window = df.iloc[: idx + 1]
        ts_py = pd.Timestamp(df.index[idx]).to_pydatetime()
        snapshot = {"ohlcv": window, "htf_bias": 0, "current_time": ts_py}
        prob = _score_m5(meta, sig, snapshot, "RANGING")
        if prob < meta_threshold:
            continue
        candidates.append({
            "bar_index": idx,
            "bar_time": str(df.index[idx]),
            "direction": t["direction"],
            "entry": float(t["entry"]),
            "stop_loss": float(t["stop_loss"]),
            "take_profit": float(t.get("take_profit") or 0),
            "meta_prob": round(prob, 4),
        })
    return candidates


def collect_pa_meta_candidates(
    df: pd.DataFrame,
    *,
    meta_threshold: float = 0.38,
    pa_trades_json: Any | None = None,
    days: int | None = None,
) -> list[dict[str, Any]]:
    """PA setups scored with meta at entry bar (no cooldown — applied during PM replay)."""
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[4]
    if days is not None:
        cache = root / "logs" / f"phase9a_candidates_{days}d.json"
        if cache.is_file():
            return json.loads(cache.read_text(encoding="utf-8"))

    cache_path = pa_trades_json or root / "logs" / "phase5a_pa_trades.json"
    if pa_trades_json is not None and Path(cache_path).is_file():
        candidates = _candidates_from_pa_trades_json(df, cache_path, meta_threshold=meta_threshold)
        if candidates:
            return candidates

    from tradingbot.config.price_action import get_price_action_config
    from tradingbot.domain.enums import SignalDirection
    from tradingbot.domain.filter_policy import aligned_session_hours, strategy_uses_kill_zone
    from tradingbot.domain.gold_strategies import evaluate_gold_setup
    from tradingbot.domain.models import TradingSignal
    from tradingbot.domain.price_action import enrich_price_action
    from tradingbot.domain.session_logic import is_kill_zone
    from tradingbot.services.meta_labeler import get_meta_labeler

    cfg = get_price_action_config("XAUUSD", "M5")
    min_conf = float(cfg.get("MIN_CONFIDENCE", 0.52))
    s0, s1 = aligned_session_hours(cfg)
    use_kz = strategy_uses_kill_zone(cfg)
    warmup = 500
    meta = get_meta_labeler()
    candidates: list[dict[str, Any]] = []

    for i in range(max(warmup, 60), len(df)):
        ts = df.index[i]
        ts_py = pd.Timestamp(ts).to_pydatetime()
        if not (s0 <= ts_py.hour < s1):
            continue
        if use_kz and not is_kill_zone(ts_py, use_kill_zones=True):
            continue

        window = df.iloc[: i + 1]
        enriched = enrich_price_action(window, cfg, at_index=i)
        setup = evaluate_gold_setup(enriched, i, cfg, timeframe="5m")
        if setup is None or setup.confidence < min_conf:
            continue

        direction = SignalDirection.BUY if setup.direction > 0 else SignalDirection.SELL
        sig = TradingSignal(
            direction=direction,
            confidence=float(setup.confidence),
            symbol="XAUUSD",
            timeframe="5m",
            strategy_name="priceaction",
            stop_loss=float(setup.stop_loss),
            take_profit=float(setup.take_profit),
            metadata={
                "entry": setup.entry,
                "price": setup.entry,
                "confidence": setup.confidence,
                "confluence": setup.confluence,
                "setup": setup.setup.value,
            },
        )
        snapshot = {
            "ohlcv": window,
            "htf_bias": 0,
            "current_time": ts_py,
        }
        prob = _score_m5(meta, sig, snapshot, "RANGING")
        if prob < meta_threshold:
            continue

        candidates.append({
            "bar_index": i,
            "bar_time": str(ts),
            "direction": "BUY" if setup.direction > 0 else "SELL",
            "entry": float(setup.entry),
            "stop_loss": float(setup.stop_loss),
            "take_profit": float(setup.take_profit),
            "meta_prob": round(prob, 4),
        })
    if days is not None:
        cache = root / "logs" / f"phase9a_candidates_{days}d.json"
        cache.write_text(json.dumps(candidates, indent=2), encoding="utf-8")
    return candidates


def _bar_atr(bar: pd.Series, pip: float) -> float:
    for col in ("atr", "ATR", "atr_14"):
        if col in bar.index:
            try:
                val = float(bar[col])
                if val > 0:
                    return val
            except Exception:
                pass
    return max(float(bar["high"]) - float(bar["low"]), pip * 10)


def simulate_pm_entry(
    candidate: dict[str, Any],
    df: pd.DataFrame,
    profile: PositionManagementProfile,
    *,
    spread_pips: float = 4.0,
    slippage_pips: float = 1.0,
    min_lot: float = 0.01,
) -> SimTrade | None:
    from tradingbot.domain.position_logic import contract_size, pip_size, trailing_improves
    from tradingbot.domain.professional_pm import (
        atr_trail_sl,
        breakeven_sl,
        current_r,
        partial_close_volume,
        should_breakeven,
        should_partial,
        should_time_stop,
        should_trail,
    )
    from tradingbot.domain.trade_features import r_multiple

    start = int(candidate["bar_index"])
    is_buy = candidate["direction"] == "BUY"
    symbol = "XAUUSD"
    pip = pip_size(symbol)
    entry = float(candidate["entry"])
    sl = float(candidate["stop_loss"])
    tp = float(candidate.get("take_profit") or 0.0)
    entry_sl = sl
    risk = abs(entry - sl)
    if risk <= 0:
        return None

    volume = min_lot
    original_volume = volume
    slip = slippage_pips * pip
    current_sl = sl
    pm_bars = 0
    be_done = partial_done = False
    realized = 0.0
    entry_time = df.index[start]
    cs = contract_size(symbol)
    mult = 1 if is_buy else -1

    def _finalize(exit_price: float, exit_bar: int, reason: str) -> SimTrade:
        pnl_rem = (exit_price - entry) * mult * cs * volume
        total_pnl = realized + pnl_rem
        r_mult = r_multiple(total_pnl, entry, entry_sl, original_volume, symbol, is_buy)
        return SimTrade(
            r_multiple=round(r_mult, 4),
            entry_time=entry_time,
            exit_time=df.index[exit_bar],
            exit_bar_index=exit_bar,
            hold_bars=max(1, exit_bar - start),
            exit_reason=reason,
        )

    for j in range(start + 1, len(df)):
        bar = df.iloc[j]
        pm_bars += 1
        high = float(bar["high"])
        low = float(bar["low"])
        close = float(bar["close"])

        exit_price: float | None = None
        exit_reason: str | None = None
        if is_buy:
            if current_sl > 0 and low <= current_sl:
                exit_price = current_sl - slip
                exit_reason = "sl"
            elif tp > 0 and high >= tp:
                exit_price = tp - slip
                exit_reason = "tp"
        else:
            if current_sl > 0 and high >= current_sl:
                exit_price = current_sl + slip
                exit_reason = "sl"
            elif tp > 0 and low <= tp:
                exit_price = tp + slip
                exit_reason = "tp"
        if exit_price is not None and exit_reason is not None:
            return _finalize(exit_price, j, exit_reason)

        cur_r = current_r(is_buy=is_buy, entry=entry, price=close, risk=risk)

        if profile.time_exit_enabled and should_time_stop(
            bars_since_open=pm_bars,
            current_r=cur_r,
            bars_limit=profile.stagnation_bars_limit,
            min_profit_r=profile.stagnation_min_profit_r,
        ):
            return _finalize(close, j, "time_stop")

        if profile.breakeven_enabled and should_breakeven(
            current_r=cur_r,
            trigger_r=profile.breakeven_trigger_r,
            done=be_done,
        ):
            spread = spread_pips * pip
            new_sl = breakeven_sl(is_buy=is_buy, entry=entry, spread=spread)
            if trailing_improves(is_buy, current_sl, new_sl):
                current_sl = new_sl
                be_done = True

        if profile.partial_close_enabled and should_partial(
            current_r=cur_r,
            trigger_r=profile.partial_trigger_r,
            done=partial_done,
        ):
            close_vol = partial_close_volume(
                volume, fraction=profile.partial_fraction, min_lot=min_lot
            )
            if close_vol > 0:
                realized += (close - entry) * mult * cs * close_vol
                volume = round(volume - close_vol, 2)
                partial_done = True
                if volume <= 0:
                    r_mult = r_multiple(realized, entry, entry_sl, original_volume, symbol, is_buy)
                    return SimTrade(
                        r_multiple=round(r_mult, 4),
                        entry_time=entry_time,
                        exit_time=df.index[j],
                        exit_bar_index=j,
                        hold_bars=max(1, j - start),
                        exit_reason="partial_full",
                    )

        if profile.atr_trailing_enabled and should_trail(
            current_r=cur_r,
            trigger_r=profile.trailing_trigger_r,
            partial_done=partial_done,
            requires_partial=profile.trailing_requires_partial,
        ):
            atr = _bar_atr(bar, pip)
            new_sl = atr_trail_sl(
                is_buy=is_buy,
                current_price=close,
                original_sl=current_sl,
                atr=atr,
                pip=pip,
                atr_multiplier=profile.trailing_atr_multiplier,
                min_pips=profile.trailing_min_pips,
            )
            if new_sl is not None:
                current_sl = new_sl

    last = len(df) - 1
    return _finalize(float(df.iloc[last]["close"]), last, "end")


def run_pm_replay(
    candidates: list[dict[str, Any]],
    df: pd.DataFrame,
    mode: str,
    *,
    cooldown_bars: int = 18,
    max_trades_per_day: int = 3,
) -> list[SimTrade]:
    profile = profile_for_mode(mode)
    trades: list[SimTrade] = []
    last_entry = -9999
    open_until = -1
    day_counts: dict[str, int] = {}

    for cand in sorted(candidates, key=lambda c: c["bar_index"]):
        i = int(cand["bar_index"])
        if i <= open_until or i - last_entry < cooldown_bars:
            continue
        day = str(pd.Timestamp(df.index[i]).date())
        if day_counts.get(day, 0) >= max_trades_per_day:
            continue
        sim = simulate_pm_entry(cand, df, profile)
        if sim is None:
            continue
        trades.append(sim)
        open_until = sim.exit_bar_index
        last_entry = i
        day_counts[day] = day_counts.get(day, 0) + 1
    return trades


def run_replay_window(days: int, mode: str, df: pd.DataFrame, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    raw = run_pm_replay(candidates, df, mode)
    metrics = trade_metrics(raw)
    metrics["pm_mode"] = mode
    metrics["days"] = days
    metrics["trades_raw"] = raw
    return metrics


@contextmanager
def pm_research_patch():
    """Extend BacktestPositionManager for v1/v2/v3 modes (research only)."""
    from tradingbot.backtest import position_manager as pm_mod

    custom = {k.lower(): profile_for_variant(k) for k in PM_V2_VARIANTS}
    orig_resolve = pm_mod.BacktestPositionManager._resolve_pm_profile
    orig_manage = pm_mod.BacktestPositionManager.manage_all

    def _resolve(self, mode: str):
        if mode in custom:
            return custom[mode]
        return orig_resolve(self, mode)

    def _manage_all(self):
        for pos in list(self._broker.open_positions):
            bar = self._data.current_bar(pos.symbol)
            if bar is None:
                continue
            price = float(bar["close"])
            is_buy = pos.is_buy
            self._tick_pm_bar(pos)
            if self._cfg.friday_close_enabled and self._friday_close(pos, price):
                continue
            if self._cfg.enable_eod_close and self._eod_close(pos, price):
                continue
            if self._cfg.enable_emergency and self._emergency(pos, price, is_buy):
                continue
            mode = str(getattr(self._cfg, "position_management_mode", "legacy") or "legacy").lower()
            if mode in ("36a", "52a", "v1", "v2", "v3") and self._is_xauusd(pos.symbol):
                if self._manage_xauusd_pm(pos, bar, price, is_buy, mode):
                    continue
                continue
            if self._cfg.enable_partial_tp and self._partial_tp(pos, price, is_buy):
                if pos.volume <= 0:
                    continue
            if self._cfg.enable_trailing:
                self._trailing(pos, bar, price, is_buy)

    pm_mod.BacktestPositionManager._resolve_pm_profile = _resolve  # type: ignore[method-assign]
    pm_mod.BacktestPositionManager.manage_all = _manage_all  # type: ignore[method-assign]
    try:
        yield
    finally:
        pm_mod.BacktestPositionManager._resolve_pm_profile = orig_resolve  # type: ignore[method-assign]
        pm_mod.BacktestPositionManager.manage_all = orig_manage  # type: ignore[method-assign]


@contextmanager
def fixed_meta_threshold(threshold: float = 0.38):
    from tradingbot.services.meta_labeler import MetaLabeler

    orig_eff = MetaLabeler.effective_threshold
    orig_cal = MetaLabeler.calibrated_threshold
    MetaLabeler.calibrated_threshold = lambda self, timeframe: None  # type: ignore[method-assign]
    MetaLabeler.effective_threshold = (  # type: ignore[method-assign]
        lambda self, timeframe, regime, base_threshold: float(threshold)
    )
    try:
        yield
    finally:
        MetaLabeler.effective_threshold = orig_eff
        MetaLabeler.calibrated_threshold = orig_cal


async def run_pm_backtest(days: int, pm_mode: str) -> dict[str, Any]:
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.adapters.legacy_strategy_registry import LegacyStrategyRegistry
    from tradingbot.backtest.config import BacktestConfig
    from tradingbot.backtest.engine import BacktestEngine
    from tradingbot.services.meta_labeler import reload_meta_labeler

    reload_meta_labeler()
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
        use_cache=True,
        position_management_mode=pm_mode,
    )
    legacy = load_legacy_config()
    pa_reg = LegacyStrategyRegistry(legacy)
    with fixed_meta_threshold(0.38):
        engine = BacktestEngine(cfg, legacy, quiet=True, strategies=pa_reg)
        engine._htf.load = lambda: None  # type: ignore[method-assign]
        engine._htf.needs_htf = lambda: False  # type: ignore[method-assign]
        pre_len = engine._data.load()
        if pre_len <= cfg.warmup + 1:
            raise RuntimeError(f"Insufficient bars ({pre_len}) for {days}d")
        result = await engine.run()
    metrics = trade_metrics(result.trades, initial_balance=cfg.initial_balance)
    metrics["pm_mode"] = pm_mode
    metrics["days"] = days
    metrics["trades_raw"] = result.trades
    return metrics


async def run_full_matrix(windows: tuple[int, ...] = (30, 60, 90)) -> dict[str, Any]:
    matrix: list[dict[str, Any]] = []
    baselines: dict[int, dict[str, Any]] = {}
    window_frames: dict[int, pd.DataFrame] = {}
    window_candidates: dict[int, list[dict[str, Any]]] = {}

    for days in windows:
        print(f"  load {days}d cache + PA/meta candidates ...", flush=True)
        df = load_window_frame(days)
        candidates = collect_pa_meta_candidates(df, meta_threshold=0.38, days=days)
        window_frames[days] = df
        window_candidates[days] = candidates
        print(f"    {days}d: {len(df)} bars, {len(candidates)} meta-pass candidates", flush=True)

    modes = ["36a", "52a", *[k.lower() for k in PM_V2_VARIANTS]]
    for days in windows:
        df = window_frames[days]
        candidates = window_candidates[days]
        for mode in modes:
            label = mode.upper() if mode in ("36a", "52a") else mode.upper()
            if mode == "36a":
                label = "36A"
            elif mode == "52a":
                label = "52A"
            print(f"  replay {label} @{days}d ...", flush=True)
            res = run_replay_window(days, mode, df, candidates)
            if mode == "36a":
                baselines[days] = res
            row = {k: v for k, v in res.items() if k != "trades_raw"}
            row["variant"] = label
            row["window_days"] = days
            if label in PM_V2_VARIANTS:
                base = baselines[days]
                row["accepted_vs_36a"] = passes_acceptance(res, base)
                row["baseline_pf"] = base["pf"]
                row["baseline_exp_r"] = base["expectancy_r"]
                row["baseline_max_dd_r"] = base["max_dd_r"]
            matrix.append(row)
            print(
                f"    {label}: trades={res['trades']} PF={res['pf']} ExpR={res['expectancy_r']} "
                f"MaxDD={res['max_dd_r']}R",
                flush=True,
            )

    best_name = None
    best_score = (-1, -1.0, -999.0)
    deployable_variants: set[str] = set()
    for vname in PM_V2_VARIANTS:
        passes_all = all(
            passes_acceptance(
                next(r for r in matrix if r["variant"] == vname and r["window_days"] == d),
                baselines[d],
            )
            for d in windows
        )
        if passes_all:
            deployable_variants.add(vname)
        agg_pf = np.mean([
            _pf_num(next(r for r in matrix if r["variant"] == vname and r["window_days"] == d)["pf"])
            for d in windows
        ])
        agg_exp = np.mean([
            float(next(r for r in matrix if r["variant"] == vname and r["window_days"] == d)["expectancy_r"])
            for d in windows
        ])
        rank = (1 if passes_all else 0, agg_pf, agg_exp)
        if rank > best_score:
            best_score = rank
            best_name = vname

    if best_name is None:
        best_name = "V1"

    best_90 = next(r for r in matrix if r["variant"] == best_name and r["window_days"] == 90)
    raw90 = run_pm_replay(
        window_candidates[90],
        window_frames[90],
        best_name.lower(),
    )
    mc = monte_carlo(raw90, simulations=500)

    return {
        "matrix": matrix,
        "baselines": {str(k): {kk: vv for kk, vv in v.items() if kk != "trades_raw"} for k, v in baselines.items()},
        "best_variant": best_name,
        "deployable_variants": sorted(deployable_variants),
        "monte_carlo_90d_best": mc,
        "best_90d_metrics": {k: v for k, v in best_90.items() if k not in ("trades_raw",)},
        "pm_v2_deployable": bool(deployable_variants),
        "method": "PM bar-replay on PA+Meta 0.38 entries (cached M5, production PM helpers)",
    }

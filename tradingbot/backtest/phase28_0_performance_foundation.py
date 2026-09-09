"""Phase 28.0 — GoldenEdge performance foundation.

RESEARCH ONLY. Does not authorize live trading, weaken COMPLETE_COSTS_REQUIRED,
change strategy/RiskGate/sizing/RR/ML, start MT5, or rewrite parquet.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from engine.strategies.price_action_strategy import PriceActionStrategy
from tradingbot.adapters.legacy_loader import load_legacy_config
from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.dataset_contract import STATUS_MATCH, STATUS_MISSING_MAP, classify_dataset_binding
from tradingbot.backtest.dataset_provenance import (
    audit_backtest_datasets,
    load_dataset_metadata,
    metadata_path_for,
)
from tradingbot.backtest.engine import BacktestEngine
from tradingbot.backtest.instrument import OFFLINE_INSTRUMENT_CATALOG, merge_broker_catalog
from tradingbot.backtest.phase25h_run import build_immutability_manifest, verify_immutability
from tradingbot.backtest.phase26b_controlled_validation import build_frozen_baseline_configuration
from tradingbot.backtest.phase26c_zero_signal_audit import WARMUP, _append_forming_bar_m5, _enrich_frame
from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_30_slippage_evidence import file_fingerprint
from tradingbot.config.live import PRIMARY_SYMBOL
from tradingbot.config.pa_symbol_tf_presets import PA_SYMBOL_TF_PRESETS
from tradingbot.config.price_action import apply_pa_to_legacy, get_price_action_config
from tradingbot.domain.enums import PipelineStageName
from tradingbot.domain.gold_strategies.m5_london_sweep import m5_ny_entry_hours
from tradingbot.domain.models import CycleContext, MarketKey
from tradingbot.domain.ohlcv import exclude_forming_bar
from tradingbot.domain.pa_hardening import clear_pa_dedup_cache

PHASE = "28.0"
PHASE280_MANIFEST_JSON = "logs/phase28_0_performance_dataset_manifest.json"
PHASE280_BASELINE_JSON = "logs/phase28_0_baseline_performance.json"
PHASE280_MD = "docs_v2/02_research/PHASE28_0_PERFORMANCE_FOUNDATION.md"
CANONICAL_PARQUET = "data/XAUUSD_i_5m.parquet"
H4_CONTEXT_PARQUET = "data/XAUUSD_i_4h.parquet"
EXPECTED_CANONICAL_FINGERPRINT = "ab3e25bab0c6d6689d6654317264cc7774e1b49f88df907a3ea1bd1ade313ed5"
UNKNOWN = "UNKNOWN"
BLOCKED = "BLOCKED"
MIN_RESOLVED_FOR_SUFFICIENCY = 30
MIN_CALENDAR_DAYS_FOR_SUFFICIENCY = 60
TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "H1": 60, "H4": 240, "D1": 1440}

REQUIRED_MANIFEST_KEYS = (
    "phase",
    "timestamp_utc",
    "research_only",
    "live_trading_authorized",
    "best_dataset",
    "inventory",
    "evidence_backed",
    "blocked",
    "canonical_audit",
    "FINAL_GATE",
    "ev_eq_01",
    "cost_completeness",
    "datasets_changed",
)

REQUIRED_BASELINE_KEYS = (
    "phase",
    "timestamp_utc",
    "research_only",
    "live_trading_authorized",
    "best_dataset",
    "dataset_fingerprint",
    "research_configuration",
    "lookahead",
    "raw_signal_results",
    "executable_results",
    "statistical_sufficiency",
    "conclusion",
    "FINAL_GATE",
    "deterministic_reproducibility",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_head(base_dir: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=base_dir,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return UNKNOWN


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def _rel(root: Path, path: str | Path) -> str:
    p = Path(path)
    try:
        return p.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return p.as_posix().replace("\\", "/")


def load_parquet_utc(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    if not isinstance(df.index, pd.DatetimeIndex):
        if "time" in df.columns:
            df = df.set_index(pd.to_datetime(df["time"], utc=True))
        elif "timestamp" in df.columns:
            df = df.set_index(pd.to_datetime(df["timestamp"], utc=True))
        else:
            raise ValueError(f"no datetime index/column in {path}")
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    return df.sort_index()


def audit_ohlc_quality(df: pd.DataFrame, *, timeframe: str | None) -> dict[str, Any]:
    if df.empty:
        return {
            "row_count": 0,
            "duplicate_timestamps": 0,
            "malformed_ohlc": 0,
            "impossible_candles": 0,
            "zero_volume": 0,
            "negative_volume": 0,
            "gap_count": 0,
            "weekend_or_session_gaps": 0,
            "weekday_unexpected_gaps": 0,
            "timezone": UNKNOWN,
        }
    o = df["open"].astype(float)
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    c = df["close"].astype(float)
    body_max = pd.concat([o, c], axis=1).max(axis=1)
    body_min = pd.concat([o, c], axis=1).min(axis=1)
    high_below_body = h < body_max
    low_above_body = l > body_min
    impossible = (h < l) | high_below_body | low_above_body
    malformed = (h < l) | high_below_body | low_above_body | (o <= 0) | (h <= 0) | (l <= 0) | (c <= 0)
    vol = df["volume"].astype(float) if "volume" in df.columns else None
    minutes = TF_MINUTES.get(str(timeframe or "").upper(), 5)
    expected = pd.Timedelta(minutes=minutes)
    deltas = df.index.to_series().diff()
    gap_mask = deltas > expected
    weekend_gaps = 0
    weekday_gaps = 0
    gap_examples: list[dict[str, Any]] = []
    for ts, delta in deltas[gap_mask].items():
        prev = ts - delta
        minutes = float(delta.total_seconds() / 60.0)
        is_daily_rollover = 50.0 <= minutes <= 90.0
        is_weekend = minutes >= 24.0 * 60.0
        is_weekendish = is_daily_rollover or is_weekend or (int(prev.weekday()) >= 4 and int(ts.weekday()) <= 1)
        if is_weekendish:
            weekend_gaps += 1
        else:
            weekday_gaps += 1
        if len(gap_examples) < 12:
            gap_examples.append(
                {
                    "from": str(prev),
                    "to": str(ts),
                    "delta_minutes": float(delta.total_seconds() / 60.0),
                    "weekend_or_session_break": is_weekendish,
                }
            )
    tz = str(df.index.tz) if df.index.tz is not None else "naive"
    return {
        "row_count": int(len(df)),
        "start": str(df.index[0]),
        "end": str(df.index[-1]),
        "timezone": tz,
        "duplicate_timestamps": int(df.index.duplicated().sum()),
        "malformed_ohlc": int(malformed.sum()),
        "impossible_candles": int(impossible.sum()),
        "zero_volume": int((vol == 0).sum()) if vol is not None else UNKNOWN,
        "negative_volume": int((vol < 0).sum()) if vol is not None else UNKNOWN,
        "gap_count": int(gap_mask.sum()),
        "weekend_or_session_gaps": weekend_gaps,
        "weekday_unexpected_gaps": weekday_gaps,
        "gap_examples": gap_examples,
        "ohlc_present": all(col in df.columns for col in ("open", "high", "low", "close")),
        "volume_present": "volume" in df.columns,
        "bid_present": any(c.lower() in {"bid", "bid_price"} for c in df.columns),
        "ask_present": any(c.lower() in {"ask", "ask_price"} for c in df.columns),
        "spread_column_present": any(c.lower() in {"spread", "tick_spread"} for c in df.columns),
    }


def _timeframe_from_filename(filename: str, inferred: str | None) -> str | None:
    if inferred:
        return str(inferred).upper()
    stem = Path(filename).stem.upper()
    aliases = (
        ("_15M", "M15"),
        ("_5M", "M5"),
        ("_4H", "H4"),
        ("_1H", "H1"),
        ("_1D", "D1"),
        ("_M15", "M15"),
        ("_M5", "M5"),
        ("_H4", "H4"),
    )
    for suffix, tf in aliases:
        if stem.endswith(suffix) or suffix + "_" in stem:
            return tf
    return None


def classify_performance_eligibility(
    *,
    inferred_symbol: str | None,
    inferred_timeframe: str | None,
    binding_status: str,
    blocked: bool,
    ohlc_present: bool,
) -> str:
    if not ohlc_present:
        return "INELIGIBLE_NO_OHLC"
    if inferred_symbol == "XAUUSD" and binding_status == STATUS_MISSING_MAP:
        return "BLOCKED_MISSING_EXPLICIT_MAP"
    if blocked or binding_status not in {STATUS_MATCH}:
        if inferred_symbol == "XAUUSD":
            return "BLOCKED_MISSING_EXPLICIT_MAP"
        return "BLOCKED_NOT_CANONICAL"
    if inferred_symbol != PRIMARY_SYMBOL:
        return "BLOCKED_NOT_CANONICAL"
    tf = str(inferred_timeframe or "").upper()
    if tf == "M5":
        return "ELIGIBLE_ENTRY"
    if tf in {"H4", "M15"}:
        return "ELIGIBLE_CONTEXT"
    if tf:
        return "ELIGIBLE_OTHER_TF"
    return "ELIGIBLE_UNKNOWN_TF"


def build_research_configuration() -> dict[str, Any]:
    """Current strategy/RiskGate/sizing/session/SL-TP — no optimization, no ZERO commission, no dataset map."""
    frozen = dict(build_frozen_baseline_configuration())
    m5 = dict(PA_SYMBOL_TF_PRESETS["XAUUSD"]["M5"])
    cfg = BacktestConfig()
    research = {
        "phase": PHASE,
        "research_only": True,
        "live_trading_authorized": False,
        "parameters_optimized": False,
        "strategy_changed": False,
        "riskgate_changed": False,
        "sizing_changed": False,
        "rr_changed": False,
        "ml_changed": False,
        "validation_class": "PHASE28_0_RESEARCH_ONLY",
        "configured_instrument_symbol": PRIMARY_SYMBOL,
        "dataset_symbol_map_explicit": {},
        "dataset_symbol_map_note": (
            "EMPTY map. Logical XAUUSD datasets remain BLOCKED. "
            "PA normalize_symbol(XAUUSD_i)→XAUUSD is live preset aliasing, not a dataset bind. "
            "EV-EQ-01 remains NOT_PROVEN."
        ),
        "symbol": PRIMARY_SYMBOL,
        "data_symbol_label": PRIMARY_SYMBOL,
        "timeframe": "M5",
        "context_timeframes": {"H4": "bias/context", "M15": "context_if_available", "M5": "entry"},
        "strategy_mode": m5.get("PRESET"),
        "gold_strategy_mode": m5.get("GOLD_STRATEGY_MODE"),
        "session_filter": f"NY {m5.get('NY_ENTRY_START_HOUR')}-{m5.get('NY_ENTRY_END_HOUR')} UTC",
        "asian_end_utc": m5.get("ASIAN_END_HOUR"),
        "min_confidence": m5.get("MIN_CONFIDENCE"),
        "min_quality_score": m5.get("MIN_QUALITY_SCORE"),
        "min_rr": m5.get("MIN_RR"),
        "tp_rr": m5.get("TP_RR"),
        "sl_atr_mult": m5.get("SL_ATR_MULT"),
        "cooldown_bars": m5.get("COOLDOWN_BARS"),
        "max_trades_per_day": m5.get("MAX_TRADES_PER_DAY"),
        "risk_per_trade": cfg.risk_per_trade,
        "htf_alignment_m5": m5.get("REQUIRE_HTF_ALIGNMENT_M5"),
        "forming_bar": cfg.simulate_forming_bar,
        "meta_labeler": cfg.use_meta_labeler,
        "meta_threshold": m5.get("META_LABEL_THRESHOLD"),
        "warmup": cfg.warmup,
        "initial_balance": cfg.initial_balance,
        "commission_status": cfg.commission_status,
        "swap_status": cfg.swap_status,
        "slippage_status": cfg.slippage_status,
        "spread_mode": cfg.spread_mode,
        "spread_pips_baseline": cfg.spread_pips,
        "slippage_pips_baseline": cfg.slippage_pips,
        "note_vs_phase26b": (
            "Phase 26B used logical XAUUSD 183d + explicit research map + commission ZERO. "
            "Phase 28.0 uses XAUUSD_i only, empty map, default UNKNOWN commission."
        ),
        "inherited_live_knobs_from_phase26b_fingerprint": frozen.get("configuration_fingerprint"),
    }
    fp = hashlib.sha256(json.dumps(research, sort_keys=True, default=str).encode()).hexdigest()[:16]
    research["configuration_fingerprint"] = fp
    return research


def _build_phase28_backtest_config(research: dict[str, Any]) -> BacktestConfig:
    m5 = PA_SYMBOL_TF_PRESETS["XAUUSD"]["M5"]
    return BacktestConfig(
        symbols=[PRIMARY_SYMBOL],
        timeframe="M5",
        configured_instrument_symbol=PRIMARY_SYMBOL,
        dataset_symbol_map={},
        broker_economics={"XAUUSD_i": dict(OFFLINE_INSTRUMENT_CATALOG["XAUUSD_i"])},
        warmup=int(research.get("warmup", WARMUP)),
        initial_balance=float(research.get("initial_balance", 1000.0)),
        risk_per_trade=float(research.get("risk_per_trade", 0.005)),
        max_trades_per_day=int(m5["MAX_TRADES_PER_DAY"]),
        cooldown_bars=int(m5["COOLDOWN_BARS"]),
        min_confidence=float(m5["MIN_CONFIDENCE"]),
        require_htf_alignment_m5=bool(m5.get("REQUIRE_HTF_ALIGNMENT_M5", False)),
        simulate_forming_bar=True,
        spread_mode=str(research.get("spread_mode", "AUTO")),
        spread_pips=float(research.get("spread_pips_baseline", 2.5)),
        slippage_pips=float(research.get("slippage_pips_baseline", 0.8)),
        variable_spread=True,
        commission_status="UNKNOWN",
        slippage_status=str(research.get("slippage_status", "MODELED_PROXY")),
        swap_status=str(research.get("swap_status", "UNKNOWN")),
        use_meta_labeler=True,
        use_news_filter=True,
        max_spread_pips=5.0,
        use_cache=False,
    )


def theoretical_outcome(
    df: pd.DataFrame,
    entry_idx: int,
    direction: str,
    entry: float,
    sl: float,
    tp: float,
) -> dict[str, Any]:
    """Exits may use bars AFTER the closed signal bar only. SL-before-TP on same bar."""
    risk = abs(float(entry) - float(sl))
    buy = str(direction).upper() in {"BUY", "1", "LONG"}
    if risk <= 0:
        return {"outcome": "invalid_risk", "r_multiple": None, "exit_price": None, "exit_index": None}
    for j in range(entry_idx + 1, len(df)):
        row = df.iloc[j]
        high = float(row["high"])
        low = float(row["low"])
        if buy:
            hit_sl = low <= sl
            hit_tp = high >= tp
            if hit_sl:
                return {
                    "outcome": "loss",
                    "r_multiple": -1.0,
                    "exit_price": float(sl),
                    "exit_index": int(j),
                    "exit_time": str(df.index[j]),
                    "same_bar_sl_and_tp": bool(hit_sl and hit_tp),
                }
            if hit_tp:
                return {
                    "outcome": "win",
                    "r_multiple": float((tp - entry) / risk),
                    "exit_price": float(tp),
                    "exit_index": int(j),
                    "exit_time": str(df.index[j]),
                    "same_bar_sl_and_tp": False,
                }
        else:
            hit_sl = high >= sl
            hit_tp = low <= tp
            if hit_sl:
                return {
                    "outcome": "loss",
                    "r_multiple": -1.0,
                    "exit_price": float(sl),
                    "exit_index": int(j),
                    "exit_time": str(df.index[j]),
                    "same_bar_sl_and_tp": bool(hit_sl and hit_tp),
                }
            if hit_tp:
                return {
                    "outcome": "win",
                    "r_multiple": float((entry - tp) / risk),
                    "exit_price": float(tp),
                    "exit_index": int(j),
                    "exit_time": str(df.index[j]),
                    "same_bar_sl_and_tp": False,
                }
    return {"outcome": "open", "r_multiple": None, "exit_price": None, "exit_index": None}


def _metrics_from_r(r_values: list[float], *, calendar_days: float) -> dict[str, Any]:
    if not r_values:
        return {
            "resolved": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": None,
            "expectancy_R": None,
            "profit_factor": None,
            "max_drawdown_R": None,
            "max_consecutive_losses": 0,
            "trade_frequency": 0.0,
        }
    wins = [r for r in r_values if r > 0]
    losses = [r for r in r_values if r <= 0]
    gross_win = float(sum(wins))
    gross_loss = float(abs(sum(losses)))
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    consec = 0
    max_consec = 0
    for r in r_values:
        equity += r
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)
        if r <= 0:
            consec += 1
            max_consec = max(max_consec, consec)
        else:
            consec = 0
    pf: float | None
    if gross_loss > 0:
        pf = gross_win / gross_loss
    elif gross_win > 0:
        pf = None  # undefined / infinite — do not invent a finite PF
    else:
        pf = None
    days = max(float(calendar_days), 1.0)
    return {
        "resolved": len(r_values),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(r_values), 6),
        "expectancy_R": round(sum(r_values) / len(r_values), 6),
        "profit_factor": None if pf is None else round(pf, 6),
        "profit_factor_undefined_no_losses": bool(gross_loss == 0 and gross_win > 0),
        "max_drawdown_R": round(abs(max_dd), 6),
        "max_consecutive_losses": int(max_consec),
        "trade_frequency": round(len(r_values) / days, 6),
        "trade_frequency_unit": "resolved_trades_per_calendar_day",
    }


def scan_signal_setups(
    enriched: pd.DataFrame,
    *,
    warmup: int = WARMUP,
    symbol: str = PRIMARY_SYMBOL,
) -> list[dict[str, Any]]:
    """Closed-bar official signals. Sequential strategy state; RiskGate is not applied."""
    cfg = get_price_action_config(symbol, "M5")
    ny_s, ny_e = m5_ny_entry_hours(cfg)
    legacy = apply_pa_to_legacy(load_legacy_config(), symbol, "M5")
    clear_pa_dedup_cache()
    pa = PriceActionStrategy(legacy)
    out: list[dict[str, Any]] = []
    for cursor in range(warmup, len(enriched)):
        window = _append_forming_bar_m5(enriched.iloc[: cursor + 1])
        closed = exclude_forming_bar(window, min_rows=30)
        if closed is None or closed.empty:
            continue
        i = len(closed) - 1
        ts = closed.index[i]
        hour = int(getattr(ts, "hour", -1))
        if not (ny_s <= hour < ny_e):
            continue
        sigs = pa.generate_signals(closed, symbol=symbol, timeframe="M5")
        if not sigs:
            continue
        sig = sigs[0]
        direction = getattr(getattr(sig, "signal_type", None), "name", None) or str(
            getattr(sig, "signal_type", UNKNOWN)
        )
        meta = getattr(sig, "metadata", None) or {}
        entry = float(getattr(sig, "price", closed.iloc[i]["close"]))
        sl = float(meta.get("stop_loss") or 0.0)
        tp = float(meta.get("take_profit") or 0.0)
        # Map closed-window index i back onto the full enriched frame.
        full_idx = int(enriched.index.get_indexer([closed.index[i]], method="nearest")[0])
        result = theoretical_outcome(enriched, full_idx, direction, entry, sl, tp)
        out.append(
            {
                "timestamp": str(closed.index[i]),
                "cursor": int(cursor),
                "closed_bar_index": int(full_idx),
                "direction": direction,
                "entry_price": entry,
                "stop_loss": sl,
                "take_profit": tp,
                "planned_rr": meta.get("risk_reward_ratio"),
                "confidence": float(getattr(sig, "confidence", 0) or 0),
                "quality_score": meta.get("quality_score"),
                "setup": meta.get("setup") or meta.get("pattern"),
                "symbol": getattr(sig, "symbol", symbol),
                **result,
                "entry_timing": (
                    "Signal on last CLOSED M5 bar only. Forming bar is appended then excluded. "
                    "Entry price = strategy setup.entry from that closed bar. "
                    "Theoretical exits start at the next bar (i+1). Same-bar SL before TP."
                ),
            }
        )
    return out


def _setups_fingerprint(setups: list[dict[str, Any]]) -> str:
    key = [
        {
            "t": s.get("timestamp"),
            "d": s.get("direction"),
            "e": s.get("entry_price"),
            "sl": s.get("stop_loss"),
            "tp": s.get("take_profit"),
            "o": s.get("outcome"),
            "r": s.get("r_multiple"),
        }
        for s in setups
    ]
    return hashlib.sha256(json.dumps(key, sort_keys=True, default=str).encode()).hexdigest()


def _build_research_engine(
    enriched: pd.DataFrame,
    research: dict[str, Any],
    *,
    h4: pd.DataFrame | None = None,
) -> BacktestEngine:
    legacy = load_legacy_config()
    legacy = merge_broker_catalog(legacy, {"XAUUSD_i": dict(OFFLINE_INSTRUMENT_CATALOG["XAUUSD_i"])})
    # No dataset_symbol_map and no XAUUSD→XAUUSD_i dataset alias.
    legacy = apply_pa_to_legacy(legacy, PRIMARY_SYMBOL, "M5")
    cfg = _build_phase28_backtest_config(research)
    engine = BacktestEngine(cfg, legacy, quiet=True)
    engine._htf.load = lambda: None  # type: ignore[method-assign]
    if h4 is not None and not h4.empty:
        engine._htf._htf_df = h4
    engine._data.inject({PRIMARY_SYMBOL: enriched})
    return engine


async def _riskgate_one_candidate(engine: BacktestEngine, cand: dict[str, Any]) -> dict[str, Any]:
    """Run the real kernel through RiskGate. Do not loosen gates."""
    cursor = int(cand["cursor"])
    clear_pa_dedup_cache()
    engine._data.set_cursor(cursor)
    market = MarketKey(PRIMARY_SYMBOL, "M5")
    portfolio = engine._broker.snapshot()
    ctx = CycleContext(market=market)
    for stage in engine._kernel._pipeline:
        ok = await stage.run(ctx, portfolio)
        if stage.name.value == PipelineStageName.RISK.value:
            break
        if not ok:
            break
    risk = ctx.risk
    allowed = bool(getattr(risk, "allowed", False)) if risk is not None else False
    reason = getattr(risk, "reason", None) if risk is not None else "no_risk_evaluation"
    if ctx.signal is None and not allowed:
        reason = reason or "no_signal"
    for stage in engine._kernel._pipeline:
        if stage.name.value == PipelineStageName.SIGNALS.value and hasattr(stage, "_last_closed_bar"):
            stage._last_closed_bar.clear()
    return {
        "allowed": allowed,
        "reason": str(reason or "unknown"),
        "has_signal": ctx.signal is not None,
    }


async def evaluate_executable_edge(
    engine: BacktestEngine,
    setups: list[dict[str, Any]],
    research: dict[str, Any],
) -> dict[str, Any]:
    """Current RiskGate path. Gates are not loosened. Isolated per candidate (does not inflate 0-allow)."""
    del research  # frozen knobs already applied on engine construction
    rows: list[dict[str, Any]] = []
    reasons: Counter[str] = Counter()
    allowed = 0
    for cand in setups:
        audit = await _riskgate_one_candidate(engine, cand)
        reason = str(audit.get("reason") or "unknown")
        is_allowed = bool(audit.get("allowed"))
        if is_allowed:
            allowed += 1
            reasons["ALLOWED"] += 1
        else:
            reasons[reason] += 1
        rows.append(
            {
                "timestamp": cand.get("timestamp"),
                "cursor": cand.get("cursor"),
                "direction": cand.get("direction"),
                "allowed": is_allowed,
                "reason": reason,
                "has_signal": audit.get("has_signal"),
            }
        )
    executed = 0  # UNKNOWN commission fail-closes SimulatedBroker; no fills invented
    return {
        "candidates": len(setups),
        "allowed": allowed,
        "rejected": len(setups) - allowed,
        "rejection_reasons": dict(reasons),
        "executed_simulated_trades": executed,
        "broker_fill_note": (
            "SimulatedBroker refuses commission UNKNOWN. Default BacktestConfig.commission_status "
            "is UNKNOWN (not ZERO). Allowed RiskGate trades still do not become fills in this "
            "research config. Do not interpret 0 fills as proof of no strategy edge."
        ),
        "candidate_isolation_note": (
            "Each candidate is evaluated with a fresh RiskGate journal slice (Phase 26E style). "
            "That can only over-count allows vs a sequential book. If allowed=0, isolation cannot inflate."
        ),
        "rows": rows,
        "expectancy_R": None,
        "profit_factor": None,
        "max_drawdown_R": None,
        "win_rate": None,
        "trades": executed,
    }


def classify_statistical_sufficiency(
    *,
    resolved: int,
    calendar_days: float,
    setups: int,
) -> dict[str, Any]:
    reasons = []
    if resolved < MIN_RESOLVED_FOR_SUFFICIENCY:
        reasons.append(f"resolved_trades={resolved}<{MIN_RESOLVED_FOR_SUFFICIENCY}")
    if calendar_days < MIN_CALENDAR_DAYS_FOR_SUFFICIENCY:
        reasons.append(f"calendar_days={calendar_days:.1f}<{MIN_CALENDAR_DAYS_FOR_SUFFICIENCY}")
    if setups == 0:
        reasons.append("zero_setups_on_short_tape_is_not_no_edge")
    sufficient = len(reasons) == 0
    return {
        "classification": "SUFFICIENT" if sufficient else "DATA_INSUFFICIENT",
        "min_resolved_required": MIN_RESOLVED_FOR_SUFFICIENCY,
        "min_calendar_days_required": MIN_CALENDAR_DAYS_FOR_SUFFICIENCY,
        "resolved": resolved,
        "setups": setups,
        "calendar_days": round(calendar_days, 4),
        "reasons": reasons,
        "confidence_invented": False,
        "zero_trades_is_not_no_edge": True,
    }


def _canonical_audit(root: Path) -> dict[str, Any]:
    path = root / CANONICAL_PARQUET
    fp_before = file_fingerprint(path)
    df = load_parquet_utc(path) if path.is_file() else pd.DataFrame()
    quality = audit_ohlc_quality(df, timeframe="M5") if not df.empty else {}
    sidecar = load_dataset_metadata(path) if path.is_file() else None
    sidecar_path = metadata_path_for(path) if path.is_file() else None
    binding = classify_dataset_binding(
        PRIMARY_SYMBOL,
        configured_symbol=PRIMARY_SYMBOL,
        dataset_symbol_map={},
    )
    bid_cov = "NONE"
    if quality.get("bid_present") and quality.get("ask_present"):
        bid_cov = "HISTORICAL_BIDASK"
    elif sidecar and getattr(sidecar, "historical_bid_ask_available", False):
        bid_cov = "SIDECAR_CLAIMS_BIDASK"
    else:
        bid_cov = "PROXY_OHLC_ONLY"
    return {
        "path": CANONICAL_PARQUET,
        "exists": path.is_file(),
        "fingerprint": fp_before,
        "expected_fingerprint": EXPECTED_CANONICAL_FINGERPRINT,
        "fingerprint_match": fp_before == EXPECTED_CANONICAL_FINGERPRINT,
        "row_count": quality.get("row_count", 0),
        "date_range": {"start": quality.get("start"), "end": quality.get("end")},
        "timezone": quality.get("timezone"),
        "quality": quality,
        "bidask_coverage": bid_cov,
        "spread_coverage": (
            "DATASET"
            if bid_cov == "HISTORICAL_BIDASK"
            else (getattr(sidecar, "spread_mode", None) or "PROXY")
        ),
        "sidecar_present": bool(sidecar_path and Path(sidecar_path).is_file()),
        "sidecar_account_environment": getattr(sidecar, "account_environment", None) if sidecar else None,
        "sidecar_spread_mode": getattr(sidecar, "spread_mode", None) if sidecar else None,
        "sidecar_spread_source": getattr(sidecar, "spread_source", None) if sidecar else None,
        "mapping_status": binding.mapping_status,
        "binding_blocked": binding.blocked,
        "provenance_quality": getattr(sidecar, "provenance_summary", None)
        if sidecar
        else "filename+direct_canonical_label_only",
        "ohlc": True,
        "broker_economics": "OBSERVED_BROKER_EVIDENCE_SIDECAR_OR_OFFLINE_CATALOG",
    }


def _inventory_payload(root: Path) -> dict[str, Any]:
    entries = audit_backtest_datasets(base_dir=root, configured_symbol=PRIMARY_SYMBOL, dataset_symbol_map={})
    inventory: list[dict[str, Any]] = []
    evidence_backed: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for entry in entries:
        inferred = entry.inferred_symbol
        if inferred not in {"XAUUSD", "XAUUSD_i", None} and inferred and "XAU" not in str(inferred).upper():
            continue
        inferred_tf = _timeframe_from_filename(entry.filename, entry.inferred_timeframe)
        binding = classify_dataset_binding(
            inferred or "",
            configured_symbol=PRIMARY_SYMBOL,
            dataset_symbol_map={},
        )
        eligibility = classify_performance_eligibility(
            inferred_symbol=inferred,
            inferred_timeframe=inferred_tf,
            binding_status=binding.mapping_status,
            blocked=binding.blocked,
            ohlc_present=entry.ohlc_present,
        )
        sidecar = load_dataset_metadata(Path(entry.path))
        row = {
            "path": _rel(root, entry.path),
            "filename": entry.filename,
            "symbol": inferred,
            "timeframe": inferred_tf,
            "start": (entry.datetime_range or {}).get("start"),
            "end": (entry.datetime_range or {}).get("end"),
            "timezone": (entry.datetime_range or {}).get("timezone"),
            "row_count": entry.row_count,
            "ohlcv": {
                "ohlc": entry.ohlc_present,
                "volume": entry.volume_present,
            },
            "bid_present": entry.bid_present,
            "ask_present": entry.ask_present,
            "spread_mode": entry.spread_mode,
            "spread_source": entry.spread_source,
            "provenance": entry.economics_provenance,
            "sidecar_present": entry.metadata_sidecar_present,
            "sidecar_account_environment": getattr(sidecar, "account_environment", None) if sidecar else None,
            "broker_economics": entry.economics_fields or None,
            "fingerprint": file_fingerprint(entry.path),
            "mapping_status": binding.mapping_status,
            "binding_blocked": binding.blocked,
            "binding_reason": binding.reason,
            "performance_eligibility": eligibility,
            "cost_completeness": entry.cost_completeness,
        }
        inventory.append(row)
        if eligibility.startswith("ELIGIBLE"):
            evidence_backed.append(row)
        if eligibility.startswith("BLOCKED"):
            blocked.append(row)
    best = None
    canonical_rows = [
        r
        for r in evidence_backed
        if r["path"] == CANONICAL_PARQUET.replace("\\", "/") or r["filename"] == "XAUUSD_i_5m.parquet"
    ]
    if canonical_rows:
        best = canonical_rows[0]
    else:
        m5 = [r for r in evidence_backed if r.get("timeframe") == "M5" and r.get("symbol") == PRIMARY_SYMBOL]
        best = m5[0] if m5 else (evidence_backed[0] if evidence_backed else None)
    return {
        "inventory": inventory,
        "evidence_backed": evidence_backed,
        "blocked": blocked,
        "best_dataset": best,
        "counts": {
            "inventory": len(inventory),
            "evidence_backed": len(evidence_backed),
            "blocked": len(blocked),
            "direct_xauusd_i": sum(1 for r in inventory if r.get("symbol") == PRIMARY_SYMBOL),
            "logical_xauusd_blocked": sum(1 for r in blocked if r.get("symbol") == "XAUUSD"),
        },
    }


def _write_markdown(
    root: Path,
    *,
    manifest: dict[str, Any],
    baseline: dict[str, Any],
) -> None:
    sig = baseline["raw_signal_results"]
    exe = baseline["executable_results"]
    can = manifest["canonical_audit"]
    best = manifest.get("best_dataset") or {}
    q = can.get("quality") or {}
    suff = baseline["statistical_sufficiency"]
    path = root / PHASE280_MD
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""# Phase 28.0 — Performance Foundation

**Status:** {baseline.get("status")}
**Class:** RESEARCH ONLY
**Live trading authorized:** NO
**FINAL_GATE:** `{baseline.get("FINAL_GATE")}`
**EV-EQ-01:** `{baseline.get("ev_eq_01")}`
**Cost completeness:** `{baseline.get("cost_completeness")}`

This phase stops broker-evidence auditing and starts **performance validation** of GoldenEdge Price Action / `gold_ny_sweep` using only defensible `XAUUSD_i` data.

It does **not** authorize live trading. It does **not** satisfy `COMPLETE_COSTS_REQUIRED`. It does **not** prove or disprove edge when the sample is short. Zero executable trades is **not** proof the strategy has no edge.

STOP AFTER PHASE 28.0. DO NOT START PHASE 28.1.

---

## Best dataset

| Field | Value |
|---|---|
| Path | `{best.get("path")}` |
| Symbol | `{best.get("symbol")}` |
| Timeframe | `{best.get("timeframe")}` |
| Rows | `{can.get("row_count")}` |
| Range | `{can.get("date_range", {}).get("start")} → {can.get("date_range", {}).get("end")}` |
| Timezone | `{can.get("timezone")}` |
| Fingerprint | `{can.get("fingerprint")}` |
| Fingerprint match | `{can.get("fingerprint_match")}` |
| Bid/Ask | `{can.get("bidask_coverage")}` |
| Spread | `{can.get("spread_coverage")}` |
| Provenance | `{can.get("provenance_quality")}` |
| Sidecar env | `{can.get("sidecar_account_environment")}` |
| Eligibility | `{best.get("performance_eligibility")}` |

Logical `XAUUSD` datasets are **BLOCKED** (`MISSING_EXPLICIT_MAP`). No silent `XAUUSD`→`XAUUSD_i` map was inserted. Phase 26 19-candidate / 0-allowed trace used `data/backtest/XAUUSD_M5_183d.parquet` (blocked here) and must not be reused as the 28.0 baseline.

H4 context file `{H4_CONTEXT_PARQUET}` is ELIGIBLE_CONTEXT when present. No canonical `XAUUSD_i` M15 parquet was found.

---

## Canonical quality

| Check | Result |
|---|---|
| Duplicate timestamps | `{q.get("duplicate_timestamps")}` |
| Malformed OHLC | `{q.get("malformed_ohlc")}` |
| Impossible candles | `{q.get("impossible_candles")}` |
| Zero volume | `{q.get("zero_volume")}` |
| Negative volume | `{q.get("negative_volume")}` |
| Gap count | `{q.get("gap_count")}` |
| Weekend/session gaps | `{q.get("weekend_or_session_gaps")}` |
| Weekday unexpected gaps | `{q.get("weekday_unexpected_gaps")}` |

Production parquet was **not** overwritten.

---

## Research configuration (unchanged strategy)

- Symbol: `XAUUSD_i` (empty `dataset_symbol_map`)
- Entry: M5 `gold_ny_sweep` / `london_sweep`
- Context: H4 bias where file exists; M15 missing
- NY 15–16 UTC; Asian end 08:00
- `MIN_CONFIDENCE=0.52`, `MIN_QUALITY_SCORE=55`, `MIN_RR`/`TP_RR=1.5`, `SL_ATR_MULT=0.35`
- `COOLDOWN_BARS=18`, `MAX_TRADES_PER_DAY=3`
- `REQUIRE_HTF_ALIGNMENT_M5=False`
- Risk per trade `0.005`
- RiskGate unchanged; meta-labeler on; commission `UNKNOWN` (fail-closed, not ZERO)
- No parameter optimization

Fingerprint: `{baseline["research_configuration"]["configuration_fingerprint"]}`

---

## Lookahead / entry timing

{baseline["lookahead"]["entry_timing_official"]}

- Official signals use **closed bars only**
- Features do not include future candle data
- Signal generation does not use future high/low
- Exits may use future bars **after** entry
- Forming bar is appended then excluded (`simulate_forming_bar` + `exclude_forming_bar`)

---

## A) SIGNAL EDGE (before RiskGate)

| Metric | Value |
|---|---|
| Setups | `{sig.get("setups")}` |
| BUY | `{sig.get("BUY")}` |
| SELL | `{sig.get("SELL")}` |
| Wins | `{sig.get("wins")}` |
| Losses | `{sig.get("losses")}` |
| Open at end | `{sig.get("open")}` |
| Win rate | `{sig.get("win_rate")}` |
| Expectancy R | `{sig.get("expectancy_R")}` |
| Profit factor | `{sig.get("profit_factor")}` |
| Max drawdown R | `{sig.get("max_drawdown_R")}` |
| Consecutive losses | `{sig.get("max_consecutive_losses")}` |
| Trade frequency | `{sig.get("trade_frequency")}` |

These are theoretical SL/TP outcomes on subsequent bars. They are **not** cost-adjusted and **not** executable.

---

## B) EXECUTABLE EDGE (current RiskGate)

| Metric | Value |
|---|---|
| Candidates | `{exe.get("candidates")}` |
| Allowed | `{exe.get("allowed")}` |
| Rejected | `{exe.get("rejected")}` |
| Rejection reasons | `{json.dumps(exe.get("rejection_reasons") or {}, default=str)}` |
| Executed simulated trades | `{exe.get("executed_simulated_trades")}` |
| Expectancy R | `{exe.get("expectancy_R")}` |
| PF | `{exe.get("profit_factor")}` |
| DD | `{exe.get("max_drawdown_R")}` |

Gates were **not** changed to produce trades. `{exe.get("broker_fill_note")}`

---

## Statistical sufficiency

**{suff.get("classification")}**

Reasons: {", ".join(suff.get("reasons") or []) or "none"}

Do not invent confidence. A ~15-day canonical tape cannot support a strategy-edge claim.

---

## Determinism

`{baseline.get("deterministic_reproducibility")}`

---

## Conclusion

{baseline.get("conclusion")}

---

## Safety

- No MT5, no live orders, no bot/daemon, no `.env`
- No production dataset modification
- No RiskGate / strategy / sizing / RR / ML changes
- No silent XAUUSD→XAUUSD_i dataset mapping
- `FINAL_GATE` remains BLOCKED
- Phase 28.1 was **not** started

Artifacts:

- `{PHASE280_MANIFEST_JSON}`
- `{PHASE280_BASELINE_JSON}`
- `{PHASE280_MD}`
- `tradingbot/backtest/phase28_0_performance_foundation.py`
- `tests/test_phase28_0_performance_foundation.py`
""",
        encoding="utf-8",
    )


def run_phase28_0_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path.cwd())
    before = build_immutability_manifest(base_dir=root)
    fp_before = file_fingerprint(root / CANONICAL_PARQUET)
    gate16 = _safe_load_json(root / PHASE2716_JSON) or {}
    final_gate = gate16.get("FINAL_GATE") or BLOCKED

    inv = _inventory_payload(root)
    canonical = _canonical_audit(root)
    research = build_research_configuration()

    manifest = {
        "schema_version": 1,
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "git_head": _git_head(root),
        "research_only": True,
        "live_trading_authorized": False,
        "cost_adjusted_metrics_allowed": False,
        "parameters_optimized": False,
        "ev_eq_01": "NOT_PROVEN",
        "cost_completeness": BLOCKED,
        "FINAL_GATE": final_gate,
        "production_readiness": BLOCKED,
        "canonical_symbol": PRIMARY_SYMBOL,
        "dataset_symbol_map": {},
        "silent_xauusd_mapping": False,
        "best_dataset": inv["best_dataset"],
        "inventory": inv["inventory"],
        "evidence_backed": inv["evidence_backed"],
        "blocked": inv["blocked"],
        "counts": inv["counts"],
        "canonical_audit": canonical,
        "h4_context_available": (root / H4_CONTEXT_PARQUET).is_file(),
        "m15_xauusd_i_available": False,
        "datasets_changed": False,
        "safety": {
            "MT5_STARTED": False,
            "BOT_STARTED": False,
            "ORDERS_SENT": False,
            "SYMBOL_SELECT": False,
            "ENV_ACCESSED": False,
            "DATASETS_MUTATED": False,
            "STRATEGY_CHANGED": False,
            "RISKGATE_CHANGED": False,
            "PHASE_28_1_STARTED": False,
        },
    }

    best_path = root / CANONICAL_PARQUET
    df = load_parquet_utc(best_path)
    # Enrich uses indicator math; PA preset aliasing is not a dataset bind.
    enriched = _enrich_frame(df)
    h4 = load_parquet_utc(root / H4_CONTEXT_PARQUET) if (root / H4_CONTEXT_PARQUET).is_file() else None

    setups = scan_signal_setups(enriched, warmup=WARMUP, symbol=PRIMARY_SYMBOL)
    setups_repeat = scan_signal_setups(enriched, warmup=WARMUP, symbol=PRIMARY_SYMBOL)
    fp1 = _setups_fingerprint(setups)
    fp2 = _setups_fingerprint(setups_repeat)
    deterministic = fp1 == fp2

    span_days = 0.0
    if not df.empty:
        span_days = float((df.index[-1] - df.index[0]).total_seconds() / 86400.0)
    buy_n = sum(1 for s in setups if str(s.get("direction")).upper() == "BUY")
    sell_n = sum(1 for s in setups if str(s.get("direction")).upper() == "SELL")
    resolved = [s for s in setups if s.get("outcome") in {"win", "loss"}]
    r_vals = [float(s["r_multiple"]) for s in resolved if s.get("r_multiple") is not None]
    metrics = _metrics_from_r(r_vals, calendar_days=span_days)
    open_n = sum(1 for s in setups if s.get("outcome") == "open")

    engine = _build_research_engine(enriched, research, h4=h4)
    executable = asyncio.run(evaluate_executable_edge(engine, setups, research))

    sufficiency = classify_statistical_sufficiency(
        resolved=metrics["resolved"],
        calendar_days=span_days,
        setups=len(setups),
    )

    if sufficiency["classification"] == "DATA_INSUFFICIENT":
        conclusion = (
            "DATA_INSUFFICIENT. The defensible XAUUSD_i M5 tape is too short for a statistical "
            "edge claim. Signal-edge metrics on this window are descriptive only. "
            "Zero RiskGate-allowed / zero SimulatedBroker fills is not proof the strategy has no edge. "
            "EV-EQ-01 remains NOT_PROVEN. Cost completeness remains BLOCKED. "
            "This research does not authorize live trading or Phase 28.1."
        )
        status = "PASS_WITH_DEFERRAL"
    else:
        conclusion = (
            "Sample meets the minimum size heuristic; still not a production authorization. "
            "Cost-adjusted validation remains BLOCKED."
        )
        status = "PASS"

    lookahead = {
        "official_results_closed_bars_only": True,
        "features_use_future_candles": False,
        "signal_generation_uses_future_high_low": False,
        "exits_may_use_future_bars_after_entry": True,
        "forming_bar_excluded": True,
        "entry_timing_official": (
            "Official signal is generated on the last closed M5 bar after exclude_forming_bar. "
            "A synthetic forming bar is appended only to match the live/backtest window shape, "
            "then dropped, so its OHLC is not used for features or signal generation. "
            "Entry price is PriceActionStrategy setup.entry on that closed bar. "
            "Theoretical SL/TP evaluation starts at the next bar. Same-bar SL is taken before TP, "
            "matching SimulatedBroker.check_exits."
        ),
    }

    raw_signal = {
        "setups": len(setups),
        "BUY": buy_n,
        "SELL": sell_n,
        "open": open_n,
        **metrics,
        "setup_rows": setups,
    }

    baseline = {
        "schema_version": 1,
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "git_head": _git_head(root),
        "status": status,
        "research_only": True,
        "live_trading_authorized": False,
        "cost_adjusted_metrics_allowed": False,
        "parameters_optimized": False,
        "strategy_changed": False,
        "riskgate_changed": False,
        "ev_eq_01": "NOT_PROVEN",
        "cost_completeness": BLOCKED,
        "FINAL_GATE": final_gate,
        "production_readiness": BLOCKED,
        "best_dataset": CANONICAL_PARQUET,
        "dataset_fingerprint": fp_before,
        "data_range": canonical.get("date_range"),
        "rows": canonical.get("row_count"),
        "data_quality": canonical.get("quality"),
        "provenance": canonical.get("provenance_quality"),
        "bidask_coverage": canonical.get("bidask_coverage"),
        "research_configuration": research,
        "lookahead": lookahead,
        "raw_signal_results": raw_signal,
        "executable_results": executable,
        "statistical_sufficiency": sufficiency,
        "deterministic_reproducibility": {
            "signal_scan_repeated": True,
            "setups_fingerprint_match": deterministic,
            "fingerprint": fp1,
        },
        "conclusion": conclusion,
        "phase_26_note": (
            "Phase 26D/E 19 candidates / 0 allowed used blocked logical XAUUSD 183d tail, "
            "not this canonical XAUUSD_i tape."
        ),
        "full_kernel_walk": (
            "NOT_RUN. Bounded baseline is closed-bar signal scan + RiskGate replay on those "
            "candidates. A 3000-bar kernel walk is not required to measure this split and was "
            "previously estimated too expensive (~1.2s/evaluable-bar in Phase 26K)."
        ),
        "safety": manifest["safety"],
        "phase_28_1_started": False,
    }

    ok, issues = verify_immutability(before, base_dir=root)
    fp_after = file_fingerprint(root / CANONICAL_PARQUET)
    datasets_changed = (not ok) or (fp_before != fp_after)
    manifest["datasets_changed"] = datasets_changed
    manifest["immutability_issues"] = issues
    manifest["canonical_fingerprint_before"] = fp_before
    manifest["canonical_fingerprint_after"] = fp_after
    baseline["datasets_changed"] = datasets_changed
    baseline["canonical_fingerprint_before"] = fp_before
    baseline["canonical_fingerprint_after"] = fp_after

    _write_json(root / PHASE280_MANIFEST_JSON, manifest)
    _write_json(root / PHASE280_BASELINE_JSON, baseline)
    _write_markdown(root, manifest=manifest, baseline=baseline)

    known = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    if known.is_file():
        text = known.read_text(encoding="utf-8")
        marker = "## Performance validation (Phase 28.0)"
        block = (
            "\n\n## Performance validation (Phase 28.0)\n\n"
            "| Claim | Status |\n"
            "|---|---|\n"
            "| Canonical XAUUSD_i M5 is the best defensible performance dataset | **SUPPORTED** |\n"
            "| Logical XAUUSD tapes usable without explicit map | **BLOCKED** |\n"
            "| Current gold_ny_sweep has proven trading edge | **DATA_INSUFFICIENT** — short canonical tape; do not invent confidence |\n"
            "| 0 RiskGate-allowed trades proves no edge | **FALSE** — sample too small; gates unchanged |\n"
            "| Phase 28.0 authorizes live trading | **NO** — RESEARCH ONLY; FINAL_GATE remains BLOCKED |\n"
        )
        if marker not in text:
            known.write_text(text.rstrip() + block, encoding="utf-8")

    return {"manifest": manifest, "baseline": baseline}


if __name__ == "__main__":
    run_phase28_0_collection()

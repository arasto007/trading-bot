"""Phase 40 — full-horizon unchanged-strategy research validation.

RESEARCH ONLY. Uses the Phase 38 XAUUSD_i M5 tape. Does not trade, optimize,
modify production strategy/RiskGate/execution/ML, read .env, or overwrite the
frozen Phase 28 snapshot. Does not start Phase 41.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import io
import json
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from engine.strategies.price_action_strategy import PriceActionStrategy
from tradingbot.adapters.legacy_loader import load_legacy_config
from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.dataset_contract import classify_dataset_binding
from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase26c_zero_signal_audit import WARMUP, _append_forming_bar_m5, _enrich_frame
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_30_slippage_evidence import file_fingerprint
from tradingbot.backtest.phase28_0_performance_foundation import (
    BLOCKED,
    CANONICAL_PARQUET,
    EXPECTED_CANONICAL_FINGERPRINT,
    H4_CONTEXT_PARQUET,
    _build_research_engine,
    build_research_configuration,
    evaluate_executable_edge,
    load_parquet_utc,
    theoretical_outcome,
)
from tradingbot.backtest.phase28_1_full_baseline import _parse_ts, expand_raw_metrics
from tradingbot.backtest.phase28_2_walk_forward import TRAIN_FRAC, VAL_FRAC, OOS_FRAC, chronological_index_splits
from tradingbot.backtest.phase28_3_monte_carlo import N_PATHS, run_bootstrap, summarize_paths
from tradingbot.backtest.phase29_research_tape import audit_dataset, content_fingerprint
from tradingbot.backtest.phase30_unchanged_strategy_evaluation import event_representatives, strategy_logic_fingerprint
from tradingbot.backtest.phase31_event_independence import assign_mechanical_events, event_metrics
from tradingbot.backtest.phase38_intelligent_evidence_acquisition import (
    PHASE38_JSON,
    PHASE38_M5,
    PHASE38_SETUPS,
    _attach_official_asian_range,
)
from tradingbot.backtest.phase39_broker_economics_execution import PHASE39_JSON, apply_modeled_cost
from tradingbot.config.live import PRIMARY_SYMBOL
from tradingbot.config.pa_symbol_tf_presets import PA_SYMBOL_TF_PRESETS
from tradingbot.config.price_action import apply_pa_to_legacy, get_price_action_config
from tradingbot.domain.gold_strategies.m5_london_sweep import asian_range, m5_asian_end_hour, m5_ny_entry_hours
from tradingbot.domain.ohlcv import exclude_forming_bar
from tradingbot.domain.pa_hardening import clear_pa_dedup_cache
from tradingbot.domain.risk_logic import infer_regime_from_ohlcv

PHASE = "40"
PHASE40_JSON = "logs/phase40_full_horizon_validation.json"
PHASE40_MD = "docs_v2/02_research/PHASE40_FULL_HORIZON_VALIDATION.md"
PHASE40_SETUPS_JSONL = "logs/phase40_raw_setups.jsonl"
PHASE40_PROGRESS = "logs/phase40_scan_progress.json"
CANONICAL_SYMBOL = "XAUUSD_i"
LOGICAL_SYMBOL = "XAUUSD"
SCAN_WINDOW_BARS = 512
RNG_SEED = 400040
MIN_EVENTS = 30
EVAL_DAYS = 180
SL_PERTURB_PCT = 0.05
PROGRESS_EVERY_NY = 400
UNKNOWN = "UNKNOWN"

# Predeclared before any fold metrics are computed.
WALKFORWARD_DECLARATION = {
    "split": "chronological bar-index 60/20/20 on the complete Phase 38 M5 tape",
    "tape": PHASE38_M5,
    "train_frac": TRAIN_FRAC,
    "val_frac": VAL_FRAC,
    "oos_frac": OOS_FRAC,
    "shuffle": False,
    "optimization": False,
    "refit": False,
    "threshold_tuning_on_oos": False,
    "best_window_selection": False,
    "declared_before_metrics": True,
}

SENSITIVITY_DECLARATION = {
    "declared_before_metrics": True,
    "commission": "UNKNOWN — not invented",
    "swap": "not applied — historical UNKNOWN",
    "spread_base_pips": 2.5,
    "slippage_base_pips": 0.8,
    "source": "BacktestConfig defaults; MODELED/SCENARIO, not BROKER-OBSERVED",
    "scenarios": (
        {"id": "RAW_NO_COST", "spread_mult": 0.0, "slip_mult": 0.0},
        {"id": "MODELED_1X", "spread_mult": 1.0, "slip_mult": 1.0},
        {"id": "MODELED_2X", "spread_mult": 2.0, "slip_mult": 2.0},
        {"id": "MODELED_3X", "spread_mult": 3.0, "slip_mult": 3.0},
    ),
}

ROBUSTNESS_DECLARATION = {
    "declared_before_metrics": True,
    "optimization": False,
    "parameter_grid_search": False,
    "diagnostics": (
        "official_entry_vs_next_bar_open",
        "sl_wider_5pct",
        "rr_1_4_and_1_6_vs_official_1_5",
        "modeled_cost_shocks",
        "event_level_vs_signal_level",
    ),
    "note": "Diagnostics are reported, not used to select a preferred configuration.",
}

REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "research_only",
    "data_quality",
    "strategy_fingerprint",
    "scan",
    "raw_signal",
    "events",
    "dependence",
    "walk_forward",
    "oos_sufficiency",
    "stability",
    "direction",
    "session",
    "raw_performance",
    "executable",
    "cost_sensitivity",
    "statistics",
    "robustness",
    "comparison_180_vs_full",
    "classification",
    "blocker_matrix",
    "FINAL_GATE",
    "phase_41_started",
)

FORBIDDEN_OUTPUT_KEYS = ("password", "mt5_password", "token", "api_key", "investor")

CODE_FINGERPRINT_FILES = (
    "engine/strategies/price_action_strategy.py",
    "tradingbot/domain/gold_strategies/m5_london_sweep.py",
    "tradingbot/domain/gold_strategies/router.py",
    "tradingbot/domain/pa_hardening.py",
    "tradingbot/config/pa_symbol_tf_presets.py",
    "tradingbot/adapters/risk_gate.py",
    "tradingbot/services/meta_labeler.py",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_head(base_dir: Path) -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=base_dir, capture_output=True, text=True, timeout=5)
        if out.returncode == 0:
            return out.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return UNKNOWN


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def _redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: ("REDACTED" if str(k).lower() in FORBIDDEN_OUTPUT_KEYS else _redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact(x) for x in obj]
    return obj


def _file_sha256(path: Path) -> str:
    if not path.is_file():
        return UNKNOWN
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _duration_days(df: pd.DataFrame) -> float:
    if df is None or df.empty:
        return 0.0
    idx = pd.to_datetime(df.index, utc=True)
    return float((idx.max() - idx.min()).total_seconds() / 86400.0)


def code_strategy_fingerprint(root: Path) -> dict[str, Any]:
    """CODE WINS. Documented assumptions are not used if they disagree with presets."""
    m5 = dict(PA_SYMBOL_TF_PRESETS["XAUUSD"]["M5"])
    cfg = get_price_action_config(PRIMARY_SYMBOL, "M5")
    ny_s, ny_e = m5_ny_entry_hours(cfg)
    asian_end = m5_asian_end_hour(cfg)
    files = {rel: _file_sha256(root / rel)[:16] for rel in CODE_FINGERPRINT_FILES}
    knobs = {
        "strategy_class": "PriceActionStrategy",
        "preset": m5.get("PRESET"),
        "gold_strategy_mode": m5.get("GOLD_STRATEGY_MODE"),
        "timeframe": "M5",
        "live_symbol": PRIMARY_SYMBOL,
        "preset_key": "XAUUSD/M5 — live preset aliasing via normalize_symbol; NOT a dataset bind",
        "session": f"NY {ny_s:02d}–{ny_e:02d} UTC",
        "asian_start_hour": int(m5.get("ASIAN_START_HOUR", 0)),
        "asian_end_hour": int(asian_end),
        "ny_entry_start_hour": int(m5.get("NY_ENTRY_START_HOUR", 15)),
        "ny_entry_end_hour": int(m5.get("NY_ENTRY_END_HOUR", 16)),
        "sweep_lookback_bars": int(m5.get("SWEEP_LOOKBACK_BARS", 12)),
        "sweep_buffer_atr": float(m5.get("SWEEP_BUFFER_ATR", 0.12)),
        "reclaim": "price back inside Asian range after sweep (CHOCH continuation OFF)",
        "entry_timing": "last CLOSED M5 bar; forming bar appended then excluded",
        "sl_atr_mult": float(m5.get("SL_ATR_MULT", 0.35)),
        "min_rr": float(m5.get("MIN_RR", 1.5)),
        "tp_rr": float(m5.get("TP_RR", 1.5)),
        "min_confidence": float(m5.get("MIN_CONFIDENCE", 0.52)),
        "min_quality_score": float(m5.get("MIN_QUALITY_SCORE", 55)),
        "m5_require_rejection": bool(m5.get("M5_REQUIRE_REJECTION", False)),
        "atr_pct_min": float(m5.get("ATR_PCT_MIN", 12)),
        "atr_pct_max": float(m5.get("ATR_PCT_MAX", 94)),
        "use_atr_percentile_filter": bool(m5.get("USE_ATR_PERCENTILE_FILTER", True)),
        "use_adx_filter": bool(m5.get("USE_ADX_FILTER", False)),
        "meta_label_threshold": float(m5.get("META_LABEL_THRESHOLD", 0.38)),
        "cooldown_bars": int(m5.get("COOLDOWN_BARS", 18)),
        "max_trades_per_day": int(m5.get("MAX_TRADES_PER_DAY", 3)),
        "enable_partial_tp": bool(m5.get("ENABLE_PARTIAL_TP", False)),
        "enable_choch_continuation": bool(m5.get("ENABLE_CHOCH_CONTINUATION", False)),
        "signal_confirmation_bars": int(cfg.get("SIGNAL_CONFIRMATION_BARS", 0)),
        "pa_dedup_cooldown_minutes": int(m5.get("PA_DEDUP_COOLDOWN_MINUTES", 10)),
        "max_open_positions_total": int(m5.get("MAX_OPEN_POSITIONS_TOTAL", 3)),
        "max_open_positions_per_symbol": int(m5.get("MAX_OPEN_POSITIONS_PER_SYMBOL", 2)),
        "logic_hash": strategy_logic_fingerprint(),
        "file_hashes_16": files,
    }
    blob = json.dumps(knobs, sort_keys=True, default=str).encode()
    knobs["deterministic_fingerprint"] = hashlib.sha256(blob).hexdigest()
    knobs["code_wins"] = True
    knobs["parameters_changed"] = False
    return knobs


def theoretical_outcome_with_excursions(
    df: pd.DataFrame,
    entry_idx: int,
    direction: str,
    entry: float,
    sl: float,
    tp: float,
) -> dict[str, Any]:
    """Official SL-before-TP walk plus MFE/MAE. Exits start at the next bar."""
    risk = abs(float(entry) - float(sl))
    buy = str(direction).upper() in {"BUY", "1", "LONG"}
    if risk <= 0:
        return {
            "outcome": "invalid_risk",
            "r_multiple": None,
            "exit_price": None,
            "exit_index": None,
            "mfe_R": None,
            "mae_R": None,
            "duration_bars": None,
            "duration_minutes": None,
        }
    mfe = 0.0
    mae = 0.0
    for j in range(entry_idx + 1, len(df)):
        row = df.iloc[j]
        high = float(row["high"])
        low = float(row["low"])
        if buy:
            mfe = max(mfe, (high - entry) / risk)
            mae = max(mae, (entry - low) / risk)
            hit_sl = low <= sl
            hit_tp = high >= tp
            if hit_sl:
                return _exit_pack(df, entry_idx, j, sl, -1.0, "loss", mfe, mae, True, hit_tp)
            if hit_tp:
                return _exit_pack(df, entry_idx, j, tp, float((tp - entry) / risk), "win", mfe, mae, False, False)
        else:
            mfe = max(mfe, (entry - low) / risk)
            mae = max(mae, (high - entry) / risk)
            hit_sl = high >= sl
            hit_tp = low <= tp
            if hit_sl:
                return _exit_pack(df, entry_idx, j, sl, -1.0, "loss", mfe, mae, True, hit_tp)
            if hit_tp:
                return _exit_pack(df, entry_idx, j, tp, float((entry - tp) / risk), "win", mfe, mae, False, False)
    return {
        "outcome": "open",
        "r_multiple": None,
        "exit_price": None,
        "exit_index": None,
        "exit_time": None,
        "same_bar_sl_and_tp": False,
        "mfe_R": round(mfe, 6),
        "mae_R": round(mae, 6),
        "duration_bars": None,
        "duration_minutes": None,
    }


def _exit_pack(
    df: pd.DataFrame,
    entry_idx: int,
    j: int,
    exit_price: float,
    r_mult: float,
    outcome: str,
    mfe: float,
    mae: float,
    sl_first: bool,
    same_bar_both: bool,
) -> dict[str, Any]:
    start = df.index[entry_idx]
    end = df.index[j]
    minutes = float((pd.Timestamp(end) - pd.Timestamp(start)).total_seconds() / 60.0)
    return {
        "outcome": outcome,
        "r_multiple": float(r_mult),
        "exit_price": float(exit_price),
        "exit_index": int(j),
        "exit_time": str(end),
        "same_bar_sl_and_tp": bool(sl_first and same_bar_both),
        "mfe_R": round(float(mfe), 6),
        "mae_R": round(float(mae), 6),
        "duration_bars": int(j - entry_idx),
        "duration_minutes": round(minutes, 4),
    }


def _sweep_window(df: pd.DataFrame, i: int, cfg: dict[str, Any]) -> tuple[float | None, float | None]:
    lookback = int(cfg.get("SWEEP_LOOKBACK_BARS", 12))
    if i < 0 or i >= len(df):
        return None, None
    start_j = max(0, i - lookback)
    window = df.iloc[start_j : i + 1]
    return float(window["high"].max()), float(window["low"].min())


def _compact_setup(s: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "timestamp",
        "cursor",
        "closed_bar_index",
        "direction",
        "side",
        "mechanical_event_id",
        "entry_price",
        "sweep_high",
        "sweep_low",
        "asian_high",
        "asian_low",
        "stop_loss",
        "take_profit",
        "planned_rr",
        "outcome",
        "r_multiple",
        "mfe_R",
        "mae_R",
        "duration_bars",
        "duration_minutes",
        "exit_time",
        "confidence",
        "quality_score",
        "setup",
        "regime",
        "hour_utc",
    )
    return {k: s.get(k) for k in keys}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, default=str) + "\n")


def ny_only_scan_windowed(
    enriched: pd.DataFrame,
    *,
    symbol: str,
    window_bars: int,
    start_cursor: int,
    setups_path: Path,
    progress_path: Path,
    tape_fp: str,
) -> dict[str, Any]:
    """Closed-bar causal NY scan. Bounded lookback equals production indicator windows."""
    cfg = get_price_action_config(symbol, "M5")
    ny_s, ny_e = m5_ny_entry_hours(cfg)
    legacy = apply_pa_to_legacy(load_legacy_config(), symbol, "M5")
    clear_pa_dedup_cache()
    pa = PriceActionStrategy(legacy)
    idx = enriched.index
    n = int(len(enriched))
    ny_scanned = 0
    wait = 0
    setups: list[dict[str, Any]] = []
    begin = max(int(start_cursor), WARMUP)
    _write_json(
        progress_path,
        {
            "last_cursor": begin,
            "n_bars": n,
            "window_bars": int(window_bars),
            "tape_fingerprint": tape_fp,
            "ny_scanned": 0,
            "wait": 0,
            "signals": 0,
            "completed": False,
            "updated_utc": _utc_now(),
        },
    )
    for cursor in range(begin, n):
        ts = idx[cursor]
        hour = int(getattr(ts, "hour", -1))
        if not (ny_s <= hour < ny_e):
            continue
        ny_scanned += 1
        start = max(0, cursor + 1 - int(window_bars))
        window = _append_forming_bar_m5(enriched.iloc[start : cursor + 1])
        closed = exclude_forming_bar(window, min_rows=30)
        if closed is None or closed.empty:
            wait += 1
            continue
        i = len(closed) - 1
        closed_ts = closed.index[i]
        closed_hour = int(getattr(closed_ts, "hour", -1))
        if not (ny_s <= closed_hour < ny_e):
            wait += 1
            continue
        sigs = pa.generate_signals(closed, symbol=symbol, timeframe="M5")
        if not sigs:
            wait += 1
            continue
        sig = sigs[0]
        direction = getattr(getattr(sig, "signal_type", None), "name", None) or str(
            getattr(sig, "signal_type", UNKNOWN)
        )
        meta = getattr(sig, "metadata", None) or {}
        entry = float(getattr(sig, "price", closed.iloc[i]["close"]))
        sl = float(meta.get("stop_loss") or 0.0)
        tp = float(meta.get("take_profit") or 0.0)
        full_idx = int(enriched.index.get_indexer([closed.index[i]], method="nearest")[0])
        result = theoretical_outcome_with_excursions(enriched, full_idx, direction, entry, sl, tp)
        sweep_hi, sweep_lo = _sweep_window(enriched, full_idx, cfg)
        planned = meta.get("risk_reward_ratio")
        if planned is None and sl and abs(entry - sl) > 0:
            planned = abs(tp - entry) / abs(entry - sl)
        regime = UNKNOWN
        try:
            regime = str(infer_regime_from_ohlcv(enriched, full_idx) or UNKNOWN)
        except Exception:
            regime = UNKNOWN
        row = {
            "timestamp": str(closed.index[i]),
            "cursor": int(cursor),
            "closed_bar_index": int(full_idx),
            "direction": direction,
            "side": "BUY" if "BUY" in str(direction).upper() else "SELL" if "SELL" in str(direction).upper() else direction,
            "entry_price": entry,
            "stop_loss": sl,
            "take_profit": tp,
            "planned_rr": planned,
            "confidence": float(getattr(sig, "confidence", 0) or 0),
            "quality_score": meta.get("quality_score"),
            "setup": meta.get("setup") or meta.get("pattern"),
            "symbol": getattr(sig, "symbol", symbol),
            "asian_high": meta.get("asian_high"),
            "asian_low": meta.get("asian_low"),
            "sweep_high": sweep_hi,
            "sweep_low": sweep_lo,
            "sweep_side": meta.get("sweep_side"),
            "hour_utc": closed_hour,
            "regime": regime,
            **result,
            "entry_timing": (
                "Signal on last CLOSED M5 bar only. Forming bar is appended then excluded. "
                "Entry price = strategy setup.entry from that closed bar. "
                "Theoretical exits start at the next bar (i+1). Same-bar SL before TP."
            ),
        }
        setups.append(row)
        _append_jsonl(setups_path, _compact_setup(row))
        if ny_scanned % PROGRESS_EVERY_NY == 0:
            _write_json(
                progress_path,
                {
                    "last_cursor": int(cursor),
                    "n_bars": n,
                    "window_bars": int(window_bars),
                    "tape_fingerprint": tape_fp,
                    "ny_scanned": ny_scanned,
                    "wait": wait,
                    "signals": len(setups),
                    "completed": False,
                    "updated_utc": _utc_now(),
                },
            )
    _write_json(
        progress_path,
        {
            "last_cursor": n - 1,
            "n_bars": n,
            "window_bars": int(window_bars),
            "tape_fingerprint": tape_fp,
            "ny_scanned": ny_scanned,
            "wait": wait,
            "signals": len(setups),
            "completed": True,
            "updated_utc": _utc_now(),
        },
    )
    return {
        "setups": setups,
        "ny_bars_scanned": ny_scanned,
        "wait": wait,
        "buy": sum(1 for s in setups if str(s.get("side")).upper() == "BUY"),
        "sell": sum(1 for s in setups if str(s.get("side")).upper() == "SELL"),
        "start_cursor": begin,
        "end_cursor": n - 1,
        "window_bars": int(window_bars),
        "warmup_bars": WARMUP,
        "completed": True,
    }


def _resume_or_scan(
    enriched: pd.DataFrame,
    *,
    root: Path,
    tape_fp: str,
) -> dict[str, Any]:
    setups_path = root / PHASE40_SETUPS_JSONL
    progress_path = root / PHASE40_PROGRESS
    n = int(len(enriched))
    prev = _safe_load_json(progress_path) or {}
    if (
        prev.get("completed")
        and int(prev.get("n_bars") or 0) == n
        and str(prev.get("tape_fingerprint") or "") == tape_fp
        and int(prev.get("window_bars") or 0) == SCAN_WINDOW_BARS
        and setups_path.is_file()
    ):
        loaded = _load_jsonl(setups_path)
        return {
            "setups": loaded,
            "ny_bars_scanned": int(prev.get("ny_scanned") or 0),
            "wait": int(prev.get("wait") or 0),
            "buy": sum(1 for s in loaded if str(s.get("side")).upper() == "BUY"),
            "sell": sum(1 for s in loaded if str(s.get("side")).upper() == "SELL"),
            "start_cursor": WARMUP,
            "end_cursor": n - 1,
            "window_bars": SCAN_WINDOW_BARS,
            "warmup_bars": WARMUP,
            "completed": True,
            "reused_checkpoint": True,
        }
    start_cursor = WARMUP
    existing: list[dict[str, Any]] = []
    if (
        int(prev.get("n_bars") or 0) == n
        and str(prev.get("tape_fingerprint") or "") == tape_fp
        and int(prev.get("window_bars") or 0) == SCAN_WINDOW_BARS
        and not prev.get("completed")
        and setups_path.is_file()
    ):
        existing = _load_jsonl(setups_path)
        start_cursor = int(prev.get("last_cursor") or WARMUP) + 1
    else:
        if setups_path.is_file():
            setups_path.unlink()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        scanned = ny_only_scan_windowed(
            enriched,
            symbol=PRIMARY_SYMBOL,
            window_bars=SCAN_WINDOW_BARS,
            start_cursor=start_cursor,
            setups_path=setups_path,
            progress_path=progress_path,
            tape_fp=tape_fp,
        )
    if existing:
        scanned["setups"] = existing + scanned["setups"]
        scanned["buy"] = sum(1 for s in scanned["setups"] if str(s.get("side")).upper() == "BUY")
        scanned["sell"] = sum(1 for s in scanned["setups"] if str(s.get("side")).upper() == "SELL")
        scanned["ny_bars_scanned"] = int(prev.get("ny_scanned") or 0) + int(scanned.get("ny_bars_scanned") or 0)
        scanned["wait"] = int(prev.get("wait") or 0) + int(scanned.get("wait") or 0)
        scanned["resumed"] = True
    else:
        scanned["resumed"] = False
    scanned["reused_checkpoint"] = False
    return scanned


def _perf(rows: list[dict[str, Any]], days: float) -> dict[str, Any]:
    ny_days = len({str(_parse_ts(r.get("timestamp")).date()) for r in rows if _parse_ts(r.get("timestamp"))})
    adapted = []
    for r in rows:
        adapted.append(
            {
                **r,
                "direction": r.get("side") or r.get("direction"),
                "r_multiple": r.get("r_multiple"),
            }
        )
    block = expand_raw_metrics(adapted, calendar_days=days, ny_session_days=max(ny_days, 1))
    mfes = [float(r["mfe_R"]) for r in rows if r.get("mfe_R") is not None]
    maes = [float(r["mae_R"]) for r in rows if r.get("mae_R") is not None]
    durs = [float(r["duration_minutes"]) for r in rows if r.get("duration_minutes") is not None]
    block["median_duration_minutes"] = None if not durs else float(np.median(durs))
    block["average_mfe_R"] = None if not mfes else round(float(np.mean(mfes)), 6)
    block["median_mfe_R"] = None if not mfes else round(float(np.median(mfes)), 6)
    block["average_mae_R"] = None if not maes else round(float(np.mean(maes)), 6)
    block["median_mae_R"] = None if not maes else round(float(np.median(maes)), 6)
    block["label"] = "RAW_THEORETICAL"
    return block


def _frequency(n_signals: int, days: float) -> dict[str, Any]:
    d = max(float(days), 1e-9)
    return {
        "calendar_days": round(d, 4),
        "signals_per_day": round(n_signals / d, 6),
        "signals_per_week": round(n_signals / (d / 7.0), 6),
        "signals_per_month": round(n_signals / (d / 30.4375), 6),
        "signals_per_year": round(n_signals / (d / 365.25), 6),
    }


def _period_stats(rows: list[dict[str, Any]], *, kind: str) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        ts = _parse_ts(r.get("timestamp"))
        if ts is None:
            continue
        if kind == "year":
            key = f"{ts.year:04d}"
        elif kind == "quarter":
            q = (ts.month - 1) // 3 + 1
            key = f"{ts.year:04d}-Q{q}"
        else:
            key = f"{ts.year:04d}-{ts.month:02d}"
        groups[key].append(r)
    out = []
    for key in sorted(groups):
        items = groups[key]
        ts0 = _parse_ts(items[0]["timestamp"])
        ts1 = _parse_ts(items[-1]["timestamp"])
        days = 1.0
        if ts0 is not None and ts1 is not None:
            days = max(float((ts1 - ts0).total_seconds() / 86400.0), 1.0)
        eids = {r.get("mechanical_event_id") for r in items if r.get("mechanical_event_id") is not None}
        perf = _perf(items, days)
        out.append(
            {
                "period": key,
                "signals": len(items),
                "events": len(eids),
                "BUY": sum(1 for r in items if str(r.get("side")).upper() == "BUY"),
                "SELL": sum(1 for r in items if str(r.get("side")).upper() == "SELL"),
                "win_rate": perf.get("win_rate"),
                "expectancy_R": perf.get("expectancy_R"),
                "profit_factor": perf.get("profit_factor"),
                "max_drawdown_R": perf.get("max_drawdown_R"),
            }
        )
    return out


def _regime_stats(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[str(r.get("regime") or UNKNOWN)].append(r)
    out = []
    for key, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        eids = {r.get("mechanical_event_id") for r in items if r.get("mechanical_event_id") is not None}
        perf = _perf(items, 1.0)
        out.append(
            {
                "regime": key,
                "signals": len(items),
                "events": len(eids),
                "win_rate": perf.get("win_rate"),
                "expectancy_R": perf.get("expectancy_R"),
                "profit_factor": perf.get("profit_factor"),
                "max_drawdown_R": perf.get("max_drawdown_R"),
            }
        )
    return out


def _direction_block(rows: list[dict[str, Any]], days: float) -> dict[str, Any]:
    buy = [r for r in rows if str(r.get("side")).upper() == "BUY"]
    sell = [r for r in rows if str(r.get("side")).upper() == "SELL"]
    buy_e = event_representatives([{**r, "event_cluster_id": r.get("mechanical_event_id")} for r in buy]) if buy else []
    sell_e = event_representatives([{**r, "event_cluster_id": r.get("mechanical_event_id")} for r in sell]) if sell else []
    return {
        "signal": {
            "BUY": _perf(buy, days) if buy else {"setups": 0},
            "SELL": _perf(sell, days) if sell else {"setups": 0},
        },
        "event": {
            "BUY": _perf(buy_e, days) if buy_e else {"setups": 0},
            "SELL": _perf(sell_e, days) if sell_e else {"setups": 0},
            "BUY_events": len(buy_e),
            "SELL_events": len(sell_e),
        },
        "note": "Do not infer a general edge from a tiny directional subset.",
    }


def classify_reject(reason: str) -> str:
    u = str(reason or "").lower()
    if "allowed" in u:
        return "ALLOWED"
    if "meta" in u:
        return "META"
    if "atr" in u:
        return "ATR"
    if "lot" in u or "volume" in u:
        return "LOT"
    if "spread" in u:
        return "SPREAD"
    if "news" in u:
        return "NEWS"
    if "cool" in u:
        return "COOLDOWN"
    return "OTHER"


def _walk_with_prices(
    df: pd.DataFrame,
    entry_idx: int,
    direction: str,
    entry: float,
    sl: float,
    tp: float,
    *,
    from_idx: int | None = None,
) -> dict[str, Any]:
    """Same SL-before-TP convention; optional start index for next-bar-open fills."""
    if from_idx is None:
        return theoretical_outcome(df, entry_idx, direction, entry, sl, tp)
    risk = abs(float(entry) - float(sl))
    buy = str(direction).upper() in {"BUY", "1", "LONG"}
    if risk <= 0:
        return {"outcome": "invalid_risk", "r_multiple": None}
    start = max(int(from_idx), 0)
    for j in range(start, len(df)):
        row = df.iloc[j]
        high = float(row["high"])
        low = float(row["low"])
        if buy:
            hit_sl = low <= sl
            hit_tp = high >= tp
            if hit_sl:
                return {"outcome": "loss", "r_multiple": -1.0, "exit_index": j, "exit_time": str(df.index[j])}
            if hit_tp:
                return {
                    "outcome": "win",
                    "r_multiple": float((tp - entry) / risk),
                    "exit_index": j,
                    "exit_time": str(df.index[j]),
                }
        else:
            hit_sl = high >= sl
            hit_tp = low <= tp
            if hit_sl:
                return {"outcome": "loss", "r_multiple": -1.0, "exit_index": j, "exit_time": str(df.index[j])}
            if hit_tp:
                return {
                    "outcome": "win",
                    "r_multiple": float((entry - tp) / risk),
                    "exit_index": j,
                    "exit_time": str(df.index[j]),
                }
    return {"outcome": "open", "r_multiple": None}


def _expectancy(rows: list[dict[str, Any]], key: str = "r_multiple") -> float | None:
    rs = [float(r[key]) for r in rows if r.get(key) is not None]
    if not rs:
        return None
    return float(sum(rs) / len(rs))


def classify_oos_sample(*, events: int, signals: int, days: float) -> str:
    del signals, days
    if events >= MIN_EVENTS:
        return "SUFFICIENT"
    if events >= 15:
        return "BORDERLINE"
    return "INSUFFICIENT"


def classify_research(
    *,
    event_n: int,
    event_exp: float | None,
    signal_exp: float | None,
    oos_events: int,
    oos_exp: float | None,
    yearly: list[dict[str, Any]],
    cost_ready: bool,
    executable_fills: int,
) -> dict[str, Any]:
    years = [y for y in yearly if int(y.get("events") or 0) >= 5]
    year_signs = []
    for y in years:
        exp = y.get("expectancy_R")
        if exp is None:
            continue
        year_signs.append(1 if float(exp) > 0 else -1 if float(exp) < 0 else 0)
    neg_years = sum(1 for s in year_signs if s < 0)
    pos_years = sum(1 for s in year_signs if s > 0)
    full_neg = event_exp is not None and float(event_exp) < 0
    full_pos = event_exp is not None and float(event_exp) > 0
    oos_neg = oos_exp is not None and float(oos_exp) < 0
    oos_pos = oos_exp is not None and float(oos_exp) > 0
    sig_neg = signal_exp is not None and float(signal_exp) < 0

    if event_n < MIN_EVENTS:
        raw = "D"
        raw_reason = f"full-tape mechanical events={event_n} < {MIN_EVENTS}"
    elif full_neg and sig_neg and (oos_events == 0 or oos_neg) and neg_years >= max(pos_years, 1):
        raw = "C"
        raw_reason = (
            "Full-horizon RAW signal and event expectancy are negative; "
            "OOS event expectancy is not positive; most populated years are negative."
        )
    elif full_pos and oos_pos and oos_events >= MIN_EVENTS and pos_years > neg_years:
        raw = "A"
        raw_reason = "Full-horizon and OOS event expectancy are positive with OOS event floor met. Still not cost-complete."
    else:
        raw = "B"
        raw_reason = "Full-horizon RAW evidence is mixed or OOS/stability do not confirm a single direction."

    broker = "D"
    broker_reason = (
        "Broker-realistic evidence is incomplete: cost AND-gate is not ready, "
        f"simulated fills={executable_fills}, commission UNKNOWN, historical Bid/Ask unavailable."
    )
    if not cost_ready and raw == "A":
        overall = "B"
        overall_reason = "RAW looks supportive but costs are incomplete, so overall cannot be A."
    else:
        overall = raw
        overall_reason = raw_reason if raw != "A" else "RAW supportive; broker-realistic remains D."
    return {
        "strategy_raw_evidence": raw,
        "strategy_raw_reason": raw_reason,
        "broker_realistic_evidence": broker,
        "broker_realistic_reason": broker_reason,
        "overall": overall,
        "overall_reason": overall_reason,
        "labels": {
            "A": "SUPPORTIVE EVIDENCE",
            "B": "MIXED / CONDITIONAL",
            "C": "NEGATIVE EVIDENCE",
            "D": "INSUFFICIENT EVIDENCE",
        },
        "profitability_verdict": "NOT_ISSUED",
        "cost_ready_for_validation": cost_ready,
    }


def _compare_windows(full_rows: list[dict[str, Any]], last180: list[dict[str, Any]], p38: dict[str, Any]) -> dict[str, Any]:
    def pack(rows: list[dict[str, Any]], days: float) -> dict[str, Any]:
        eids = {r.get("mechanical_event_id") for r in rows if r.get("mechanical_event_id") is not None}
        reps = event_representatives([{**r, "event_cluster_id": r.get("mechanical_event_id")} for r in rows]) if rows else []
        return {
            "signals": len(rows),
            "events": len(eids),
            "BUY": sum(1 for r in rows if str(r.get("side")).upper() == "BUY"),
            "SELL": sum(1 for r in rows if str(r.get("side")).upper() == "SELL"),
            "signal": _perf(rows, days) if rows else {},
            "event": _perf(reps, days) if reps else {},
        }

    full_days = 1.0
    if full_rows:
        a = _parse_ts(full_rows[0]["timestamp"])
        b = _parse_ts(full_rows[-1]["timestamp"])
        if a is not None and b is not None:
            full_days = max(float((b - a).total_seconds() / 86400.0), 1.0)
    d180 = float(EVAL_DAYS)
    full_pack = pack(full_rows, full_days)
    last_pack = pack(last180, d180)
    p38_raw = ((p38.get("strategy_evaluation") or {}).get("raw") or {})
    p38_ev = p38.get("event_sufficiency") or {}
    full_exp = (full_pack.get("event") or {}).get("expectancy_R")
    last_exp = (last_pack.get("event") or {}).get("expectancy_R")
    representative = False
    materially_different = False
    more_favorable = None
    if full_exp is not None and last_exp is not None:
        materially_different = abs(float(last_exp) - float(full_exp)) >= 0.15
        representative = not materially_different
        more_favorable = "180d" if float(last_exp) > float(full_exp) else "full_tape" if float(full_exp) > float(last_exp) else "similar"
    return {
        "full_tape": full_pack,
        "latest_180d_of_full_scan": last_pack,
        "phase38_isolated_180d_sliced_enrich": {
            "signals": p38_raw.get("n") or p38_ev.get("raw_setups"),
            "events": p38_ev.get("event_count"),
            "expectancy_R": p38_raw.get("expectancy_R"),
            "note": (
                "Phase 38 enriched only the last 180 days. Phase 40 last-180d rows come from a "
                "full-tape enrich + bounded window. Timestamps may differ; that is expected."
            ),
        },
        "representative": representative,
        "materially_different": materially_different,
        "more_favorable_window": more_favorable,
        "do_not_treat_180d_as_full_tape": True,
    }


def blocker_matrix(p36: dict[str, Any], p38: dict[str, Any], p39: dict[str, Any], p40: dict[str, Any]) -> list[dict[str, Any]]:
    def cell(phase36: Any, phase38: Any, phase39: Any, phase40: Any, status: str) -> dict[str, Any]:
        return {
            "Phase36": phase36,
            "Phase38": phase38,
            "Phase39": phase39,
            "Phase40": phase40,
            "Status": status,
        }

    ev40 = (p40.get("events") or {}).get("event_count")
    oos40 = ((p40.get("oos_sufficiency") or {}).get("events"))
    raw_class = (p40.get("classification") or {}).get("strategy_raw_evidence")
    cost = p39.get("cost_completeness") or p40.get("cost_completeness") or {}
    return [
        {
            "Requirement": "M5 horizon",
            **cell("~14.88d", "1291.4d acquired", "1291.38d reused", p40.get("tape_days"), "MET_PREFERRED"),
        },
        {
            "Requirement": "mechanical events",
            **cell(6, 43, 43, ev40, "SUFFICIENT" if int(ev40 or 0) >= MIN_EVENTS else "INSUFFICIENT"),
        },
        {
            "Requirement": "OOS events",
            **cell("n/a on 15d", "full-tape scan not run", 11, oos40, (p40.get("oos_sufficiency") or {}).get("classification")),
        },
        {
            "Requirement": "M15",
            **cell("none", "OBSERVED", "reused", "reused", "OBSERVED"),
        },
        {
            "Requirement": "symbol binding",
            **cell("NOT_PROVEN", "NOT_PROVEN", "NOT_PROVEN", "NOT_PROVEN", "NOT_PROVEN"),
        },
        {
            "Requirement": "symbol economics",
            **cell("UNKNOWN/PARTIAL", "CURRENT_SNAPSHOT", "CURRENT_SNAPSHOT", "reused Phase 39", "PARTIAL"),
        },
        {
            "Requirement": "Bid/Ask",
            **cell("PROXY", "unavailable on eval tape", "unavailable on eval tape", "unavailable on eval tape", "UNAVAILABLE"),
        },
        {
            "Requirement": "spread",
            **cell("PROXY", "NOT_OBSERVED on eval tape", "PARTIAL current ticks / PROXY tape", "PROXY eval tape", "PROXY"),
        },
        {
            "Requirement": "commission",
            **cell("UNKNOWN", "UNKNOWN", "OBSERVED_ZERO_NOT_PROVEN", "UNKNOWN", "UNKNOWN"),
        },
        {
            "Requirement": "swap",
            **cell("BROKER_RATE_ONLY", "BROKER_RATE_ONLY", "historical UNKNOWN", "historical UNKNOWN", "UNKNOWN"),
        },
        {
            "Requirement": "slippage",
            **cell("MODELED", "MODELED", "MODELED pairs=0", "MODELED", "MODELED"),
        },
        {
            "Requirement": "execution",
            **cell("DEAL_FILL_TAPE_ONLY", "DEAL_FILL_TAPE_ONLY", "PARTIAL_EXECUTION_EVIDENCE", "not re-probed", "PARTIAL"),
        },
        {
            "Requirement": "cost AND-gate",
            **cell("0/8", "0/8", "0/8", f"{cost.get('complete_count', 0)}/8", "INCOMPLETE"),
        },
        {
            "Requirement": "statistical sufficiency",
            **cell("INSUFFICIENT", "180d events>=30; full tape not scanned", "OOS 11 INSUFFICIENT", (p40.get("oos_sufficiency") or {}).get("classification"), (p40.get("oos_sufficiency") or {}).get("classification")),
        },
        {
            "Requirement": "strategy evidence classification",
            **cell("D INSUFFICIENT_EVIDENCE", "not classified (acquisition)", "not a verdict", raw_class, raw_class),
        },
    ]


def write_markdown(root: Path, payload: dict[str, Any]) -> Path:
    c = payload.get("classification") or {}
    scan = payload.get("scan") or {}
    raw = payload.get("raw_performance") or {}
    ev = payload.get("events") or {}
    oos = payload.get("oos_sufficiency") or {}
    exe = payload.get("executable") or {}
    cmp_ = payload.get("comparison_180_vs_full") or {}
    labels = c.get("labels") or {}
    overall = c.get("overall")
    md = f"""# Phase 40 — Full-Horizon Unchanged Strategy Validation

**STATUS:** `{payload.get("status")}`
**Class:** RESEARCH ONLY
**Tape:** `{PHASE38_M5}`
**Bars loaded:** `{scan.get("tape_rows_loaded")}`
**Scan completed:** `{scan.get("completed")}`
**Strategy RAW evidence:** `{c.get("strategy_raw_evidence")}` — {labels.get(c.get("strategy_raw_evidence"), "")}
**Broker-realistic evidence:** `{c.get("broker_realistic_evidence")}` — {labels.get(c.get("broker_realistic_evidence"), "")}
**Overall research classification:** `{overall}` — {labels.get(overall, "")}
**cost_ready_for_validation:** `{payload.get("cost_completeness", {}).get("cost_ready_for_validation")}`
**FINAL_GATE:** `{payload.get("FINAL_GATE")}`
**Production changes:** `{payload.get("production_changes")}`
**Frozen dataset changed:** `{payload.get("datasets_changed")}`

STOP AFTER PHASE 40. DO NOT START PHASE 41.
DO NOT OPTIMIZE. DO NOT TRADE. DO NOT CHANGE PRODUCTION.

This phase does **not** issue a profitability verdict.
This phase does **not** issue an unprofitability verdict.
`profitability_verdict`: `{c.get("profitability_verdict")}`.

---

## What this phase is

The complete available XAUUSD_i M5 tape is now long enough for a serious **unchanged-strategy** research evaluation.

Lack of broker cost completeness is **not** a reason to skip RAW analysis.
RAW results are **not** broker-realistic results.

Layers (never merged):

1. RAW / theoretical strategy behavior
2. EXECUTABLE / RiskGate-filtered behavior
3. MODELED cost sensitivity
4. BROKER-OBSERVED evidence

---

## Data

- Path: `{PHASE38_M5}`
- Rows loaded: `{scan.get("tape_rows_loaded")}`
- Start: `{scan.get("start")}`
- End: `{scan.get("end")}`
- Days: `{payload.get("tape_days")}`
- Fingerprint: `{payload.get("tape_fingerprint")}`
- Chronological: `{(payload.get("data_quality") or {}).get("abnormal_timestamp_ordering") is False}`
- Duplicates: `{(payload.get("data_quality") or {}).get("duplicate_timestamps")}`
- Malformed OHLC: `{(payload.get("data_quality") or {}).get("malformed_ohlc")}`
- Impossible OHLC: `{(payload.get("data_quality") or {}).get("impossible_ohlc")}`
- Zero volume: `{(payload.get("data_quality") or {}).get("zero_volume")}`
- Gaps: `{(payload.get("data_quality") or {}).get("gap_classification")}`

Bars were **not** repaired or fabricated. The source parquet was **not** modified.
Frozen Phase 28 `data/XAUUSD_i_5m.parquet` fingerprint remains `{EXPECTED_CANONICAL_FINGERPRINT}`.

## Strategy (CODE WINS)

{(payload.get("strategy_fingerprint") or {})}

Scan window `{SCAN_WINDOW_BARS}` bars is a bounded lookback matching production indicator windows (ATR 14, ATR percentile 252, swings 250, FVG 80, Asian same UTC day). It is **not** a shortened horizon and **not** random sampling. Warmup `{WARMUP}` bars is the official scanner floor, not a dataset cut.

## RAW scan

- Completed: `{scan.get("completed")}`
- NY bars scanned: `{scan.get("ny_bars_scanned")}`
- RAW signals: `{scan.get("signals")}`
- BUY: `{scan.get("buy")}`
- SELL: `{scan.get("sell")}`
- WAIT (NY bars with no signal): `{scan.get("wait")}`
- Mechanical events: `{ev.get("event_count")}`
- Signals/event mean: `{(ev.get("signals_per_event") or {}).get("mean")}`
- Full-tape event floor >=30: `{bool(int(ev.get("event_count") or 0) >= MIN_EVENTS)}`
- Frequency: `{payload.get("frequency")}`

Every RAW signal is persisted at `{PHASE40_SETUPS_JSONL}` with timestamp, direction, event id, entry, sweep, Asian range, SL, TP, planned R, outcome, MFE, MAE, duration.

## RAW_THEORETICAL performance

{raw}

No cost adjustment in this block.

## Events / dependence

{payload.get("dependence")}

Signal count is **not** the independent sample size.

## Walk-forward (predeclared 60/20/20)

Declaration: `{WALKFORWARD_DECLARATION}`

{payload.get("walk_forward")}

## OOS sufficiency

{oos}

SUFFICIENT here means the OOS **event count** meets the floor. It does **not** mean the strategy is valid.

## Stability / direction / session

Yearly: {(payload.get("stability") or {}).get("yearly")}

Quarterly: {(payload.get("stability") or {}).get("quarterly")}

Monthly: omitted from this narrative if large; see JSON `stability.monthly`.

Regime: {(payload.get("stability") or {}).get("regime")}

Direction: {payload.get("direction")}

Session: {payload.get("session")}

If signals concentrate in NY 15–16 UTC, that is **expected by design**. It is not independent evidence that the window is optimal. This phase does not optimize session boundaries.

## EXECUTABLE (unchanged RiskGate)

{exe}

If commission is UNKNOWN, fills are not fabricated.

## MODELED cost sensitivity

Commission = **UNKNOWN** (not invented).
Swap historical = **UNKNOWN** (not applied).

{payload.get("cost_sensitivity")}

## Bootstrap (event-level, descriptive)

{payload.get("statistics")}

This is DESCRIPTIVE. It is not a significance claim unless the methodology actually supports one (it does not, while costs are incomplete and events remain clustered).

## Robustness (predeclared only)

{payload.get("robustness")}

These diagnostics were **not** used to select a preferred configuration. Production remains unchanged.

## 180-day vs full tape

{cmp_}

## Classification

- Strategy RAW evidence: **{c.get("strategy_raw_evidence")}** — {c.get("strategy_raw_reason")}
- Broker-realistic evidence: **{c.get("broker_realistic_evidence")}** — {c.get("broker_realistic_reason")}
- Overall: **{overall}** — {c.get("overall_reason")}

A = SUPPORTIVE EVIDENCE  
B = MIXED / CONDITIONAL  
C = NEGATIVE EVIDENCE  
D = INSUFFICIENT EVIDENCE

## Blocker matrix

See JSON `blocker_matrix`.

## Stop

STOP AFTER PHASE 40.
DO NOT START PHASE 41.
DO NOT OPTIMIZE.
DO NOT TRADE.
DO NOT MODIFY PRODUCTION.
"""
    path = root / PHASE40_MD
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(md, encoding="utf-8")
    return path


def _patch_truth_docs(root: Path, payload: dict[str, Any]) -> None:
    c = payload.get("classification") or {}
    p40_line = (
        "Phase 40 (`docs_v2/02_research/PHASE40_FULL_HORIZON_VALIDATION.md`) is research-only "
        "full-horizon unchanged-strategy validation on the Phase 38 XAUUSD_i M5 tape. "
        "It does not authorize live trading, overwrite the frozen M5 snapshot, optimize, or start Phase 41."
    )
    src = root / "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md"
    text = src.read_text(encoding="utf-8")
    old39 = (
        "Phase 39 (`docs_v2/02_research/PHASE39_BROKER_ECONOMICS_EXECUTION.md`) is research-only broker "
        "economics and execution evidence resolution on the Phase 38 XAUUSD_i tape. It does not authorize "
        "live trading, overwrite the frozen M5 snapshot, or start Phase 40."
    )
    new39 = (
        "Phase 39 (`docs_v2/02_research/PHASE39_BROKER_ECONOMICS_EXECUTION.md`) is research-only broker "
        "economics and execution evidence resolution on the Phase 38 XAUUSD_i tape. It does not authorize "
        "live trading, overwrite the frozen M5 snapshot, or change production."
    )
    if old39 in text and p40_line not in text:
        text = text.replace(old39, new39 + "\n\n" + p40_line)
        src.write_text(text, encoding="utf-8")
    elif p40_line not in text and new39 in text:
        text = text.replace(new39, new39 + "\n\n" + p40_line)
        src.write_text(text, encoding="utf-8")

    cfg = root / "docs_v2/01_truth/CONFIGURATION_TRUTH.md"
    ctext = cfg.read_text(encoding="utf-8")
    ctext = ctext.replace(
        "| Phase 39 broker economics | `run_phase39_collection()` | n/a | RESEARCH; cost/execution evidence + labeled sensitivity; no bot/orders/.env | **PASS**; Phase 40 not started |",
        "| Phase 39 broker economics | `run_phase39_collection()` | n/a | RESEARCH; cost/execution evidence + labeled sensitivity; no bot/orders/.env | **PASS** |",
    )
    row40 = (
        "| Phase 40 full-horizon validation | `run_phase40_collection()` | n/a | "
        "RESEARCH; full 1291-day unchanged gold_ny_sweep on phase38 XAUUSD_i M5; no bot/orders/.env | "
        f"**{payload.get('status')}**; Phase 41 not started |"
    )
    if "Phase 40 full-horizon validation" not in ctext:
        ctext = ctext.replace(
            "| PA M5 `MIN_CONFIDENCE`",
            row40 + "\n| PA M5 `MIN_CONFIDENCE`",
        )
    cfg.write_text(ctext, encoding="utf-8")

    bnd = root / "docs_v2/01_truth/PRODUCTION_RESEARCH_BOUNDARY.md"
    btext = bnd.read_text(encoding="utf-8")
    line = (
        "`tradingbot/backtest/phase40_full_horizon_validation.py` — **RESEARCH_ONLY** full-horizon "
        "unchanged-strategy validation on the Phase 38 XAUUSD_i M5 tape; does not overwrite Phase 28 M5.\n"
    )
    if "phase40_full_horizon_validation.py" not in btext:
        btext = btext.replace(
            "`tradingbot/backtest/phase39_broker_economics_execution.py` — **RESEARCH_ONLY** broker economics/execution evidence; may attach identified MT5 read-only; does not overwrite Phase 28 M5.  \n",
            "`tradingbot/backtest/phase39_broker_economics_execution.py` — **RESEARCH_ONLY** broker economics/execution evidence; may attach identified MT5 read-only; does not overwrite Phase 28 M5.  \n"
            + line,
        )
        bnd.write_text(btext, encoding="utf-8")

    ku = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    ktext = ku.read_text(encoding="utf-8")
    ktext = ktext.replace("| Phase 40 started | **NO** |", "| Phase 40 started | **YES** |")
    block = f"""

## Full-horizon unchanged strategy validation (Phase 40)

| Claim | Status |
|---|---|
| Phase 40 status | **{payload.get("status")}** |
| Frozen Phase 28/30 M5 overwritten | **NO** |
| Silent XAUUSD map | **NO** |
| Full tape scan completed | **{scan_completed_label(payload)}** |
| Strategy RAW classification | **{c.get("strategy_raw_evidence")}** |
| Broker-realistic classification | **{c.get("broker_realistic_evidence")}** |
| Profitability verdict | **NOT ISSUED** |
| Phase 41 started | **NO** |
"""
    if "## Full-horizon unchanged strategy validation (Phase 40)" not in ktext:
        ktext = ktext.rstrip() + block
        ku.write_text(ktext, encoding="utf-8")


def scan_completed_label(payload: dict[str, Any]) -> str:
    scan = payload.get("scan") or {}
    return "YES" if scan.get("completed") else f"NO — coverage={scan.get('last_cursor')}"


def run_phase40_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    tape_path = root / PHASE38_M5
    frozen_path = root / CANONICAL_PARQUET
    frozen_fp = file_fingerprint(frozen_path) if frozen_path.is_file() else UNKNOWN
    frozen_ok = frozen_fp == EXPECTED_CANONICAL_FINGERPRINT
    p38 = _safe_load_json(root / PHASE38_JSON) or {}
    p39 = _safe_load_json(root / PHASE39_JSON) or {}
    p36 = _safe_load_json(root / "logs/phase36_strategy_verdict.json") or {}
    p16 = _safe_load_json(root / PHASE2716_JSON) or {}

    if not tape_path.is_file():
        payload = {
            "phase": PHASE,
            "timestamp_utc": _utc_now(),
            "status": "BLOCKED",
            "research_only": True,
            "reason": f"missing {PHASE38_M5}",
            "FINAL_GATE": BLOCKED,
            "phase_41_started": False,
            "production_changes": "NONE",
        }
        _write_json(root / PHASE40_JSON, _redact(payload))
        write_markdown(root, payload)
        return payload

    m5 = load_parquet_utc(tape_path)
    tape_fp = content_fingerprint(m5)
    tape_days = _duration_days(m5)
    n = int(len(m5))
    quality = audit_dataset(m5, timeframe="M5", path=str(tape_path))
    quality["source_modified"] = False
    quality["bars_repaired"] = False
    quality["bars_fabricated"] = False

    splits = chronological_index_splits(n)
    split_ts = {}
    idx = pd.to_datetime(m5.index, utc=True)
    for name, sp in splits.items():
        a, b = int(sp["start_index"]), int(sp["end_index"])
        split_ts[name] = {
            **sp,
            "start_ts": str(idx[min(a, n - 1)]),
            "end_ts": str(idx[min(max(b - 1, a), n - 1)]),
            "rows": max(b - a, 0),
            "days": round(float((idx[min(max(b - 1, a), n - 1)] - idx[min(a, n - 1)]).total_seconds() / 86400.0), 4),
        }

    fingerprint = code_strategy_fingerprint(root)
    binding = classify_dataset_binding(
        CANONICAL_SYMBOL,
        configured_symbol=PRIMARY_SYMBOL,
        dataset_symbol_map={},
    )
    frozen_fp_before = file_fingerprint(frozen_path) if frozen_path.is_file() else UNKNOWN

    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        enriched = _enrich_frame(m5)
    scanned = _resume_or_scan(enriched, root=root, tape_fp=tape_fp)
    setups = list(scanned.get("setups") or [])
    setups = _attach_official_asian_range(setups, enriched, symbol=PRIMARY_SYMBOL)
    for i, s in enumerate(setups):
        s["signal_id"] = s.get("signal_id") or f"P40-{i+1:04d}"
        s["side"] = s.get("side") or s.get("direction")
        if s.get("planned_rr") is None:
            try:
                risk = abs(float(s["entry_price"]) - float(s["stop_loss"]))
                if risk > 0:
                    s["planned_rr"] = abs(float(s["take_profit"]) - float(s["entry_price"])) / risk
            except (TypeError, ValueError, KeyError):
                pass

    labeled = []
    skipped_range = 0
    for s in setups:
        if s.get("asian_high") is None or s.get("asian_low") is None:
            skipped_range += 1
            continue
        labeled.append(s)
    labeled = assign_mechanical_events(labeled) if labeled else []
    for r in labeled:
        r["event_cluster_id"] = r.get("mechanical_event_id")
        ts = _parse_ts(r.get("timestamp"))
        if ts is None:
            r["fold"] = "UNKNOWN"
            continue
        loc = int(idx.get_indexer([ts], method="nearest")[0])
        r["closed_bar_index"] = r.get("closed_bar_index", loc)
        r["fold"] = "OOS"
        for name, sp in splits.items():
            if int(sp["start_index"]) <= loc < int(sp["end_index"]):
                r["fold"] = name
                break

    ev = event_metrics(labeled) if labeled else {"event_count": 0, "signal_count": 0, "signals_per_event": {}}
    reps = event_representatives(labeled) if labeled else []
    raw_perf = _perf(labeled, tape_days) if labeled else {"setups": 0, "label": "RAW_THEORETICAL"}
    event_perf = _perf(reps, tape_days) if reps else {"setups": 0, "label": "RAW_THEORETICAL_EVENT"}
    if event_perf:
        event_perf["label"] = "RAW_THEORETICAL_EVENT"

    end_ts = idx.max()
    cut_180 = end_ts - pd.Timedelta(days=EVAL_DAYS)
    last180 = [r for r in labeled if (_parse_ts(r.get("timestamp")) is not None and _parse_ts(r["timestamp"]) >= cut_180)]

    folds = {}
    for name in ("TRAIN", "VALIDATION", "OOS"):
        rows = [r for r in labeled if r.get("fold") == name]
        eids = {r.get("mechanical_event_id") for r in rows if r.get("mechanical_event_id") is not None}
        fold_reps = event_representatives([{**r, "event_cluster_id": r.get("mechanical_event_id")} for r in rows]) if rows else []
        meta = split_ts[name]
        folds[name] = {
            "date_range": [meta["start_ts"], meta["end_ts"]],
            "bars": meta["rows"],
            "days": meta["days"],
            "signals": len(rows),
            "events": len(eids),
            "BUY": sum(1 for r in rows if str(r.get("side")).upper() == "BUY"),
            "SELL": sum(1 for r in rows if str(r.get("side")).upper() == "SELL"),
            "signal_metrics": _perf(rows, float(meta["days"])) if rows else {},
            "event_metrics": _perf(fold_reps, float(meta["days"])) if fold_reps else {},
            "frequency": _frequency(len(rows), float(meta["days"])),
        }

    oos_rows = [r for r in labeled if r.get("fold") == "OOS"]
    oos_events = folds["OOS"]["events"]
    oos_days = float(split_ts["OOS"]["days"])
    oos_ts = [_parse_ts(r["timestamp"]) for r in oos_rows if _parse_ts(r.get("timestamp"))]
    oos_months = len({f"{t.year:04d}-{t.month:02d}" for t in oos_ts}) if oos_ts else 0
    oos_weeks = len({f"{t.isocalendar().year:04d}-W{int(t.isocalendar().week):02d}" for t in oos_ts}) if oos_ts else 0
    oos_block = {
        "signals": len(oos_rows),
        "events": oos_events,
        "calendar_days": oos_days,
        "months": oos_months,
        "weeks": oos_weeks,
        "classification": classify_oos_sample(events=int(oos_events), signals=len(oos_rows), days=oos_days),
        "primary_unit": "mechanical_event",
        "note": "Event count is the independence-aware sample unit. Meeting the event floor is not a validity claim.",
    }

    yearly = _period_stats(labeled, kind="year")
    quarterly = _period_stats(labeled, kind="quarter")
    monthly = _period_stats(labeled, kind="month")
    regimes = _regime_stats(labeled)

    hours = Counter(int(r.get("hour_utc") if r.get("hour_utc") is not None else -1) for r in labeled)
    session_block = {
        "production_session": "NY 15–16 UTC (unchanged)",
        "hour_utc_counts": dict(sorted((str(k), v) for k, v in hours.items())),
        "expected_concentration": "NY 15–16 UTC",
        "note": (
            "Concentration in NY 15–16 UTC is expected because the production strategy only emits "
            "in that window. It is not evidence that the window is optimal. Session boundaries were not optimized."
        ),
    }

    sl_groups = Counter()
    tp_groups = Counter()
    sweep_groups = Counter()
    for r in labeled:
        if r.get("stop_loss") is not None:
            sl_groups[round(float(r["stop_loss"]), 2)] += 1
        if r.get("take_profit") is not None:
            tp_groups[round(float(r["take_profit"]), 2)] += 1
        if r.get("sweep_high") is not None and r.get("sweep_low") is not None:
            sweep_groups[(round(float(r["sweep_high"]), 2), round(float(r["sweep_low"]), 2))] += 1
    dependence = {
        **ev,
        "same_event_reentries": int(sum(1 for r in labeled if r.get("repeated_signal_within_same_event"))),
        "same_direction_reentries": int(sum(1 for r in labeled if r.get("same_direction_reentry"))),
        "overlapping_holds": int(sum(1 for r in labeled if r.get("overlapping_holding_period"))),
        "shared_sweep_groups": int(sum(1 for n in sweep_groups.values() if n > 1)),
        "shared_sl_groups": int(sum(1 for n in sl_groups.values() if n > 1)),
        "shared_tp_groups": int(sum(1 for n in tp_groups.values() if n > 1)),
        "independence_claimed": False,
        "do_not_treat_signals_as_iid": True,
    }

    cost39 = p39.get("cost_completeness") or p38.get("cost_completeness") or {}
    cost_ready = bool(cost39.get("cost_ready_for_validation"))
    commission_unknown = True

    prev40 = _safe_load_json(root / PHASE40_JSON) or {}
    prev_exe = prev40.get("executable") or {}
    if (
        prev_exe.get("ran")
        and int(prev_exe.get("candidates") or -1) == len(setups)
        and prev_exe.get("mixed_with_raw") is False
        and str(prev40.get("tape_fingerprint")) == tape_fp
    ):
        executable = dict(prev_exe)
        executable["reused_prior_phase40_executable"] = True
    else:
        research = build_research_configuration()
        h4 = load_parquet_utc(root / H4_CONTEXT_PARQUET) if (root / H4_CONTEXT_PARQUET).is_file() else None
        engine = _build_research_engine(enriched, research, h4=h4)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            executable = asyncio.run(evaluate_executable_edge(engine, setups, research))
        reasons = executable.get("rejection_reasons") or {}
        attr = Counter()
        for reason, cnt in reasons.items():
            attr[classify_reject(str(reason))] += int(cnt)
        fills = int(executable.get("executed_simulated_trades") or 0)
        executable = {
            "book": "EXECUTABLE",
            "ran": True,
            "candidates": int(executable.get("candidates") or len(setups)),
            "allowed": int(executable.get("allowed") or 0),
            "rejected": int(executable.get("rejected") or 0),
            "rejection_reasons": reasons,
            "reject_attribution": dict(attr),
            "executed_simulated_trades": fills,
            "fills_fabricated": False,
            "mixed_with_raw": False,
            "status": (
                "EXECUTABLE_BLOCKED_BY_UNKNOWN_COMMISSION"
                if commission_unknown
                else "EXECUTABLE"
            ),
            "broker_fill_note": executable.get("broker_fill_note"),
            "gates_unchanged": {
                "risk": True,
                "lot": True,
                "meta_threshold": True,
                "atr": True,
                "spread": True,
                "news": True,
                "cooldown": True,
                "max_trades_per_day": True,
            },
        }

    cfg_bt = BacktestConfig()
    spread_base = float(getattr(cfg_bt, "spread_pips", 2.5) or 2.5)
    slip_base = float(getattr(cfg_bt, "slippage_pips", 0.8) or 0.8)
    scenarios = []
    for spec in SENSITIVITY_DECLARATION["scenarios"]:
        sp = spread_base * float(spec["spread_mult"])
        slp = slip_base * float(spec["slip_mult"])
        priced = []
        for r in labeled:
            rr = apply_modeled_cost(r, spread_pips=sp, slip_pips=slp) if spec["id"] != "RAW_NO_COST" else r.get("r_multiple")
            priced.append({**r, "r_multiple": rr})
        event_priced = []
        for r in reps:
            rr = apply_modeled_cost(r, spread_pips=sp, slip_pips=slp) if spec["id"] != "RAW_NO_COST" else r.get("r_multiple")
            event_priced.append({**r, "r_multiple": rr})
        scenarios.append(
            {
                "id": spec["id"],
                "spread_pips": sp,
                "slippage_pips": slp,
                "commission": "UNKNOWN_NOT_APPLIED",
                "signal_expectancy_R": _expectancy(priced),
                "event_expectancy_R": _expectancy(event_priced),
            }
        )
    cost_sensitivity = {
        "label": "MODELED / SCENARIO — not broker-realistic",
        "commission": "UNKNOWN",
        "declaration": SENSITIVITY_DECLARATION,
        "scenarios": scenarios,
    }

    rng = np.random.default_rng(RNG_SEED)
    event_r = [float(r["r_multiple"]) for r in reps if r.get("r_multiple") is not None]
    if event_r:
        paths = run_bootstrap(event_r, rng, N_PATHS)
        boot = summarize_paths(paths)
        boot["sampling_unit"] = "mechanical_event"
        boot["n_events"] = len(event_r)
        boot["seed"] = RNG_SEED
        boot["kind"] = "DESCRIPTIVE"
        boot["inferential_claim"] = False
        boot["statistical_significance_claimed"] = False
        boot["note"] = "Event-level bootstrap. Clustered signals were not treated as independent."
    else:
        boot = {"ran": False, "reason": "no resolved event R"}

    next_bar_rows = []
    sl_wider_rows = []
    rr14_rows = []
    rr16_rows = []
    for r in labeled:
        i = int(r.get("closed_bar_index") if r.get("closed_bar_index") is not None else r.get("cursor") or 0)
        direction = str(r.get("side") or r.get("direction"))
        entry = float(r.get("entry_price") or 0)
        sl = float(r.get("stop_loss") or 0)
        tp = float(r.get("take_profit") or 0)
        if i + 1 < len(enriched):
            fill = float(enriched.iloc[i + 1]["open"])
            nxt = _walk_with_prices(enriched, i, direction, fill, sl, tp, from_idx=i + 1)
            next_bar_rows.append({**r, "r_multiple": nxt.get("r_multiple"), "outcome": nxt.get("outcome")})
        risk = abs(entry - sl)
        if risk > 0:
            buy = str(direction).upper() == "BUY"
            sl_w = sl - 0.05 * risk if buy else sl + 0.05 * risk
            wide = theoretical_outcome(enriched, i, direction, entry, sl_w, tp)
            sl_wider_rows.append({**r, "r_multiple": wide.get("r_multiple"), "outcome": wide.get("outcome")})
            sign = 1.0 if buy else -1.0
            tp14 = entry + sign * 1.4 * risk
            tp16 = entry + sign * 1.6 * risk
            a = theoretical_outcome(enriched, i, direction, entry, sl, tp14)
            b = theoretical_outcome(enriched, i, direction, entry, sl, tp16)
            rr14_rows.append({**r, "r_multiple": a.get("r_multiple"), "outcome": a.get("outcome")})
            rr16_rows.append({**r, "r_multiple": b.get("r_multiple"), "outcome": b.get("outcome")})
    robustness = {
        "declaration": ROBUSTNESS_DECLARATION,
        "official_signal_expectancy_R": raw_perf.get("expectancy_R"),
        "official_event_expectancy_R": event_perf.get("expectancy_R"),
        "next_bar_open_signal_expectancy_R": _expectancy(next_bar_rows),
        "sl_wider_5pct_signal_expectancy_R": _expectancy(sl_wider_rows),
        "rr_1_4_signal_expectancy_R": _expectancy(rr14_rows),
        "rr_1_6_signal_expectancy_R": _expectancy(rr16_rows),
        "selected_as_preferred": False,
        "production_unchanged": True,
        "note": "Predeclared diagnostics only. Not a parameter search. Official configuration remains unchanged.",
    }

    comparison = _compare_windows(labeled, last180, p38)
    oos_event_exp = (folds["OOS"].get("event_metrics") or {}).get("expectancy_R")
    frozen_fp_after = file_fingerprint(frozen_path) if frozen_path.is_file() else UNKNOWN
    ok_immut = frozen_fp_before == frozen_fp_after == EXPECTED_CANONICAL_FINGERPRINT
    issues = [] if ok_immut else ["frozen Phase 28 M5 fingerprint changed during Phase 40"]

    classification = classify_research(
        event_n=int(ev.get("event_count") or 0),
        event_exp=event_perf.get("expectancy_R"),
        signal_exp=raw_perf.get("expectancy_R"),
        oos_events=int(oos_events),
        oos_exp=oos_event_exp,
        yearly=yearly,
        cost_ready=cost_ready,
        executable_fills=int(executable.get("executed_simulated_trades") or 0),
    )

    scan_block = {
        "tape": PHASE38_M5,
        "tape_rows_loaded": n,
        "start": str(idx.min()),
        "end": str(idx.max()),
        "window_bars": SCAN_WINDOW_BARS,
        "warmup_bars": WARMUP,
        "horizon_shortened": False,
        "sampled": False,
        "random_sample": False,
        "completed": bool(scanned.get("completed")) and n == int(len(m5)),
        "last_cursor": scanned.get("end_cursor"),
        "ny_bars_scanned": scanned.get("ny_bars_scanned"),
        "signals": len(labeled),
        "raw_setups_including_missing_asian": len(setups),
        "setups_missing_asian_range": skipped_range,
        "buy": scanned.get("buy"),
        "sell": scanned.get("sell"),
        "wait": scanned.get("wait"),
        "reused_checkpoint": bool(scanned.get("reused_checkpoint")),
        "resumed": bool(scanned.get("resumed")),
        "lookahead_protection": True,
        "closed_bar_only": True,
        "same_bar_sl_before_tp": True,
        "jsonl": PHASE40_SETUPS_JSONL,
    }

    payload: dict[str, Any] = {
        "schema_version": 1,
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "git_head": _git_head(root),
        "status": "PASS" if scan_block["completed"] else "PARTIAL_COVERAGE",
        "research_only": True,
        "live_trading_authorized": False,
        "production_changes": "NONE",
        "parameters_optimized": False,
        "strategy_changed": False,
        "riskgate_changed": False,
        "ml_changed": False,
        "env_accessed": False,
        "silent_xauusd_mapping": False,
        "ev_eq_01": "NOT_PROVEN",
        "FINAL_GATE": BLOCKED,
        "phase_41_started": False,
        "datasets_changed": False,
        "dataset_symbol_map": {},
        "tape_days": round(tape_days, 6),
        "tape_fingerprint": tape_fp,
        "fingerprints": {
            "phase28_m5": frozen_fp,
            "phase28_m5_unchanged": frozen_ok,
            "expected": EXPECTED_CANONICAL_FINGERPRINT,
        },
        "immutability": {
            "unchanged": ok_immut,
            "issues": issues,
            "phase28_frozen_unchanged": frozen_ok,
        },
        "dataset_binding": {
            "empty_map": True,
            "xauusd_merged": False,
            "logical_xauusd_used": False,
            "canonical_symbol": CANONICAL_SYMBOL,
            "binding": binding.to_dict(),
        },
        "data_quality": quality,
        "strategy_fingerprint": fingerprint,
        "scan": scan_block,
        "frequency": _frequency(len(labeled), tape_days),
        "raw_signal": {
            "book": "RAW_SIGNAL",
            "n": len(labeled),
            "BUY": sum(1 for r in labeled if str(r.get("side")).upper() == "BUY"),
            "SELL": sum(1 for r in labeled if str(r.get("side")).upper() == "SELL"),
            "WAIT": scanned.get("wait"),
            "cost_adjusted": False,
        },
        "events": {
            **ev,
            "event_definition": "(UTC date, asian_high, asian_low, side)",
            "floor_met": int(ev.get("event_count") or 0) >= MIN_EVENTS,
            "event_performance": event_perf,
        },
        "dependence": dependence,
        "walk_forward": {
            "declaration": WALKFORWARD_DECLARATION,
            "splits": split_ts,
            "folds": folds,
        },
        "oos_sufficiency": oos_block,
        "stability": {"yearly": yearly, "quarterly": quarterly, "monthly": monthly, "regime": regimes},
        "direction": _direction_block(labeled, tape_days),
        "session": session_block,
        "raw_performance": raw_perf,
        "executable": executable,
        "cost_completeness": {
            "complete_count": int(cost39.get("complete_count") or 0),
            "required_count": int(cost39.get("required_count") or 8),
            "cost_ready_for_validation": cost_ready,
            "gate_weakened": False,
            "classification": cost39.get("classification") or "INCOMPLETE",
            "source": "Phase 39 reuse — Phase 40 does not weaken the AND-gate",
        },
        "cost_sensitivity": cost_sensitivity,
        "statistics": boot,
        "robustness": robustness,
        "comparison_180_vs_full": comparison,
        "classification": classification,
        "safety": {
            "BOT_STARTED": False,
            "ORDERS_SENT": False,
            "SYMBOL_SELECT": False,
            "ENV_READ": False,
            "PRODUCTION_MODIFIED": False,
        },
        "prior_phase16_final_gate": p16.get("FINAL_GATE"),
        "research": {"optimized": False, "logical_xauusd_used": False},
    }
    payload["blocker_matrix"] = blocker_matrix(p36, p38, p39, payload)
    payload = _redact(payload)
    _write_json(root / PHASE40_JSON, payload)
    write_markdown(root, payload)
    _patch_truth_docs(root, payload)
    return payload


if __name__ == "__main__":
    run_phase40_collection(Path.cwd())

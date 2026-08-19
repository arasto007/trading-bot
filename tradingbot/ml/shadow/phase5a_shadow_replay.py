"""Phase 5A — build shadow_trade_record rows from PA replay + ML shadow probe."""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.domain.models import MarketKey

ROOT = Path(__file__).resolve().parents[3]
REPLAY_CACHE = ROOT / "logs" / "phase5a_shadow_replay_records.jsonl"
PA_CACHE = ROOT / "logs" / "phase5a_pa_trades.json"


def _probe_ml_adapter(
    adapter: Any,
    builder: Any,
    df: pd.DataFrame,
    bar_index: int,
) -> tuple[str, float | None]:
    """Fast Phase 9.9 ML shadow probe (same path as ShadowObserver)."""
    if bar_index < 0 or bar_index >= len(df):
        return "HOLD", None
    sl = df.iloc[: bar_index + 1]
    idx = len(sl) - 1
    try:
        feats = builder.compute_at(sl, idx)
        subset = {k: feats.get(k, 0.0) for k in adapter.bundle.feature_order}
        pred = adapter.predict(subset, timestamp=str(sl.index[idx]))
        d = str(getattr(pred, "direction", "HOLD")).upper()
        prob = getattr(pred, "probability", None)
        if prob is None:
            prob = getattr(pred, "confidence", None)
        p = float(prob) if prob is not None else None
        if d in ("BUY", "SELL"):
            return d, p
    except Exception:
        pass
    return "HOLD", None


def _load_pa_cache() -> list[dict[str, Any]] | None:
    if not PA_CACHE.is_file():
        return None
    try:
        return json.loads(PA_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_pa_cache(trades: list[dict[str, Any]]) -> None:
    PA_CACHE.parent.mkdir(parents=True, exist_ok=True)
    PA_CACHE.write_text(json.dumps(trades, indent=2, default=str), encoding="utf-8")


def load_replay_cache() -> list[dict[str, Any]] | None:
    if not REPLAY_CACHE.is_file():
        return None
    rows: list[dict[str, Any]] = []
    for line in REPLAY_CACHE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows if rows else None


def save_replay_cache(records: list[dict[str, Any]]) -> None:
    REPLAY_CACHE.parent.mkdir(parents=True, exist_ok=True)
    with REPLAY_CACHE.open("w", encoding="utf-8") as fh:
        for row in records:
            fh.write(json.dumps(row, default=str) + "\n")


def build_replay_shadow_trade_records(
    df: pd.DataFrame,
    pa_trades: list[dict[str, Any]] | None = None,
    *,
    use_cache: bool = True,
    rebuild: bool = False,
) -> list[dict[str, Any]]:
    """
    Shadow analysis replay: PA closed trades + ML prediction at entry bar.

    Uses frozen Phase 9.9 MLAdapter (shadow path). Output matches shadow_trade_record schema.
    """
    if use_cache and not rebuild:
        cached = load_replay_cache()
        if cached and len(cached) >= 100:
            return cached

    if pa_trades is None:
        pa_trades = _load_pa_cache()
    if pa_trades is None:
        from logs.phase_c_meta_resurrection import collect_pa_trades

        pa_trades = collect_pa_trades(df)
        _save_pa_cache(pa_trades)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from tradingbot.ml.features.builder import FeatureBuilder
        from tradingbot.ml.shadow.ml_adapter import MLAdapter

        adapter = MLAdapter.load()
        builder = FeatureBuilder("XAUUSD", None)

    records: list[dict[str, Any]] = []
    for n, trade in enumerate(pa_trades):
        i = int(trade["bar_index"])
        live_dir = str(trade["direction"]).upper()
        ml_dir, ml_prob = _probe_ml_adapter(adapter, builder, df, i)
        final_r = float(trade.get("r_multiple", 0))
        agrees = ml_dir in ("BUY", "SELL") and ml_dir == live_dir
        records.append({
            "event": "shadow_trade_record",
            "timestamp": str(trade.get("bar_time", df.index[i])),
            "ticket": 900000 + n,
            "live_engine_direction": live_dir,
            "ml_prediction_direction": ml_dir,
            "ml_probability": round(ml_prob, 4) if ml_prob is not None else None,
            "ml_agrees_with_live": agrees,
            "live_engine": "PA",
            "final_trade_result": {
                "pnl": 0.0,
                "exit_reason": trade.get("exit_reason", ""),
            },
            "final_trade_R": round(final_r, 4),
            "source": "shadow_replay",
            "ml_engine": "phase9_9_shadow",
        })

    if records:
        save_replay_cache(records)
    return records

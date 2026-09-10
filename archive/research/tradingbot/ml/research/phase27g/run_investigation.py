"""Phase 27G — 30-day trade performance validation after replay fix."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.research.phase27a.trade_builder import build_completed_trades
from tradingbot.ml.research.phase27g.metrics import (
    build_confidence_analysis_report,
    build_direction_analysis,
    build_drawdown_curve_report,
    build_engine_analysis_report,
    build_equity_curve_report,
    build_exit_analysis,
    build_final_report,
    build_profitability_report,
    build_regime_analysis_report,
    build_risk_analysis_report,
    build_signal_funnel,
    build_time_analysis_report,
    build_trade_statistics_report,
)
from tradingbot.ml.research.regime_router.phase99_feature_validation import normalize_candles_for_builder

PROJECT_ROOT = Path(__file__).resolve().parents[4]
PHASE_DIR = Path(__file__).resolve().parent
PHASE27F_CACHE = PHASE_DIR.parent / "phase27f" / "_cache"
REPLAY_DAYS = 30


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(x) for x in obj]
    if isinstance(obj, float) and (obj != obj or obj in (float("inf"), float("-inf"))):
        return str(obj)
    return obj


def _write(name: str, payload: dict[str, Any]) -> None:
    (PHASE_DIR / name).write_text(json.dumps(_json_safe(payload), indent=2), encoding="utf-8")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def run_phase27g(*, base_dir: str | Path | None = None) -> dict[str, Any]:
    ts = datetime.now(timezone.utc).isoformat()
    root = Path(base_dir or PROJECT_ROOT)
    symbol = "XAUUSD"
    timeframe = "M5"

    records_path = PHASE27F_CACHE / "replay_records.json"
    meta_path = PHASE27F_CACHE / "replay_meta.json"
    if not records_path.is_file():
        raise FileNotFoundError(f"Phase 27F replay cache required: {records_path}")

    records = _load_json(records_path)
    replay_meta = _load_json(meta_path) if meta_path.is_file() else {}

    candles_raw = CandleStore(root).load(symbol, timeframe)
    if candles_raw is None or candles_raw.empty:
        raise RuntimeError("CandleStore unavailable for XAUUSD M5")
    window = normalize_candles_for_builder(prepare_calibration_candles(candles_raw, days=REPLAY_DAYS))

    trades = build_completed_trades(records, window, symbol=symbol)

    trade_stats = build_trade_statistics_report(trades, records, replay_days=REPLAY_DAYS)
    profitability = build_profitability_report(trades)
    direction = build_direction_analysis(trades)
    regime = build_regime_analysis_report(trades)
    engine = build_engine_analysis_report(trades, records)
    confidence = build_confidence_analysis_report(trades)
    time_analysis = build_time_analysis_report(trades)
    risk = build_risk_analysis_report(trades)
    exit_analysis = build_exit_analysis(trades)
    equity = build_equity_curve_report(trades)
    drawdown = build_drawdown_curve_report(trades)
    funnel = build_signal_funnel(records, trades)

    final = build_final_report(
        trades=trades,
        records=records,
        replay_meta=replay_meta,
        trade_stats=trade_stats,
        profitability=profitability,
        direction=direction,
        regime=regime,
        engine=engine,
        funnel=funnel,
        exit_analysis=exit_analysis,
        replay_days=REPLAY_DAYS,
    )
    final["generated_utc"] = ts

    outputs = {
        "trade_statistics.json": {**trade_stats, "generated_utc": ts},
        "profitability_report.json": {**profitability, "generated_utc": ts},
        "direction_analysis.json": {**direction, "generated_utc": ts},
        "regime_analysis.json": {**regime, "generated_utc": ts},
        "engine_analysis.json": {**engine, "generated_utc": ts},
        "confidence_analysis.json": {**confidence, "generated_utc": ts},
        "time_analysis.json": {**time_analysis, "generated_utc": ts},
        "risk_analysis.json": {**risk, "generated_utc": ts},
        "exit_analysis.json": {**exit_analysis, "generated_utc": ts},
        "equity_curve.json": {**equity, "generated_utc": ts},
        "drawdown_curve.json": {**drawdown, "generated_utc": ts},
        "signal_funnel.json": {**funnel, "generated_utc": ts},
        "final_report.json": final,
    }

    PHASE_DIR.mkdir(parents=True, exist_ok=True)
    for name, payload in outputs.items():
        _write(name, payload)

    return final


def main() -> int:
    report = run_phase27g()
    print(json.dumps(report, indent=2))
    return 0 if report.get("verdict") == "PERFORMANCE_VALIDATED" else 1


if __name__ == "__main__":
    raise SystemExit(main())

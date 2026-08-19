"""Phase 27L — exit engine investigation (read-only simulation)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.research.phase27a.trade_builder import build_completed_trades
from tradingbot.ml.research.phase27l.exit_simulators import simulate_all_strategies
from tradingbot.ml.research.phase27l.exit_trace import (
    _risk_unit,
    build_profit_timeline,
    build_reversal_stats,
    prepare_indicator_frame,
    trace_trade_bars,
)
from tradingbot.ml.research.phase27l.metrics import (
    build_edge_recovery,
    build_exit_ranking,
    build_exit_scoreboard,
    build_exit_simulations,
    build_exit_timeline,
    build_final_report,
    build_loser_recovery,
    build_profit_timeline_report,
    build_reversal_analysis,
    build_winner_preservation,
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


def run_phase27l(*, base_dir: str | Path | None = None) -> dict[str, Any]:
    ts = datetime.now(timezone.utc).isoformat()
    root = Path(base_dir or PROJECT_ROOT)
    symbol = "XAUUSD"
    timeframe = "M5"

    records_path = PHASE27F_CACHE / "replay_records.json"
    if not records_path.is_file():
        raise FileNotFoundError(f"Phase 27F replay cache required: {records_path}")

    records = _load_json(records_path)
    candles_raw = CandleStore(root).load(symbol, timeframe)
    if candles_raw is None or candles_raw.empty:
        raise RuntimeError("CandleStore unavailable for XAUUSD M5")
    window = normalize_candles_for_builder(prepare_calibration_candles(candles_raw, days=REPLAY_DAYS))
    frame = prepare_indicator_frame(window)

    trades = build_completed_trades(records, window, symbol=symbol)

    traces: list[dict[str, Any]] = []
    profit_timelines: list[dict[str, Any]] = []
    reversal_rows: list[dict[str, Any]] = []
    sim_results: list[dict[str, Any]] = []

    for trade in trades:
        trace = trace_trade_bars(trade, frame)
        traces.append(trace)
        is_buy = str(trade["direction"]) == "BUY"
        risk = _risk_unit(float(trade["entry_price"]), trade.get("sl"))
        profit_timelines.append(build_profit_timeline(trace, risk, is_buy))
        reversal_rows.append(build_reversal_stats(trace))
        sim_results.append(simulate_all_strategies(trade, frame))

    exit_timeline = build_exit_timeline(traces)
    profit_timeline = build_profit_timeline_report(profit_timelines)
    reversal = build_reversal_analysis(reversal_rows)
    simulations = build_exit_simulations(sim_results)
    edge_recovery = build_edge_recovery(sim_results)
    loser_recovery = build_loser_recovery(sim_results)
    winner_preservation = build_winner_preservation(sim_results)
    scoreboard = build_exit_scoreboard(sim_results)
    ranking = build_exit_ranking(scoreboard, loser_recovery)

    final = build_final_report(
        ranking=ranking,
        scoreboard=scoreboard,
        edge_recovery=edge_recovery,
        loser_recovery=loser_recovery,
        winner_preservation=winner_preservation,
        reversal=reversal,
        trade_count=len(trades),
    )
    final["generated_utc"] = ts

    outputs = {
        "exit_timeline.json": {**exit_timeline, "generated_utc": ts},
        "profit_timeline.json": {**profit_timeline, "generated_utc": ts},
        "reversal_analysis.json": {**reversal, "generated_utc": ts},
        "exit_simulations.json": {**simulations, "generated_utc": ts},
        "edge_recovery.json": {**edge_recovery, "generated_utc": ts},
        "loser_recovery.json": {**loser_recovery, "generated_utc": ts},
        "winner_preservation.json": {**winner_preservation, "generated_utc": ts},
        "exit_scoreboard.json": {**scoreboard, "generated_utc": ts},
        "exit_ranking.json": {**ranking, "generated_utc": ts},
        "final_report.json": final,
    }

    PHASE_DIR.mkdir(parents=True, exist_ok=True)
    for name, payload in outputs.items():
        _write(name, payload)

    return final


def main() -> int:
    report = run_phase27l()
    print(json.dumps(report, indent=2))
    return 0 if report.get("verdict") == "EXIT_ENGINE_ROOT_CAUSE_IDENTIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())

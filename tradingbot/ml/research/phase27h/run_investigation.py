"""Phase 27H — robustness and stress test validation (read-only)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.research.phase27a.trade_builder import build_completed_trades
from tradingbot.ml.research.phase27h.metrics import (
    INITIAL_BALANCE,
    build_confidence_robustness,
    build_cost_analysis,
    build_execution_delay_stress,
    build_failure_simulation,
    build_final_report,
    build_missed_trade_montecarlo,
    build_regime_robustness,
    build_robustness_score,
    build_rr_distribution,
    build_sequence_montecarlo,
    build_slippage_stress,
    build_spread_stress,
    _metrics,
)
from tradingbot.ml.research.regime_router.phase99_feature_validation import normalize_candles_for_builder

PROJECT_ROOT = Path(__file__).resolve().parents[4]
PHASE_DIR = Path(__file__).resolve().parent
PHASE27F_CACHE = PHASE_DIR.parent / "phase27f" / "_cache"
PHASE27G_DIR = PHASE_DIR.parent / "phase27g"
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


def run_phase27h(*, base_dir: str | Path | None = None) -> dict[str, Any]:
    ts = datetime.now(timezone.utc).isoformat()
    root = Path(base_dir or PROJECT_ROOT)
    symbol = "XAUUSD"
    timeframe = "M5"

    records_path = PHASE27F_CACHE / "replay_records.json"
    if not records_path.is_file():
        raise FileNotFoundError(f"Phase 27F replay cache required: {records_path}")

    records = _load_json(records_path)
    phase27g_baseline = _load_json(PHASE27G_DIR / "profitability_report.json") if (
        PHASE27G_DIR / "profitability_report.json"
    ).is_file() else {}

    candles_raw = CandleStore(root).load(symbol, timeframe)
    if candles_raw is None or candles_raw.empty:
        raise RuntimeError("CandleStore unavailable for XAUUSD M5")
    window = normalize_candles_for_builder(prepare_calibration_candles(candles_raw, days=REPLAY_DAYS))

    trades = build_completed_trades(records, window, symbol=symbol)
    if len(trades) != 575 and len(trades) > 0:
        print(f"[phase27h] warning: expected 575 trades, got {len(trades)}")

    baseline = _metrics(trades, initial=INITIAL_BALANCE)

    spread = build_spread_stress(trades, baseline)
    slippage = build_slippage_stress(trades, window, baseline)
    delay = build_execution_delay_stress(trades, window, baseline, symbol=symbol)
    missed_mc = build_missed_trade_montecarlo(trades, baseline)
    sequence_mc = build_sequence_montecarlo(trades, baseline)
    cost = build_cost_analysis(trades, baseline)
    rr_dist = build_rr_distribution(trades, window)
    confidence = build_confidence_robustness(trades, baseline)
    regime = build_regime_robustness(trades, window, baseline)
    failure = build_failure_simulation(trades, baseline)
    scores = build_robustness_score(
        baseline=baseline,
        spread=spread,
        slippage=slippage,
        delay=delay,
        missed_mc=missed_mc,
        sequence_mc=sequence_mc,
        cost=cost,
        failure=failure,
    )

    final = build_final_report(
        baseline=baseline,
        baseline_source=phase27g_baseline,
        scores=scores,
        spread=spread,
        slippage=slippage,
        missed_mc=missed_mc,
        sequence_mc=sequence_mc,
        cost=cost,
        failure=failure,
        trade_count=len(trades),
    )
    final["generated_utc"] = ts

    outputs = {
        "spread_stress.json": {**spread, "generated_utc": ts},
        "slippage_stress.json": {**slippage, "generated_utc": ts},
        "execution_delay.json": {**delay, "generated_utc": ts},
        "missed_trade_montecarlo.json": {**missed_mc, "generated_utc": ts},
        "sequence_montecarlo.json": {**sequence_mc, "generated_utc": ts},
        "cost_analysis.json": {**cost, "generated_utc": ts},
        "rr_distribution.json": {**rr_dist, "generated_utc": ts},
        "confidence_robustness.json": {**confidence, "generated_utc": ts},
        "regime_robustness.json": {**regime, "generated_utc": ts},
        "failure_simulation.json": {**failure, "generated_utc": ts},
        "robustness_score.json": {**scores, "generated_utc": ts},
        "final_report.json": final,
    }

    PHASE_DIR.mkdir(parents=True, exist_ok=True)
    for name, payload in outputs.items():
        _write(name, payload)

    return final


def main() -> int:
    report = run_phase27h()
    print(json.dumps(report, indent=2))
    return 0 if report.get("verdict") == "ROBUST_FOR_PAPER" else 1


if __name__ == "__main__":
    raise SystemExit(main())

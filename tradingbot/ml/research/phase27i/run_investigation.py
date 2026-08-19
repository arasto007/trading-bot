"""Phase 27I — slippage root cause investigation (read-only)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.research.phase27a.trade_builder import build_completed_trades
from tradingbot.ml.research.phase27h.metrics import _metrics, INITIAL_BALANCE
from tradingbot.ml.research.phase27i.metrics import (
    build_atr_analysis,
    build_direction_slippage,
    build_duration_slippage,
    build_edge_decay,
    build_execution_price_analysis,
    build_final_report,
    build_regime_slippage,
    build_root_cause_rank,
    build_rr_decay,
    build_slippage_breakdown,
    build_spread_analysis,
)
from tradingbot.ml.research.phase27i.slippage_decompose import enrich_all_trades
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


def run_phase27i(*, base_dir: str | Path | None = None) -> dict[str, Any]:
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

    trades = build_completed_trades(records, window, symbol=symbol)
    baseline = _metrics(trades, initial=INITIAL_BALANCE)
    enriched = enrich_all_trades(trades, window)

    breakdown = build_slippage_breakdown(enriched, baseline)
    direction = build_direction_slippage(enriched)
    regime = build_regime_slippage(enriched)
    duration = build_duration_slippage(enriched)
    rr_decay = build_rr_decay(enriched)
    atr_analysis = build_atr_analysis(enriched)
    spread_analysis = build_spread_analysis(enriched)
    execution_price = build_execution_price_analysis(enriched)
    edge_decay = build_edge_decay(trades, window, enriched, baseline)
    root_cause = build_root_cause_rank(
        breakdown=breakdown,
        direction=direction,
        duration=duration,
        rr_decay=rr_decay,
        atr_analysis=atr_analysis,
        spread_analysis=spread_analysis,
        execution_price=execution_price,
        edge_decay=edge_decay,
        enriched=enriched,
    )

    final = build_final_report(
        root_cause=root_cause,
        breakdown=breakdown,
        edge_decay=edge_decay,
        execution_price=execution_price,
        trade_count=len(trades),
    )
    final["generated_utc"] = ts

    # Summary-only breakdown for top-level JSON (full per-trade in separate field)
    breakdown_summary = {k: v for k, v in breakdown.items() if k != "per_trade"}
    breakdown_trades = {"phase": "27I", "trade_count": len(enriched), "trades": enriched}

    outputs = {
        "slippage_breakdown.json": {**breakdown_summary, "generated_utc": ts},
        "slippage_per_trade.json": {**breakdown_trades, "generated_utc": ts},
        "direction_slippage.json": {**direction, "generated_utc": ts},
        "regime_slippage.json": {**regime, "generated_utc": ts},
        "duration_slippage.json": {**duration, "generated_utc": ts},
        "rr_decay.json": {**rr_decay, "generated_utc": ts},
        "atr_analysis.json": {**atr_analysis, "generated_utc": ts},
        "spread_analysis.json": {**spread_analysis, "generated_utc": ts},
        "execution_price_analysis.json": {**execution_price, "generated_utc": ts},
        "edge_decay.json": {**edge_decay, "generated_utc": ts},
        "root_cause_rank.json": {**root_cause, "generated_utc": ts},
        "final_report.json": final,
    }

    PHASE_DIR.mkdir(parents=True, exist_ok=True)
    for name, payload in outputs.items():
        _write(name, payload)

    return final


def main() -> int:
    report = run_phase27i()
    print(json.dumps(report, indent=2))
    return 0 if report.get("verdict") == "SLIPPAGE_ROOT_CAUSE_IDENTIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())

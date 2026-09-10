"""Phase 27K — losing trade root cause investigation (read-only)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.research.phase27a.trade_builder import build_completed_trades
from tradingbot.ml.research.phase27k.loser_enrich import build_loser_log
from tradingbot.ml.research.phase27k.metrics import (
    build_confidence_loss_analysis,
    build_engine_loss_analysis,
    build_entry_conditions,
    build_false_signal_classification,
    build_final_report,
    build_first_bar_analysis,
    build_mae_mfe_analysis,
    build_regime_loss_analysis,
    build_root_cause_rank,
    build_stoploss_quality,
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


def run_phase27k(*, base_dir: str | Path | None = None) -> dict[str, Any]:
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
    losers = build_loser_log(trades, records, window)

    entry = build_entry_conditions(losers)
    first_bar = build_first_bar_analysis(losers)
    mae_mfe = build_mae_mfe_analysis(losers)
    stoploss = build_stoploss_quality(losers)
    false_sig = build_false_signal_classification(losers)
    regime = build_regime_loss_analysis(losers, len(trades))
    engine = build_engine_loss_analysis(losers, len(trades))
    confidence = build_confidence_loss_analysis(losers)
    root_cause = build_root_cause_rank(
        losers=losers,
        false_sig=false_sig,
        first_bar=first_bar,
        mae_mfe=mae_mfe,
        stoploss=stoploss,
        entry=entry,
        regime=regime,
        engine=engine,
        confidence=confidence,
    )

    final = build_final_report(
        losers=losers,
        total_trades=len(trades),
        root_cause=root_cause,
        mae_mfe=mae_mfe,
        false_sig=false_sig,
        stoploss=stoploss,
        first_bar=first_bar,
    )
    final["generated_utc"] = ts

    outputs = {
        "losing_trade_log.json": {"phase": "27K", "count": len(losers), "trades": losers, "generated_utc": ts},
        "entry_conditions.json": {**entry, "generated_utc": ts},
        "first_bar_analysis.json": {**first_bar, "generated_utc": ts},
        "mae_mfe_analysis.json": {**mae_mfe, "generated_utc": ts},
        "stoploss_quality.json": {**stoploss, "generated_utc": ts},
        "false_signal_classification.json": {**false_sig, "generated_utc": ts},
        "regime_loss_analysis.json": {**regime, "generated_utc": ts},
        "engine_loss_analysis.json": {**engine, "generated_utc": ts},
        "confidence_loss_analysis.json": {**confidence, "generated_utc": ts},
        "root_cause_rank.json": {**root_cause, "generated_utc": ts},
        "final_report.json": final,
    }

    PHASE_DIR.mkdir(parents=True, exist_ok=True)
    for name, payload in outputs.items():
        _write(name, payload)

    return final


def main() -> int:
    report = run_phase27k()
    print(json.dumps(report, indent=2))
    return 0 if report.get("verdict") == "LOSING_TRADES_ROOT_CAUSE_IDENTIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())

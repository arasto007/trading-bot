"""Phase 1.5.36–1.5.40 orchestrator — offline isolated v41 TREND evidence."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.research.v41_isolated.integrity import audit_v41_bundle
from tradingbot.ml.research.v41_isolated.replay import (
    DEFAULT_WARMUP_START,
    FREEZE_END,
    FREEZE_START,
    MIN_TRADES_FOR_INFERENCE,
    run_isolated_trend_replay,
)
from tradingbot.ml.research.v41_isolated.robustness import monte_carlo_r, walk_forward_from_trades

SYMBOL = "XAUUSD"
TIMEFRAME = "M5"


def phase15_36_reports_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import reports_dir

    return reports_dir(base_dir) / "phase15_36"


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def load_xauusd_m5() -> pd.DataFrame:
    candles = CandleStore().load(SYMBOL, TIMEFRAME)
    if candles is None or candles.empty:
        parquet = Path(__file__).resolve().parents[4] / "data" / "ml" / "raw" / "candles" / "m5" / "XAUUSD_m5.parquet"
        if parquet.is_file():
            candles = pd.read_parquet(parquet)
    if candles is None or candles.empty:
        raise FileNotFoundError("XAUUSD M5 candles missing — cannot invent market data")
    return candles


def classify_calibration_readiness(payload: dict[str, Any]) -> dict[str, Any]:
    """Exactly one of A/B/C/D. Does not write production factors."""
    book = payload.get("book") or {}
    oos = payload.get("book_oos") or {}
    wf = payload.get("walk_forward") or {}
    mc = payload.get("monte_carlo") or {}
    n = int(book.get("trades") or 0)
    n_oos = int(oos.get("trades") or 0)
    pf = oos.get("profit_factor")
    exp = oos.get("expectancy")

    if n < MIN_TRADES_FOR_INFERENCE:
        letter = "C"
        reason = f"isolated TREND book has {n} trades < {MIN_TRADES_FOR_INFERENCE}"
    elif wf.get("status") == "INSUFFICIENT" and mc.get("status") == "INSUFFICIENT":
        if n_oos == 0:
            letter = "C"
            reason = "no valid OOS trades after freeze end; in-sample book cannot authorize calibration"
        else:
            letter = "B"
            reason = (
                f"isolated book exists (n={n}, oos={n_oos}) but WF/MC classified INSUFFICIENT"
            )
    elif n_oos >= MIN_TRADES_FOR_INFERENCE and isinstance(pf, (int, float)) and pf < 1.0 and (exp or 0) < 0:
        letter = "D"
        reason = f"OOS evidence contradicts edge: PF={pf}, expectancy={exp}, n={n_oos}"
    elif (
        n_oos >= MIN_TRADES_FOR_INFERENCE
        and isinstance(pf, (int, float))
        and pf >= 1.2
        and wf.get("status") == "OK"
        and mc.get("status") == "OK"
        and float(mc.get("probability_of_loss") or 1) < 0.5
    ):
        letter = "A"
        reason = "OOS book + WF + MC all present and supportive — still not production-activated"
    else:
        letter = "B"
        reason = "isolated TREND book exists but is not sufficient for dedicated calibration"

    return {
        "classification": letter,
        "reason": reason,
        "v41_remains_neutral_1_0": True,
        "production_calibrators_modified": False,
    }


def run_v41_isolated_study(*, write_reports: bool = True) -> dict[str, Any]:
    integrity = audit_v41_bundle()
    candles = load_xauusd_m5()
    if not isinstance(candles.index, pd.DatetimeIndex):
        if "timestamp" in candles.columns:
            candles = candles.set_index("timestamp")
        elif "time" in candles.columns:
            candles = candles.set_index("time")
    candles.index = pd.to_datetime(candles.index, utc=True)

    replay = run_isolated_trend_replay(
        candles,
        symbol=SYMBOL,
        start=DEFAULT_WARMUP_START,
        end=candles.index.max(),
        non_overlapping=True,
    )
    trades = list(replay.get("trades") or [])
    oos_r = [t["r_multiple"] for t in trades if t.get("split") == "oos"]
    all_r = [t["r_multiple"] for t in trades]
    wf = walk_forward_from_trades(trades)
    # MC on real R only. Prefer OOS; if OOS insufficient, MC the full isolated book
    # but label the sample as mixed in-sample+OOS so it cannot be sold as WF.
    mc_source = "oos" if len(oos_r) >= MIN_TRADES_FOR_INFERENCE else "full_isolated_book"
    mc = monte_carlo_r(oos_r if mc_source == "oos" else all_r)
    mc["sample"] = mc_source

    decision = classify_calibration_readiness({
        **replay,
        "walk_forward": wf,
        "monte_carlo": mc,
    })
    payload = {
        "phase": "1.5.36-1.5.40",
        "offline_only": True,
        "integrity": integrity,
        "coverage": replay.get("coverage"),
        "methodology": replay.get("methodology"),
        "classification_funnel": replay.get("classification"),
        "book": replay.get("book"),
        "book_in_sample": replay.get("book_in_sample"),
        "book_oos": replay.get("book_oos"),
        "average_holding_bars": replay.get("average_holding_bars"),
        "trade_date_range": replay.get("trade_date_range"),
        "bundle_classification_metrics": replay.get("bundle_classification_metrics"),
        "walk_forward": wf,
        "monte_carlo": mc,
        "decision": decision,
        "candle_span": {
            "min": str(candles.index.min()),
            "max": str(candles.index.max()),
            "rows": int(len(candles)),
        },
        "freeze_start": FREEZE_START.isoformat(),
        "freeze_end": FREEZE_END.isoformat(),
        "n_trades_recorded": len(trades),
    }
    if write_reports:
        out = phase15_36_reports_dir()
        out.mkdir(parents=True, exist_ok=True)
        slim = dict(payload)
        slim["trades"] = trades
        (out / "v41_isolated_trend_replay.json").write_text(
            json.dumps(_json_safe(slim), indent=2), encoding="utf-8"
        )
        book_only = {
            "book": replay.get("book"),
            "book_in_sample": replay.get("book_in_sample"),
            "book_oos": replay.get("book_oos"),
            "walk_forward": wf,
            "monte_carlo": mc,
            "decision": decision,
        }
        (out / "v41_trend_performance_book.json").write_text(
            json.dumps(_json_safe(book_only), indent=2), encoding="utf-8"
        )
        payload["report_dir"] = str(out)
    payload["trades"] = trades
    return payload


if __name__ == "__main__":
    result = run_v41_isolated_study()
    print(json.dumps(_json_safe({
        "ok": True,
        "decision": result.get("decision"),
        "book": result.get("book"),
        "book_oos": result.get("book_oos"),
        "walk_forward": result.get("walk_forward"),
        "monte_carlo_status": (result.get("monte_carlo") or {}).get("status"),
        "coverage": result.get("coverage"),
        "classification_funnel": result.get("classification_funnel"),
    }), indent=2))

"""Phase 27J — edge decomposition investigation (read-only)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.research.phase27a.trade_builder import build_completed_trades
from tradingbot.ml.research.phase27j.edge_decompose import enrich_all_edges
from tradingbot.ml.research.phase27j.metrics import (
    build_capture_efficiency,
    build_edge_decay,
    build_edge_per_trade,
    build_edge_sources,
    build_exit_quality,
    build_final_report,
    build_loser_analysis,
    build_opportunity_loss,
    build_r_multiple_analysis,
    build_root_cause_rank,
    build_winner_analysis,
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


def run_phase27j(*, base_dir: str | Path | None = None) -> dict[str, Any]:
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
    enriched = enrich_all_edges(trades, window)

    edge_per_trade = build_edge_per_trade(enriched)
    winner = build_winner_analysis(enriched)
    loser = build_loser_analysis(enriched)
    capture = build_capture_efficiency(enriched)
    exit_q = build_exit_quality(enriched)
    sources = build_edge_sources(enriched)
    r_mult = build_r_multiple_analysis(enriched)
    opportunity = build_opportunity_loss(enriched)
    decay = build_edge_decay(enriched)
    root_cause = build_root_cause_rank(
        winner=winner,
        loser=loser,
        capture=capture,
        exit_q=exit_q,
        edge_decay=decay,
        r_mult=r_mult,
        opportunity=opportunity,
        enriched=enriched,
    )

    final = build_final_report(
        root_cause=root_cause,
        edge_per_trade=edge_per_trade,
        winner=winner,
        loser=loser,
        edge_decay=decay,
        r_mult=r_mult,
        capture=capture,
        trade_count=len(trades),
    )
    final["generated_utc"] = ts

    edge_summary = {k: v for k, v in edge_per_trade.items() if k != "trades"}

    outputs = {
        "edge_per_trade.json": {**edge_summary, "trades": enriched, "generated_utc": ts},
        "winner_analysis.json": {**winner, "generated_utc": ts},
        "loser_analysis.json": {**loser, "generated_utc": ts},
        "capture_efficiency.json": {**capture, "generated_utc": ts},
        "exit_quality.json": {**exit_q, "generated_utc": ts},
        "edge_sources.json": {**sources, "generated_utc": ts},
        "r_multiple_analysis.json": {**r_mult, "generated_utc": ts},
        "opportunity_loss.json": {**opportunity, "generated_utc": ts},
        "edge_decay.json": {**decay, "generated_utc": ts},
        "root_cause_rank.json": {**root_cause, "generated_utc": ts},
        "final_report.json": final,
    }

    PHASE_DIR.mkdir(parents=True, exist_ok=True)
    for name, payload in outputs.items():
        _write(name, payload)

    return final


def main() -> int:
    report = run_phase27j()
    print(json.dumps(report, indent=2))
    return 0 if report.get("verdict") == "EDGE_ROOT_CAUSE_IDENTIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())

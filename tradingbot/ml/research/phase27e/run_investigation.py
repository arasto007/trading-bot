"""Phase 27E — signal-to-execution bottleneck investigation (READ ONLY)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.research.phase27a.trade_builder import build_completed_trades
from tradingbot.ml.research.phase27e.metrics import (
    build_execution_statistics,
    build_final_report,
    build_journal_flow_statistics,
    build_riskgate_rejection_statistics,
    build_root_cause_rank,
    build_signal_loss_funnel,
    build_signal_trace,
    build_stage_statistics,
)
from tradingbot.ml.research.regime_router.phase99_feature_validation import normalize_candles_for_builder

PROJECT_ROOT = Path(__file__).resolve().parents[4]
PHASE_DIR = Path(__file__).resolve().parent
PHASE27D_CACHE = PHASE_DIR.parent / "phase27d" / "_cache"
EXPECTED_EMITTED = 762


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


def run_phase27e(*, base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or PROJECT_ROOT)
    records_path = PHASE27D_CACHE / "replay_records.json"
    hold_path = PHASE27D_CACHE / "hold_chain.json"

    if not records_path.is_file():
        raise FileNotFoundError(f"Phase 27D replay cache required: {records_path}")

    records = _load_json(records_path)
    hold_chain = _load_json(hold_path) if hold_path.is_file() else {}

    candles_raw = CandleStore(root).load("XAUUSD", "M5")
    window = normalize_candles_for_builder(prepare_calibration_candles(candles_raw, days=30))
    trades = build_completed_trades(records, window, symbol="XAUUSD")

    trace_payload = build_signal_trace(records)
    traced = trace_payload["signals"]
    if len(traced) != EXPECTED_EMITTED:
        trace_payload["warning"] = f"expected {EXPECTED_EMITTED} emitted, got {len(traced)}"

    riskgate = build_riskgate_rejection_statistics(traced)
    execution = build_execution_statistics(traced)
    journal = build_journal_flow_statistics(traced, trades)
    funnel = build_signal_loss_funnel(traced, hold_chain)
    stages = build_stage_statistics(traced)
    root_causes = build_root_cause_rank(traced)
    final = build_final_report(
        trace=trace_payload,
        funnel=funnel,
        riskgate=riskgate,
        execution=execution,
        root_causes=root_causes,
    )

    outputs = {
        "signal_trace.json": trace_payload,
        "riskgate_rejection_statistics.json": riskgate,
        "execution_statistics.json": execution,
        "journal_flow_statistics.json": journal,
        "signal_loss_funnel.json": funnel,
        "stage_statistics.json": stages,
        "root_cause_rank.json": root_causes,
        "final_report.json": final,
    }

    PHASE_DIR.mkdir(parents=True, exist_ok=True)
    for name, payload in outputs.items():
        _write(name, payload)

    return final


def main() -> int:
    report = run_phase27e()
    print(json.dumps(report, indent=2))
    return 0 if report.get("verdict") == "BOTTLENECK_IDENTIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())

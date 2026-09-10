"""Phase 27F — replay portfolio state repair validation."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.research.phase22c.hold_chain import get_hold_chain, reset_hold_chain
from tradingbot.ml.research.phase25b.unified_pipeline_replay import run_unified_pipeline_replay
from tradingbot.ml.research.phase27f.metrics import (
    build_execution_statistics,
    build_final_report,
    build_open_position_history,
    build_portfolio_consistency,
    build_portfolio_timeline,
    build_position_lifecycle,
    build_riskgate_before_after,
)

PROJECT_ROOT = Path(__file__).resolve().parents[4]
PHASE_DIR = Path(__file__).resolve().parent
PHASE27D_CACHE = PHASE_DIR.parent / "phase27d" / "_cache"
CACHE_DIR = PHASE_DIR / "_cache"
REPLAY_DAYS = 30
WARMUP_BARS = 300
STRIDE = 1


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


def run_phase27f(*, base_dir: str | Path | None = None, use_cache: bool = True) -> dict[str, Any]:
    ts = datetime.now(timezone.utc).isoformat()
    root = Path(base_dir or PROJECT_ROOT)
    symbol = "XAUUSD"
    timeframe = "M5"

    before_path = PHASE27D_CACHE / "replay_records.json"
    if not before_path.is_file():
        raise FileNotFoundError(f"Phase 27D before cache required: {before_path}")
    before_records = _load_json(before_path)

    os.environ["USE_ML_KERNEL"] = "1"
    os.environ["ALLOW_LEGACY_FALLBACK"] = "0"
    os.environ["TRADINGBOT_PAPER"] = "1"

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_records = CACHE_DIR / "replay_records.json"
    cache_meta = CACHE_DIR / "replay_meta.json"

    reset_hold_chain()
    t0 = time.perf_counter()
    if use_cache and cache_records.is_file() and cache_meta.is_file():
        after_records = _load_json(cache_records)
        replay_meta = _load_json(cache_meta)
        elapsed = float(replay_meta.get("elapsed_sec") or 0)
        print(f"[phase27f] loaded cached post-fix replay ({len(after_records)} records)")
    else:
        print("[phase27f] running fresh 30-day replay with portfolio lifecycle repair...")
        after_records, replay_meta = run_unified_pipeline_replay(
            base_dir=str(root),
            symbol=symbol,
            timeframe=timeframe,
            days=REPLAY_DAYS,
            tail_only=None,
            stride=STRIDE,
            warmup_bars=WARMUP_BARS,
            use_forming_bar_adapter=True,
        )
        elapsed = round(time.perf_counter() - t0, 2)
        replay_meta["elapsed_sec"] = elapsed
        replay_meta["phase27f_portfolio_repair"] = True
        cache_records.write_text(json.dumps(_json_safe(after_records)), encoding="utf-8")
        cache_meta.write_text(json.dumps(_json_safe(replay_meta)), encoding="utf-8")
        print(f"[phase27f] replay complete in {elapsed}s — {len(after_records)} bars")

    portfolio_timeline = build_portfolio_timeline(replay_meta)
    position_lifecycle = build_position_lifecycle(replay_meta)
    riskgate = build_riskgate_before_after(before_records, after_records)
    open_history = build_open_position_history(after_records)
    execution = build_execution_statistics(after_records)
    consistency = build_portfolio_consistency(replay_meta, after_records)
    final = build_final_report(
        before_records=before_records,
        after_records=after_records,
        meta=replay_meta,
        replay_meta=replay_meta,
        consistency=consistency,
        riskgate=riskgate,
        execution=execution,
    )
    final["generated_utc"] = ts

    outputs = {
        "portfolio_timeline.json": portfolio_timeline,
        "position_lifecycle.json": position_lifecycle,
        "riskgate_before_after.json": riskgate,
        "open_position_history.json": open_history,
        "execution_statistics.json": execution,
        "portfolio_consistency.json": consistency,
        "final_report.json": final,
    }

    PHASE_DIR.mkdir(parents=True, exist_ok=True)
    for name, payload in outputs.items():
        _write(name, payload)

    return final


def main() -> int:
    use_cache = "--no-cache" not in sys.argv
    report = run_phase27f(use_cache=use_cache)
    print(json.dumps(report, indent=2))
    return 0 if report.get("verdict") == "REPLAY_PORTFOLIO_FIXED" else 1


if __name__ == "__main__":
    raise SystemExit(main())

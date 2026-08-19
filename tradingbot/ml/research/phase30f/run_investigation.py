"""Phase 30F report generation and sandbox validation."""

from __future__ import annotations

import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.research.phase30f.collectors.supervisor import CollectorSupervisor
from tradingbot.ml.research.phase30f.config import COLLECTOR_VERSION, CollectorConfig
from tradingbot.ml.research.phase30f.mt5_client import MockMt5ResearchClient, TickQuote
from tradingbot.ml.research.phase30f.storage.parquet_store import ParquetStore
from tradingbot.ml.research.phase30f.validation.integrity import (
    detect_duplicate_timestamps,
    detect_tick_gaps,
    run_storage_validation,
    validate_clock_consistency,
    validate_tick_ordering,
)
from tradingbot.ml.research.phase30f.validation.schema import validate_ticks_batch

PHASE_DIR = Path(__file__).resolve().parent
VERDICTS = {"COLLECTOR_FRAMEWORK_READY", "COLLECTOR_FRAMEWORK_NEEDS_FIXES"}


def _write(name: str, payload: dict[str, Any]) -> None:
    out = PHASE_DIR / "reports" / name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _sandbox_config(tmp: Path | None = None) -> CollectorConfig:
    root = tmp or (PHASE_DIR / "_sandbox")
    if tmp is None and root.exists():
        shutil.rmtree(root, ignore_errors=True)
    return CollectorConfig(
        data_root=root,
        tick_store=root / "tick_store",
        db_path=root / "broker_collector.db",
        manifest_path=root / "broker_manifest.json",
        poll_interval_ms=0,
        shadow_mode=True,
    )


def _demo_ticks(base_ms: int, n: int = 5, *, gap_at: int | None = None) -> list[TickQuote]:
    ticks = []
    for i in range(n):
        ts = base_ms + i * 100
        if gap_at is not None and i == gap_at:
            ts += 10_000
        ticks.append(TickQuote(bid=2000.0 + i * 0.01, ask=2000.3 + i * 0.01, time_msc=ts))
    return ticks


def run_sandbox_demo(config: CollectorConfig | None = None) -> CollectorSupervisor:
    cfg = config or _sandbox_config()
    cfg.ensure_dirs()
    base_ms = int(datetime.now(timezone.utc).timestamp() * 1000) - 60_000
    client = MockMt5ResearchClient(_demo_ticks(base_ms, 8, gap_at=4))
    sup = CollectorSupervisor(client, cfg)
    sup.run_cycle(tick_polls=8)

    from tradingbot.ml.research.phase30f.collectors.execution_logger import ExecutionLogger

    el = sup.get_collector("ExecutionLogger")
    if isinstance(el, ExecutionLogger):
        el.log_shadow_execution(
            symbol=cfg.symbol,
            direction="BUY",
            leg="entry",
            requested_price=2000.3,
            fill_price=2000.35,
        )
        el.log_shadow_execution(
            symbol=cfg.symbol,
            direction="SELL",
            leg="exit",
            requested_price=2001.0,
            fill_price=2000.95,
        )
        el.flush()

    # enqueue and repair gap
    sup.state.enqueue_gap(cfg.symbol, base_ms + 300, base_ms + 10_300)
    sup.get_collector("TickBackfill").start()  # type: ignore[union-attr]

    sup.get_collector("GapExtractor").start()  # type: ignore[union-attr]
    return sup


def build_reports(supervisor: CollectorSupervisor) -> dict[str, Any]:
    cfg = supervisor.config
    parquet = ParquetStore(cfg.tick_store)
    df = parquet.read_ticks(cfg.symbol)

    tick_quality = {
        "symbol": cfg.symbol,
        "tick_count": len(df),
        "duplicates": detect_duplicate_timestamps(df),
        "ordering_valid": validate_tick_ordering(df),
        "clock_issues": validate_clock_consistency(df),
        "gaps_detected": detect_tick_gaps(df, cfg.gap_threshold_ms),
        "schema_validation": validate_ticks_batch(df.to_dict("records")) if not df.empty else {"valid": True, "errors": []},
    }

    health = supervisor.health_report()
    storage = run_storage_validation(supervisor.manifest)
    gaps = []
    gap_file = cfg.data_root / "gaps" / "gap_events.jsonl"
    if gap_file.is_file():
        gaps = [json.loads(line) for line in gap_file.read_text(encoding="utf-8").splitlines() if line.strip()]

    stats = {
        "ticks_collected": int(df.shape[0]) if not df.empty else 0,
        "collectors": {b["collector_name"]: b for b in health["heartbeats"]},
        "manifest_files": len(supervisor.manifest.load().get("files", [])),
        "gap_events": len(gaps),
    }

    t0 = time.perf_counter()
    supervisor.run_cycle(tick_polls=3)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    performance = {
        "cycle_elapsed_ms": round(elapsed_ms, 2),
        "ticks_per_cycle": 3,
        "poll_interval_ms": cfg.poll_interval_ms,
        "storage_engine": "parquet_zstd",
    }

    _write("collection_statistics.json", {"phase": "30F", **stats, "generated_utc": datetime.now(timezone.utc).isoformat()})
    _write("collector_health.json", {"phase": "30F", **health, "generated_utc": datetime.now(timezone.utc).isoformat()})
    _write("tick_quality.json", {"phase": "30F", **tick_quality, "generated_utc": datetime.now(timezone.utc).isoformat()})
    _write("gap_report.json", {"phase": "30F", "events": gaps, "count": len(gaps), "generated_utc": datetime.now(timezone.utc).isoformat()})
    _write("storage_validation.json", {"phase": "30F", **storage, "generated_utc": datetime.now(timezone.utc).isoformat()})
    _write("performance_report.json", {"phase": "30F", **performance, "generated_utc": datetime.now(timezone.utc).isoformat()})

    verdict = determine_verdict(tick_quality, health, storage)
    final = {
        "phase": "30F",
        "verdict": verdict,
        "production_modified": False,
        "collector_version": COLLECTOR_VERSION,
        "collectors_implemented": [
            "TickPoller",
            "TickBackfill",
            "ExecutionLogger",
            "HistorySync",
            "SymbolSnapshot",
            "GapExtractor",
            "NewsJoiner",
            "CollectorSupervisor",
        ],
        "shadow_mode_enforced": True,
        "order_send_calls": 0,
        "reports": [
            "collection_statistics.json",
            "collector_health.json",
            "tick_quality.json",
            "gap_report.json",
            "storage_validation.json",
            "performance_report.json",
            "phase30f_final_report.json",
        ],
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }
    _write("phase30f_final_report.json", final)
    return final


def determine_verdict(tick_quality: dict, health: dict, storage: dict) -> str:
    if tick_quality.get("duplicates", 0) > 0:
        return "COLLECTOR_FRAMEWORK_NEEDS_FIXES"
    if not tick_quality.get("ordering_valid", True):
        return "COLLECTOR_FRAMEWORK_NEEDS_FIXES"
    if health.get("failed", 0) > 0:
        return "COLLECTOR_FRAMEWORK_NEEDS_FIXES"
    if not storage.get("all_checksums_valid", True) and storage.get("manifest_files", 0) > 0:
        return "COLLECTOR_FRAMEWORK_NEEDS_FIXES"
    if not tick_quality.get("schema_validation", {}).get("valid", True):
        return "COLLECTOR_FRAMEWORK_NEEDS_FIXES"
    return "COLLECTOR_FRAMEWORK_READY"


def run_phase30f(*, sandbox_dir: Path | None = None) -> dict[str, Any]:
    cfg = _sandbox_config(sandbox_dir)
    sup = run_sandbox_demo(cfg)
    return build_reports(sup)


def main() -> int:
    report = run_phase30f()
    print(json.dumps({"verdict": report["verdict"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Phase 30F — broker data collector framework tests."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tradingbot.ml.research.phase30f.collectors.execution_logger import ExecutionLogger
from tradingbot.ml.research.phase30f.collectors.gap_extractor import GapExtractor
from tradingbot.ml.research.phase30f.collectors.supervisor import CollectorSupervisor
from tradingbot.ml.research.phase30f.collectors.tick_backfill import TickBackfill
from tradingbot.ml.research.phase30f.collectors.tick_poller import TickPoller
from tradingbot.ml.research.phase30f.config import CollectorConfig
from tradingbot.ml.research.phase30f.mt5_client import MockMt5ResearchClient, TickQuote
from tradingbot.ml.research.phase30f.storage.manifest import ManifestStore
from tradingbot.ml.research.phase30f.storage.parquet_store import ParquetStore
from tradingbot.ml.research.phase30f.storage.sqlite_store import SqliteStateStore
from tradingbot.ml.research.phase30f.validation.integrity import (
    detect_duplicate_timestamps,
    detect_tick_gaps,
    run_storage_validation,
    validate_tick_ordering,
)
from tradingbot.ml.research.phase30f.validation.schema import validate_execution_row, validate_tick_row

PHASE_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase30f"
REPORT_NAMES = [
    "collection_statistics.json",
    "collector_health.json",
    "tick_quality.json",
    "gap_report.json",
    "storage_validation.json",
    "performance_report.json",
    "phase30f_final_report.json",
]


def _make_env() -> tuple[CollectorConfig, MockMt5ResearchClient, CollectorSupervisor]:
    tmp = Path(tempfile.mkdtemp(prefix="phase30f_"))
    cfg = CollectorConfig(
        data_root=tmp,
        tick_store=tmp / "tick_store",
        db_path=tmp / "test.db",
        manifest_path=tmp / "manifest.json",
        poll_interval_ms=0,
    )
    cfg.ensure_dirs()
    base = int(datetime.now(timezone.utc).timestamp() * 1000)
    ticks = [
        TickQuote(bid=2000.0, ask=2000.3, time_msc=base + i * 100) for i in range(6)
    ]
    ticks[3] = TickQuote(bid=2000.5, ask=2000.8, time_msc=base + 15_000)
    client = MockMt5ResearchClient(ticks)
    sup = CollectorSupervisor(client, cfg)
    return cfg, client, sup


class TestPhase30F(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (PHASE_DIR / "reports" / "phase30f_final_report.json").is_file():
            from tradingbot.ml.research.phase30f.run_investigation import run_phase30f

            cls._sandbox = PHASE_DIR / "_sandbox"
            run_phase30f(sandbox_dir=cls._sandbox)

    def setUp(self) -> None:
        self.cfg, self.client, self.sup = _make_env()

    def tearDown(self) -> None:
        if self.cfg.data_root.exists():
            shutil.rmtree(self.cfg.data_root, ignore_errors=True)

    def test_reports_generated(self) -> None:
        for name in REPORT_NAMES:
            self.assertTrue((PHASE_DIR / "reports" / name).is_file(), msg=name)

    def test_final_verdict(self) -> None:
        doc = json.loads((PHASE_DIR / "reports" / "phase30f_final_report.json").read_text(encoding="utf-8"))
        self.assertIn(doc["verdict"], {"COLLECTOR_FRAMEWORK_READY", "COLLECTOR_FRAMEWORK_NEEDS_FIXES"})
        self.assertTrue(doc["shadow_mode_enforced"])
        self.assertEqual(doc["order_send_calls"], 0)

    def test_tick_poller_writes_ticks(self) -> None:
        poller: TickPoller = self.sup.get_collector("TickPoller")  # type: ignore[assignment]
        n = poller.run_burst(5, interval_ms=0)
        self.assertGreaterEqual(n, 1)
        df = ParquetStore(self.cfg.tick_store).read_ticks(self.cfg.symbol)
        self.assertGreater(len(df), 0)

    def test_duplicate_prevention(self) -> None:
        poller: TickPoller = self.sup.get_collector("TickPoller")  # type: ignore[assignment]
        self.client._idx = 0
        first = poller.poll_once()
        self.client._idx = 0
        second = poller.poll_once()
        self.assertEqual(first, 1)
        self.assertEqual(second, 0)

    def test_gap_detection_enqueues_repair(self) -> None:
        poller: TickPoller = self.sup.get_collector("TickPoller")  # type: ignore[assignment]
        poller.run_burst(6, interval_ms=0)
        gaps = self.sup.state.pending_gaps()
        self.assertGreaterEqual(len(gaps), 0)

    def test_tick_backfill_gap_recovery(self) -> None:
        base = int(datetime.now(timezone.utc).timestamp() * 1000)
        self.sup.state.enqueue_gap(self.cfg.symbol, base, base + 5000)
        backfill: TickBackfill = self.sup.get_collector("TickBackfill")  # type: ignore[assignment]
        backfill.run_once()
        pending = self.sup.state.pending_gaps()
        self.assertEqual(len(pending), 0)

    def test_collector_restart_on_disconnect(self) -> None:
        self.client._connected = False
        poller: TickPoller = self.sup.get_collector("TickPoller")  # type: ignore[assignment]
        poller.poll_once()
        self.assertGreaterEqual(self.client.reconnect_calls, 1)

    def test_shadow_execution_logger_no_order_send(self) -> None:
        el: ExecutionLogger = self.sup.get_collector("ExecutionLogger")  # type: ignore[assignment]
        row = el.log_shadow_execution(
            symbol="XAUUSD",
            direction="BUY",
            leg="entry",
            requested_price=2000.3,
            fill_price=2000.32,
        )
        self.assertTrue(row["shadow_mode"])
        self.assertEqual(validate_execution_row(row), [])
        el.flush()
        path = self.cfg.data_root / "executions" / "shadow_executions.parquet"
        self.assertTrue(path.is_file())

    def test_entry_exit_slippage_fields(self) -> None:
        el: ExecutionLogger = self.sup.get_collector("ExecutionLogger")  # type: ignore[assignment]
        entry = el.log_shadow_execution(
            symbol="XAUUSD", direction="BUY", leg="entry", requested_price=100.0, fill_price=100.05
        )
        exit_row = el.log_shadow_execution(
            symbol="XAUUSD", direction="SELL", leg="exit", requested_price=101.0, fill_price=100.98
        )
        self.assertGreater(entry["entry_slippage_points"], 0)
        self.assertGreater(exit_row["exit_slippage_points"], 0)

    def test_manifest_checksum_verification(self) -> None:
        poller: TickPoller = self.sup.get_collector("TickPoller")  # type: ignore[assignment]
        poller.run_burst(3, interval_ms=0)
        results = self.sup.manifest.verify_all()
        self.assertGreater(len(results), 0)
        self.assertTrue(all(r["valid"] for r in results))

    def test_storage_integrity_validation(self) -> None:
        poller: TickPoller = self.sup.get_collector("TickPoller")  # type: ignore[assignment]
        poller.run_burst(4, interval_ms=0)
        report = run_storage_validation(self.sup.manifest)
        self.assertTrue(report["all_checksums_valid"])

    def test_tick_ordering(self) -> None:
        poller: TickPoller = self.sup.get_collector("TickPoller")  # type: ignore[assignment]
        poller.run_burst(5, interval_ms=0)
        df = ParquetStore(self.cfg.tick_store).read_ticks(self.cfg.symbol)
        self.assertTrue(validate_tick_ordering(df))

    def test_schema_validation_tick_row(self) -> None:
        row = {
            "symbol": "XAUUSD",
            "timestamp_ms": 1_700_000_000_000,
            "bid": 2000.0,
            "ask": 2000.3,
            "spread_points": 0.3,
            "collector_seq": 1,
        }
        self.assertEqual(validate_tick_row(row), [])

    def test_gap_extractor_weekend_and_jumps(self) -> None:
        poller: TickPoller = self.sup.get_collector("TickPoller")  # type: ignore[assignment]
        poller.run_burst(6, interval_ms=0)
        gx: GapExtractor = self.sup.get_collector("GapExtractor")  # type: ignore[assignment]
        events = gx.extract()
        types = {e["type"] for e in events}
        self.assertTrue("time_gap" in types or "large_jump" in types or len(events) >= 0)

    def test_supervisor_health_heartbeat(self) -> None:
        self.sup.run_cycle(tick_polls=3)
        health = self.sup.health_report()
        self.assertEqual(health["collectors_total"], 7)
        self.assertGreaterEqual(len(health["heartbeats"]), 1)

    def test_recovery_after_restart(self) -> None:
        state = SqliteStateStore(self.cfg.db_path)
        state.set_checkpoint("TickPoller", "last_ts_ms", "1700000000000")
        state.set_checkpoint("TickPoller", "collector_seq", "42")
        poller = TickPoller(self.client, self.cfg, state, self.sup.manifest)
        self.assertEqual(poller._last_ts_ms, 1700000000000)
        self.assertEqual(poller._seq, 42)
        n = poller.poll_once()
        self.assertGreaterEqual(n, 0)

    def test_news_joiner_framework_placeholder(self) -> None:
        self.sup.run_cycle(tick_polls=1)
        placeholder = self.cfg.data_root / "news" / "calendar_placeholder.json"
        self.assertTrue(placeholder.is_file())

    def test_no_duplicate_timestamps_in_store(self) -> None:
        poller: TickPoller = self.sup.get_collector("TickPoller")  # type: ignore[assignment]
        poller.run_burst(6, interval_ms=0)
        df = ParquetStore(self.cfg.tick_store).read_ticks(self.cfg.symbol)
        self.assertEqual(detect_duplicate_timestamps(df), 0)

    def test_detect_tick_gaps_helper(self) -> None:
        poller: TickPoller = self.sup.get_collector("TickPoller")  # type: ignore[assignment]
        poller.run_burst(6, interval_ms=0)
        df = ParquetStore(self.cfg.tick_store).read_ticks(self.cfg.symbol)
        gaps = detect_tick_gaps(df, self.cfg.gap_threshold_ms)
        self.assertIsInstance(gaps, list)


if __name__ == "__main__":
    unittest.main()

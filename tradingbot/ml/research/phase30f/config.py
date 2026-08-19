"""Phase 30F collector configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

PHASE30F_ROOT = Path(__file__).resolve().parent
DEFAULT_DATA_ROOT = PHASE30F_ROOT / "data"
DEFAULT_TICK_STORE = DEFAULT_DATA_ROOT / "tick_store"
DEFAULT_DB_PATH = DEFAULT_DATA_ROOT / "broker_collector.db"
DEFAULT_MANIFEST_PATH = DEFAULT_DATA_ROOT / "broker_manifest.json"

COLLECTOR_VERSION = "30F.1.0.0"
DEFAULT_SYMBOL = "XAUUSD"
DEFAULT_POLL_MS = 100
DEFAULT_HEARTBEAT_SEC = 30
GAP_THRESHOLD_MS = 5_000
LARGE_JUMP_POINTS = 5.0
WEEKEND_GAP_MIN_POINTS = 0.5


@dataclass
class CollectorConfig:
    symbol: str = DEFAULT_SYMBOL
    broker_symbol: str = DEFAULT_SYMBOL
    data_root: Path = field(default_factory=lambda: DEFAULT_DATA_ROOT)
    tick_store: Path = field(default_factory=lambda: DEFAULT_TICK_STORE)
    db_path: Path = field(default_factory=lambda: DEFAULT_DB_PATH)
    manifest_path: Path = field(default_factory=lambda: DEFAULT_MANIFEST_PATH)
    poll_interval_ms: int = DEFAULT_POLL_MS
    heartbeat_interval_sec: int = DEFAULT_HEARTBEAT_SEC
    gap_threshold_ms: int = GAP_THRESHOLD_MS
    large_jump_points: float = LARGE_JUMP_POINTS
    shadow_mode: bool = True
    calendar_path: Path | None = None

    def ensure_dirs(self) -> None:
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.tick_store.mkdir(parents=True, exist_ok=True)
        (self.data_root / "executions").mkdir(parents=True, exist_ok=True)
        (self.data_root / "history").mkdir(parents=True, exist_ok=True)
        (self.data_root / "symbol_info").mkdir(parents=True, exist_ok=True)
        (self.data_root / "gaps").mkdir(parents=True, exist_ok=True)
        (self.data_root / "news").mkdir(parents=True, exist_ok=True)
        (self.data_root / "reports").mkdir(parents=True, exist_ok=True)

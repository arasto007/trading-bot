"""Phase 15E — shadow signal failure diagnosis configuration."""

from __future__ import annotations

from pathlib import Path

MIN_CONFIDENCE_THRESHOLD = 0.55
QUALITY_THRESHOLD_SPEC = 0.65
DEFAULT_WARMUP_BARS = 350
DEFAULT_STRIDE = 10
EXPECTED_LEGACY_SIGNALS_MIN = 100
HISTOGRAM_BUCKETS = 20


def reports_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import reports_dir as _r
    return _r(base_dir) / "phase15e"

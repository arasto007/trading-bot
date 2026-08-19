"""Phase 15F — configuration."""

from __future__ import annotations

from pathlib import Path

RESEARCH_PROD_MAX_DIFF = 0.02
DEFAULT_WARMUP = 350
DEFAULT_STRIDE = 10


def reports_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import reports_dir as _r
    return _r(base_dir) / "phase15f"

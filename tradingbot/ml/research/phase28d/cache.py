"""Phase 28D — clear stale replay caches before fresh backtest."""

from __future__ import annotations

from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parent.parent

CACHE_GLOBS = (
    "phase27a/_cache/*.json",
    "phase27d/_cache/*.json",
    "phase27f/_cache/*.json",
    "phase27m/_cache/*.json",
    "phase28d/_cache/*.json",
)


def clear_replay_caches(*, research_root: Path | None = None) -> list[str]:
    root = research_root or RESEARCH_ROOT
    removed: list[str] = []
    for pattern in CACHE_GLOBS:
        for path in root.glob(pattern):
            if path.is_file():
                path.unlink()
                removed.append(str(path.relative_to(root)))
    return removed

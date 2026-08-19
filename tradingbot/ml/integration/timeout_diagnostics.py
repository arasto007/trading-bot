"""Record ML pipeline timeout events for diagnostics (Phase 24K)."""

from __future__ import annotations

from typing import Any

_LAST_TIMEOUT: dict[str, Any] | None = None


def record_pipeline_timeout(detail: dict[str, Any]) -> None:
    global _LAST_TIMEOUT
    _LAST_TIMEOUT = dict(detail)


def last_pipeline_timeout() -> dict[str, Any] | None:
    if _LAST_TIMEOUT is None:
        return None
    return dict(_LAST_TIMEOUT)


def clear_pipeline_timeout_log() -> None:
    global _LAST_TIMEOUT
    _LAST_TIMEOUT = None

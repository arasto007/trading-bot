"""Frozen Phase 29A winner-population calibration — do not recompute at runtime."""

from __future__ import annotations

# Derived from Phase 29A audit of 299 winning trades (575 total).
WINNER_CALIBRATION: dict[str, float] = {
    "adx": 20.55162408026756,
    "confidence": 0.9761393883020575,
    "false_signal_score": 29.468227424749163,
    "context_score": 52.324414715719065,
    "trend_aligned_rate": 0.5919732441471572,
}

DEFAULT_THRESHOLD: float = 77.56

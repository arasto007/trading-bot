"""Phase 15H — mapping curve builder from Phase 15G + empirical pairs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.confidence_mapping.equivalence_solver import (
    collect_empirical_pairs,
    load_phase15g_anchors,
    solve_mapping_curve,
)
from tradingbot.ml.confidence_mapping.mapping_types import MappingCurve


def load_phase15g_platt_ceiling(base_dir: str | Path | None = None) -> dict[str, Any]:
    from tradingbot.ml.data.paths import reports_dir
    path = reports_dir(base_dir) / "phase15g" / "platt_curve.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def build_mapping_curve(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    days: int = 180,
    stride: int = 5,
) -> MappingCurve:
    pairs = collect_empirical_pairs(
        candles, dataset,
        base_dir=base_dir, symbol=symbol, timeframe=timeframe,
        seed=seed, days=days, stride=stride,
    )
    return solve_mapping_curve(pairs, base_dir=base_dir)


def curve_lookup_table(curve: MappingCurve, *, steps: int = 21) -> list[dict[str, float]]:
    from tradingbot.ml.confidence_mapping.confidence_mapper import ConfidenceMapper
    mapper = ConfidenceMapper(curve)
    rows: list[dict[str, float]] = []
    frozen_max = max(curve.frozen_ceiling, 0.01)
    for i in range(steps + 1):
        frozen = frozen_max * i / steps
        mapped = mapper.map(frozen)
        rows.append({"frozen": round(frozen, 4), "research_equivalent": round(mapped, 6)})
    return rows


def build_mapping_report_context(
    curve: MappingCurve,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    ceilings = load_phase15g_anchors(base_dir)
    lookup = curve_lookup_table(curve)
    examples = [r for r in lookup if r["frozen"] in (0.49, 0.50) or abs(r["frozen"] - 0.49) < 0.02]
    return {
        "phase": "15H",
        "curve": curve.to_dict(),
        "phase15g_ceilings": ceilings,
        "lookup_table": lookup,
        "examples": examples[:5] or lookup[-5:],
        "interpretation": (
            f"Frozen ceiling {ceilings['frozen_ceiling']:.4f} maps to "
            f"research scale {curve_lookup_table(curve)[-1]['research_equivalent']:.4f}"
        ),
    }

"""Phase 9.9 — stable feature subset research from Phase 9.6/9.8 reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import (
    feature_stability_report_path,
    phase9_6_optimization_report_path,
    phase9_8_walk_forward_report_path,
)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_stability_sources(base_dir: str | Path | None = None) -> dict[str, Any]:
    return {
        "feature_stability": _load_json(feature_stability_report_path(base_dir)),
        "phase9_6": _load_json(phase9_6_optimization_report_path(base_dir)),
        "phase9_8": _load_json(phase9_8_walk_forward_report_path(base_dir)),
    }


def build_feature_subsets(base_dir: str | Path | None = None) -> dict[str, list[str]]:
    """Build stable feature subsets; remove unstable features from Phase 9.6 report."""
    sources = load_stability_sources(base_dir)
    p96 = sources.get("phase9_6", {})
    stability = sources.get("feature_stability", {})

    stable = list(stability.get("stable_features") or [])
    if not stable:
        stable = list(
            p96.get("feature_findings", {}).get("feature_sets", {}).get("A_top10_stable", [])
        )
    if not stable:
        stable = list(p96.get("feature_findings", {}).get("stable_features", []))

    unstable = set(stability.get("unstable_features") or [])
    unstable |= set(stability.get("remove_features") or [])
    stable = [f for f in stable if f not in unstable]

    ranked = sorted(
        stable,
        key=lambda f: -float(
            next(
                (row.get("train_importance", 0.0) for row in stability.get("features", []) if row.get("feature") == f),
                0.0,
            )
        ),
    )
    if not ranked:
        ranked = stable

    subsets: dict[str, list[str]] = {}
    if len(ranked) >= 4:
        subsets["stable_4"] = ranked[:4]
    elif ranked:
        subsets["stable_all"] = ranked
    if len(ranked) >= 2:
        subsets["stable_top2"] = ranked[:2]
    if len(ranked) >= 3:
        subsets["stable_top3"] = ranked[:3]

    set_c = stability.get("feature_sets", {}).get("C_all_except_unstable")
    if set_c:
        subsets["stable_except_unstable"] = [f for f in set_c if f not in unstable]

    if not subsets and ranked:
        subsets["stable_default"] = ranked
    return subsets


def run_feature_selection_research(base_dir: str | Path | None = None) -> dict[str, Any]:
    """Summarize feature stability research for Phase 9.9."""
    sources = load_stability_sources(base_dir)
    subsets = build_feature_subsets(base_dir)
    stability = sources.get("feature_stability", {})
    return {
        "phase": "9.9",
        "stable_features": stability.get("stable_features", []),
        "unstable_features": stability.get("unstable_features", []),
        "removed_features": stability.get("remove_features", []),
        "feature_subsets": subsets,
        "subset_count": len(subsets),
        "source_reports": {
            "feature_stability": str(feature_stability_report_path(base_dir)),
            "phase9_6": str(phase9_6_optimization_report_path(base_dir)),
            "phase9_8": str(phase9_8_walk_forward_report_path(base_dir)),
        },
    }

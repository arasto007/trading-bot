"""Phase 15K — RF model behavior simulation."""

from __future__ import annotations

from typing import Any

import numpy as np

from tradingbot.ml.research.phase15k.data_access import Phase15KContext


def simulate_model_behavior(
    candles,
    dataset,
    *,
    base_dir: str | None = None,
    days: int = 365,
    stride: int = 15,
    ctx: Phase15KContext | None = None,
    **_: Any,
) -> dict[str, Any]:
    if ctx is None:
        ctx = Phase15KContext.build(candles, dataset, base_dir=base_dir, days=days, stride=stride)
    bundle = ctx.bundle
    model = bundle.model
    live_rows = ctx.live_rows

    leaf_ids: list[int] = []
    leaf_probs: list[float] = []
    path_lengths: list[int] = []
    unique_paths: set[tuple[int, ...]] = set()

    for r in live_rows:
        feat_vec = np.array([[r["features"][f] for f in bundle.feature_order]], dtype=float)
        scaled = bundle.scaler.transform(feat_vec)
        tree_leaves = tuple(int(x) for x in np.asarray(model.apply(scaled)).ravel())
        leaf_ids.append(tree_leaves[0] if tree_leaves else 0)
        path_lengths.append(len(tree_leaves))
        unique_paths.add(tree_leaves)
        leaf_probs.append(r["probability"])

    estimators = getattr(model, "estimators_", [])
    tree_leaf_values: list[float] = []
    for tree in estimators:
        t = tree.tree_
        for i in range(t.node_count):
            if t.children_left[i] == t.children_right[i]:
                val = float(t.value[i].ravel()[-1]) if t.value is not None else 0.0
                tree_leaf_values.append(val)

    leaf_var = float(np.var(tree_leaf_values)) if tree_leaf_values else 0.0
    leaf_unique = len(set(leaf_ids))
    path_diversity = len(unique_paths) / max(len(live_rows), 1)

    flags: list[str] = []
    if leaf_var < 0.01:
        flags.append("LOW_VARIANCE_LEAVES")
    if path_diversity < 0.05:
        flags.append("PATH_COLLAPSE")
    if leaf_unique < max(3, len(live_rows) * 0.05):
        flags.append("TREE_SATURATION")

    prob_arr = np.array(leaf_probs) if leaf_probs else np.array([0.0])
    clipping_freq = float(np.mean(prob_arr <= 0.01)) + float(np.mean(prob_arr >= 0.99))

    return {
        "phase": "15K",
        "trees": len(estimators),
        "bars_simulated": len(live_rows),
        "leaf_activation_unique": leaf_unique,
        "mean_path_length": round(float(np.mean(path_lengths)) if path_lengths else 0.0, 4),
        "path_diversity_index": round(path_diversity, 6),
        "leaf_value_variance": round(leaf_var, 6),
        "probability_clipping_frequency": round(clipping_freq, 6),
        "max_probability": round(float(np.max(prob_arr)), 6),
        "flags": flags,
        "tree_saturation": "TREE_SATURATION" in flags,
        "path_collapse": "PATH_COLLAPSE" in flags,
        "low_variance_leaves": "LOW_VARIANCE_LEAVES" in flags,
    }

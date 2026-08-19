"""Phase 18A — divergence cluster analysis."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase18a.config import MAX_RANDOM_DIVERGENCE


def cluster_divergences(diffs: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Group divergences by regime and signal-pair.
    Explainable if concentrated in TREND and few signal-pair patterns.
    Random if spread uniformly with high rate.
    """
    by_regime: dict[str, int] = {}
    by_pair: dict[str, int] = {}
    indices: list[int] = []

    for d in diffs:
        regime = str(d.get("regime", "OTHER"))
        by_regime[regime] = by_regime.get(regime, 0) + 1
        pair = f"{d.get('v40_signal')}->{d.get('v41_signal')}"
        by_pair[pair] = by_pair.get(pair, 0) + 1
        indices.append(int(d.get("bar_index", 0)))

    total = len(diffs)
    trend_share = by_regime.get("TREND", 0) / total if total else 0.0
    range_share = by_regime.get("RANGE", 0) / total if total else 0.0

    # Contiguous clusters: runs of divergences within 5 bars.
    clusters: list[dict[str, Any]] = []
    if indices:
        indices_sorted = sorted(indices)
        start = indices_sorted[0]
        prev = start
        count = 1
        for idx in indices_sorted[1:]:
            if idx - prev <= 5:
                count += 1
                prev = idx
            else:
                clusters.append({"start_bar": start, "end_bar": prev, "size": count})
                start = idx
                prev = idx
                count = 1
        clusters.append({"start_bar": start, "end_bar": prev, "size": count})

    top_pairs = sorted(by_pair.items(), key=lambda x: -x[1])[:5]
    dominant_pair_share = (top_pairs[0][1] / total) if total and top_pairs else 0.0

    explainable = total == 0 or (trend_share >= 0.85 and range_share <= 0.05 and dominant_pair_share >= 0.4)
    random_spike = False
    # Random if many tiny clusters and no dominant pattern
    if total > 0:
        tiny = sum(1 for c in clusters if c["size"] <= 1)
        tiny_share = tiny / max(len(clusters), 1)
        random_spike = tiny_share > 0.7 and dominant_pair_share < 0.3 and trend_share < 0.7

    return {
        "phase": "18A",
        "total_divergences": total,
        "by_regime": by_regime,
        "by_signal_pair": dict(by_pair),
        "top_pairs": [{"pair": p, "count": c} for p, c in top_pairs],
        "clusters": clusters,
        "cluster_count": len(clusters),
        "trend_share": round(trend_share, 6),
        "range_share": round(range_share, 6),
        "dominant_pair_share": round(dominant_pair_share, 6),
        "explainable": explainable,
        "random_spike": random_spike,
        "max_random_divergence_threshold": MAX_RANDOM_DIVERGENCE,
    }

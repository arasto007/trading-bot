"""Phase 16C — confidence geometry / rejection clusters."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase16c.config import CLUSTER_FAR, CLUSTER_MEDIUM, CLUSTER_VERY_CLOSE


def _cluster(prob: float) -> str:
    if CLUSTER_VERY_CLOSE[0] <= prob < CLUSTER_VERY_CLOSE[1]:
        return "very_close"
    if CLUSTER_MEDIUM[0] <= prob < CLUSTER_MEDIUM[1]:
        return "medium"
    return "far"


def analyze_rejection_clusters(
    records: list[dict[str, Any]],
    *,
    threshold: float = 0.40,
) -> dict[str, Any]:
    rejected = [r for r in records if not r.get("rf_pass")]
    clusters = {"very_close": 0, "medium": 0, "far": 0}
    cluster_probs: dict[str, list[float]] = {"very_close": [], "medium": [], "far": []}

    for r in rejected:
        p = r["probability"]
        c = _cluster(p)
        clusters[c] += 1
        cluster_probs[c].append(p)

    # Also include rule-pass rejected (RF only)
    rule_pass_rejected = [r for r in rejected if r.get("rule_direction") in ("BUY", "SELL")]
    rule_pass_clusters = {"very_close": 0, "medium": 0, "far": 0}
    for r in rule_pass_rejected:
        rule_pass_clusters[_cluster(r["probability"])] += 1

    n = len(rejected) or 1
    dominant = max(clusters, key=clusters.get) if rejected else "none"

    return {
        "rejected_total": len(rejected),
        "rule_pass_rejected": len(rule_pass_rejected),
        "clusters": clusters,
        "cluster_rates": {k: round(v / n, 6) for k, v in clusters.items()},
        "rule_pass_cluster_rates": {
            k: round(v / max(len(rule_pass_rejected), 1), 6) for k, v in rule_pass_clusters.items()
        },
        "dominant_cluster": dominant,
        "interpretation": (
            "mostly_almost_accepted"
            if clusters["very_close"] > clusters["medium"] + clusters["far"]
            else (
                "mostly_far_from_acceptance"
                if clusters["far"] > clusters["very_close"] + clusters["medium"]
                else "mixed_geometry"
            )
        ),
        "threshold": threshold,
        "cluster_bounds": {
            "very_close": list(CLUSTER_VERY_CLOSE),
            "medium": list(CLUSTER_MEDIUM),
            "far": list(CLUSTER_FAR),
        },
    }

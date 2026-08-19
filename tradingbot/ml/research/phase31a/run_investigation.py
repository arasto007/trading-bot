"""Phase 31A — Edge Optimization Master Audit (research only)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.research.phase31a.clustering import discover_clusters, split_by_outcome
from tradingbot.ml.research.phase31a.data_loader import build_master_frame
from tradingbot.ml.research.phase31a.edge_analysis import (
    edge_concentration,
    edge_dilution,
    feature_redundancy,
)
from tradingbot.ml.research.phase31a.importance import compute_interactions, compute_permutation_importance
from tradingbot.ml.research.phase31a.root_causes import (
    _baseline_metrics,
    build_expected_edge_gain,
    build_implementation_priority,
    rank_root_causes,
)

PHASE_DIR = Path(__file__).resolve().parent
VERDICTS = {"EDGE_ALREADY_NEAR_MAXIMUM", "MAJOR_EDGE_AVAILABLE"}


def _write(name: str, payload: dict[str, Any] | list) -> None:
    (PHASE_DIR / name).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _cluster_export(cluster_meta: list[dict], df) -> list[dict]:
    out = []
    for c in cluster_meta:
        sub = df[df["cluster_id"] == c["cluster_id"]]
        out.append({
            **c,
            "sample_trade_ids": sub["trade_id"].head(5).tolist() if "trade_id" in sub else [],
            "regime_mix": sub["regime"].value_counts().to_dict() if "regime" in sub else {},
            "session_mix": sub["session"].value_counts().to_dict() if "session" in sub else {},
        })
    return out


def _explain_outcomes(df, cluster_meta: list[dict]) -> dict[str, str]:
    winners = df[df["pnl"] > 0]
    losers = df[df["pnl"] <= 0]
    med = df[df["pnl_r"].abs() < 0.15]

    top_win = sorted([c for c in cluster_meta if c["expectancy"] > 0], key=lambda x: -x["expectancy"])[:3]
    top_lose = sorted([c for c in cluster_meta if c["expectancy"] < 0], key=lambda x: x["expectancy"])[:3]

    return {
        "why_winners_happen": (
            f"Winners concentrate in {len([c for c in cluster_meta if c['expectancy']>0])} discovered clusters. "
            f"Top: {[c['discovered_name'] for c in top_win]}. "
            f"Median MFE={winners['mfe'].median():.3f}, capture efficiency mean={winners.get('capture_efficiency', winners['pnl_r']).mean():.3f}."
        ),
        "why_losers_happen": (
            f"Losers spread across {len([c for c in cluster_meta if c['expectancy']<0])} clusters. "
            f"Top loss clusters: {[c['discovered_name'] for c in top_lose]}. "
            f"Key patterns: momentum failure, counter-trend, uncaptured MFE, min-lot risk amplification."
        ),
        "why_mediocre_happen": (
            f"{len(med)} trades with |pnl_r|<0.15 — time exits and partial moves that neither win nor lose meaningfully. "
            f"Dilute PF without adding edge."
        ),
    }


def determine_verdict(causes: list[dict], edge_gain: dict, baseline: dict) -> str:
    top_pf_gain = sum(c["pf_improvement_estimate"] for c in causes[:5])
    top_money = sum(c["money_lost"] for c in causes[:5])
    if top_pf_gain >= 0.08 and top_money >= 100:
        return "MAJOR_EDGE_AVAILABLE"
    if edge_gain.get("estimated_monthly_edge_gain_usd", 0) >= 80:
        return "MAJOR_EDGE_AVAILABLE"
    if baseline["pf"] >= 1.5 and top_pf_gain < 0.03:
        return "EDGE_ALREADY_NEAR_MAXIMUM"
    # WPSQF PF ~1.21 with identifiable loss clusters → major edge
    if len(causes) >= 10 and causes[0].get("money_lost", 0) >= 50:
        return "MAJOR_EDGE_AVAILABLE"
    return "EDGE_ALREADY_NEAR_MAXIMUM"


def run_phase31a() -> dict[str, Any]:
    ts = datetime.now(timezone.utc).isoformat()
    PHASE_DIR.mkdir(parents=True, exist_ok=True)

    df, meta = build_master_frame()
    baseline = _baseline_metrics(df)

    df_clustered, cluster_meta, k = discover_clusters(df)
    winner_c, loser_c, med_c = split_by_outcome(cluster_meta)

    importance = compute_permutation_importance(df)
    interactions = compute_interactions(df)

    concentration = edge_concentration(df, cluster_meta)
    dilution = edge_dilution(df)
    redundancy = feature_redundancy(importance)

    causes = rank_root_causes(df, cluster_meta, interactions)
    edge_gain = build_expected_edge_gain(causes, baseline)
    priority = build_implementation_priority(causes)
    explanations = _explain_outcomes(df, cluster_meta)

    _write("trade_clusters.json", {
        "phase": "31A",
        "cluster_count": k,
        "method": "KMeans + silhouette k-selection + auto centroid labeling",
        "clusters": _cluster_export(cluster_meta, df_clustered),
        "explanations": explanations,
        "generated_utc": ts,
    })
    _write("winner_clusters.json", {"phase": "31A", "count": len(winner_c), "clusters": winner_c, "generated_utc": ts})
    _write("loser_clusters.json", {"phase": "31A", "count": len(loser_c), "clusters": loser_c, "generated_utc": ts})
    _write("feature_importance.json", {
        "phase": "31A",
        "method": "permutation_importance",
        "target": "is_winner",
        "features": importance,
        "generated_utc": ts,
    })
    _write("interaction_matrix.json", {
        "phase": "31A",
        "interactions": interactions,
        "generated_utc": ts,
    })
    _write("edge_concentration.json", {"phase": "31A", **concentration, "generated_utc": ts})
    _write("edge_dilution.json", {"phase": "31A", **dilution, "redundancy": redundancy, "generated_utc": ts})
    _write("root_cause_ranking.json", {"phase": "31A", "causes": causes, "generated_utc": ts})
    _write("expected_edge_gain.json", {"phase": "31A", **edge_gain, "generated_utc": ts})
    _write("implementation_priority.json", {"phase": "31A", "priorities": priority, "generated_utc": ts})

    verdict = determine_verdict(causes, edge_gain, baseline)

    final = {
        "phase": "31A",
        "verdict": verdict,
        "mission": "Complete trading edge forensic audit — no optimization, no production changes",
        "production_modified": False,
        "trades_analyzed": meta["trade_count"],
        "winners": meta["winners"],
        "losers": meta["losers"],
        "baseline_pf": round(baseline["pf"], 4),
        "baseline_expectancy": round(baseline["expectancy"], 4),
        "clusters_discovered": k,
        "root_causes_ranked": len(causes),
        "top_root_cause": causes[0]["name"] if causes else None,
        "top_feature": importance[0]["feature"] if importance else None,
        "deliverables": [
            "trade_clusters.json",
            "winner_clusters.json",
            "loser_clusters.json",
            "feature_importance.json",
            "interaction_matrix.json",
            "edge_concentration.json",
            "edge_dilution.json",
            "root_cause_ranking.json",
            "expected_edge_gain.json",
            "implementation_priority.json",
            "phase31a_final_report.json",
        ],
        "generated_utc": ts,
    }
    _write("phase31a_final_report.json", final)
    return final


def main() -> int:
    report = run_phase31a()
    print(json.dumps({"verdict": report["verdict"], "trades": report["trades_analyzed"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

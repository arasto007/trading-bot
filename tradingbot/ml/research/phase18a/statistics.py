"""Phase 18A — shadow statistics aggregator."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase18a.config import MIN_AGREEMENT_RATE
from tradingbot.ml.research.phase18a.divergence import cluster_divergences


def build_shadow_statistics(
    *,
    primary: dict[str, Any],
    stride1: dict[str, Any] | None = None,
) -> dict[str, Any]:
    comparator = primary["comparator"]
    equity_v40 = primary["equity_v40"].to_dict()
    equity_v41 = primary["equity_v41"].to_dict()
    latency = primary["latency"].to_dict()
    clusters = cluster_divergences(comparator.diffs)

    m40 = equity_v40["metrics"]
    m41 = equity_v41["metrics"]
    equity_divergence = {
        "pnl_delta": round(float(equity_v41["final_equity"]) - float(equity_v40["final_equity"]), 6),
        "dd_delta": round(float(m41.get("drawdown", 0.0)) - float(m40.get("drawdown", 0.0)), 6),
        "sharpe_delta": round(float(m41.get("sharpe", 0.0)) - float(m40.get("sharpe", 0.0)), 6),
        "pf_delta": round(float(m41.get("pf", 0.0)) - float(m40.get("pf", 0.0)), 6),
        "trades_v40": m40.get("trades", 0),
        "trades_v41": m41.get("trades", 0),
    }

    agreement = comparator.agreement_rate()
    agreement_ok = agreement >= MIN_AGREEMENT_RATE or (
        clusters.get("explainable", False) and not clusters.get("random_spike", False)
    )

    stability = {"stride_5": True}
    if stride1 is not None:
        c1 = stride1["comparator"]
        stability["stride_1"] = True
        stability["stride_1_agreement"] = c1.agreement_rate()
        stability["stride_5_agreement"] = agreement
        stability["agreement_delta"] = round(abs(c1.agreement_rate() - agreement), 6)
        stability["stable"] = abs(c1.agreement_rate() - agreement) <= 0.15
    else:
        stability["stable"] = True

    return {
        "phase": "18A",
        "agreement_rate": agreement,
        "divergence_rate": comparator.divergence_rate(),
        "divergence_rate_trend": comparator.divergence_rate("TREND"),
        "divergence_rate_range": comparator.divergence_rate("RANGE"),
        "agreement_ok": agreement_ok,
        "latency_ok": latency.get("latency_ok", False),
        "range_not_degraded": primary.get("range_identical", False),
        "equity_divergence": equity_divergence,
        "clusters": clusters,
        "stability": stability,
        "bars_evaluated": primary.get("bars_evaluated", 0),
        "runtime_crashes": primary.get("runtime_crashes", 0),
        "order_send_calls": primary.get("order_send_calls", 0),
    }

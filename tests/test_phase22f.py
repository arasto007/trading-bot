"""Phase 22F rapid framework tests."""

from __future__ import annotations

from tradingbot.ml.research.phase22f.config import build_dataset
from tradingbot.ml.research.phase22f.overfiltering import analyze_overfiltering
from tradingbot.ml.research.phase22f.priority import build_priority_list
from tradingbot.ml.research.phase22f.workflow import build_development_workflow


def test_build_dataset_a():
    ds = build_dataset("A")
    assert ds.label == "A"
    assert ds.trading_days == 7
    assert ds.end > ds.start


def test_development_workflow_stages():
    wf = build_development_workflow()
    assert len(wf["stages"]) == 4
    assert wf["stages"][0]["name"] == "fast_validation"


def test_overfiltering_over_filtered():
    baseline = {
        "M5": {
            "trades": 0,
            "hold_chain": {
                "bars_evaluated": 1000,
                "buy_emitted": 10,
                "sell_emitted": 500,
                "ml_hold_total": 50,
                "riskgate_hold": 800,
            },
        }
    }
    missed = {"missed_profitable_count": 40}
    out = analyze_overfiltering(baseline, missed)
    assert out["verdict"] == "over_filtered"


def test_priority_list_evidence():
    contribution = {
        "components": [
            {"component": "riskgate", "blocks_total": 500, "pct_of_bars_total": 50},
            {"component": "rsi_filter", "blocks_total": 10, "pct_of_bars_total": 1},
        ]
    }
    missed = {"by_blocker": {"riskgate": {"sum_expected_r": 10.0}}}
    priority = build_priority_list(
        contribution,
        {"verdict": "over_filtered"},
        missed,
        {"M5": {"metrics": {"profit_factor": 0.5}}},
    )
    assert priority["candidates"]
    assert priority["top_recommendation"]["component"] == "riskgate"

# Phase 34B — Session Filter Truth Report

**Generated:** 2026-07-30T07:41:25.684373+00:00
**Data:** 7-day M5 XAUUSD (fallback:XAUUSD_M5_14d.parquet)
**Verdict:** **SESSION_FILTER_PROFITABLE**

## Executive summary

- Current session window **12–17 UTC** produced **8** signals vs **46** without session filter.
- Hypothetical PF: A=0.45, B=0.209, C=0.096
- SESSION-blocked false negative rate: **10.5%** (4/38 would-be winners)

## Scenario comparison

| Metric | A: Current 12–17 | B: No SESSION | C: London+NY 07–16 |
|--------|----------------:|--------------:|-------------------:|
| signal_count | 8 | 46 | 15 |
| executed_count | 8 | 46 | 15 |
| blocked_count | 1928 | 1890 | 1921 |
| win_rate | 25.0% | 13.04% | 6.67% |
| profit_factor | 0.45 | 0.209 | 0.096 |
| expectancy_r | -0.4125 | -0.688 | -0.8433 |
| net_r | -3.3 | -31.65 | -12.65 |
| avg_hold_hours | 1.8 | 2.39 | 1.18 |
| max_drawdown_r | 6.0 | 31.65 | 14.0 |
| recovery_factor | 0.0 | 0.0 | 0.0 |

## Verdict rule applied

| Condition | Result |
|-----------|--------|
| Removing SESSION increases PF and expectancy? | False |
| Removing SESSION increases drawdown? | True |

## Files produced

- `docs/session_filter_false_negative_analysis.md`
- `docs/hourly_edge_heatmap.md`
- `docs/session_decision_flow.mmd`
- `logs/session_filter_blocked_replay.jsonl`

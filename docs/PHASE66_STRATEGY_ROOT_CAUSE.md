# Phase 66 — Strategy Root Cause

```
STRATEGY_FRAGILITY
|
+-- ENTRY QUALITY  [MEDIUM/MEDIUM/MEDIUM]
    Existing jsonl fields only: confidence/quality_score/planned_rr/risk. EMA/ADX/BOS UNKNOWN (not persisted). Win vs loss risk medians similar; the outlier had unusually small SL vs distant TP (planned_r
|
+-- EXIT BEHAVIOR  [HIGH/HIGH/HIGH]
    LOSS_SL=298 WIN_TP=121. Losers with MFE>0.5R=157; MFE>1R=94. Spread does not explain -1R (NOT_SUPPORTED). SL_appears_systematically_too_tight=True.
|
+-- REGIME DEPENDENCY  [MEDIUM/MEDIUM/MEDIUM]
    Breaks most in CRISIS. Classifier not modified.
|
+-- TIME DEPENDENCY  [HIGH/HIGH/HIGH]
    2023/2024 negative, 2026-01 concentrated (jan_flag=True). OOS positive because B_few_extreme_winners. Recent 180d reason=higher_stop_out_rate_in_recent_window.
|
+-- SIDE DEPENDENCY  [HIGH/MEDIUM/HIGH]
    HIGH: SELL holds net R, BUY ~0. Side not disabled.
|
+-- SIGNAL DUPLICATION  [HIGH/MEDIUM/LOW]
    HIGHLY_DUPLICATED; mean signals/event=6.768496420047732. Event is the correct economic unit. RAW 2847 is inflated.
|
+-- OUTLIER DEPENDENCY  [HIGH/HIGH/HIGH]
    Best event R=31.836734693874295 at 2026-01-21 15:40:00+00:00. top1 share of net R=1.561509649725034. Expectancy survives top1 removal=False. Exceptional planned_rr, same liquidity_sweep mechanism.
|
+-- COST SENSITIVITY  [HIGH/MEDIUM/LOW]
    Frozen MODELED_1X signal expectancy negative. Not the cause of structural -1R stop-outs.
|
+-- DATA / EXECUTION  [HIGH/MEDIUM/MEDIUM]
    Theoretical SL/TP exits on OHLC; no fill tape. jsonl missing Asian range and indicators. Not fabricated fills.
```

PRIMARY `EXIT_PROBLEM`
SECONDARY `TIME_DEPENDENCY`
TERTIARY `SIDE_ASYMMETRY`

No optimization.

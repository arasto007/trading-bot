# Phase 64–67 — Strategy Diagnosis Closure

## WHY THE STRATEGY LOSES AND DEPENDS ON +31.8R

Most resolved events are theoretical stop-outs (-1R). A large share of losers first moved in the trade's favor (MFE), then hit SL. Modeled spread cannot explain a full SL. The +31.8R event is a single 2026-01-21 SELL whose planned RR was ~32 because SL was tiny versus a distant TP that actually filled — exceptional magnitude, same liquidity_sweep mechanism. Removing that event makes expectancy negative. OOS positivity is that same outlier. Recent 180d has no such fill and is negative.

## NEXT_RESEARCH_TARGET `EXIT_RESEARCH`

Highest-evidence failure mechanism: most events are theoretical stop-outs, and a large share first moved favorably (MFE>0.5R / >1R) then hit SL. Spread does not explain the -1R. The +31.8R outlier is the complementary geometry (tiny SL, distant TP that actually filled). Next work is causal study of SL/TP interaction on the frozen tape — not threshold search, not broker rediscovery, not live/shadow. Dedup is already understood (event is the unit). Top1-removed expectancy survives=False.

## WHAT_NOT_TO_DO
Optimization, live trading, shadow, broker rediscovery, production strategy/RiskGate/Execution changes.

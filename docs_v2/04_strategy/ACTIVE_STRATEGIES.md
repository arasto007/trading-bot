# Active Strategies

**Status:** VERIFIED  
**Last verified:** 2026-09-01  
**Epistemic-Role:** OWNER of STRATEGY_LIST.  
**Operator-effective state:** UNKNOWN  

## Live selected

| ID | Implementation | Path |
|----|----------------|------|
| `priceaction` | `PriceActionStrategy` + `evaluate_m5_london_sweep` | Default daemon + PA lock |

`ACTIVE_STRATEGIES` (`tradingbot/config/strategies.py`): only `"priceaction": True`.

## Shadow (generated, not selected under lock)

`VOL_REGIME`, `ADAPTIVE_REGIME` — `MultiEngineRouterRegistry.generate_signal`.

## Disabled flags (false)

`advancedml`, `arbitrage`, `breakout`, `dynamicsizing`, `gridtrading`, `hedgingprofessional`, `meanreversion`, `ml`, `momentum`, `patternrecognition`, `pullback`, `rangebound`, `scalping`, `trendfollowing`, `trendmomentumcombo`, `volatilitybreakout`.

If files still exist under `engine/strategies/`, they are **not activated**.

## Present but not looped on default live

`evaluate_m15_intraday`, `evaluate_h4_swing`, `evaluate_m5_scalp` — dispatched only if `GOLD_STRATEGY_MODE` / TF routing selects them. Default M5 preset mode is `london_sweep`. Kernel TFs are `["5m"]`.

## ML engines

`trend_rf_v40`, `trend_rf_v41`, `phase9_9` — **not live** on default path.

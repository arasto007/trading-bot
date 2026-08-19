# Adaptive Regime Live Truth — 7-Day Backtest

**Generated:** 2026-07-30T07:20:55.592730+00:00
**Window:** 7 days | **Initial balance:** $200.0
**Data source:** fallback:XAUUSD_M5_14d.parquet

## Active configuration (from runtime truth)

- Engine: **ADAPTIVE_REGIME**
- ADAPTIVE_CONFLUENCE_ONLY: **True**
- Session: **12-17 UTC**
- Cooldown: **12** bars | Max trades/day: **3**

## Signal funnel (bar scan)

| Metric | Count |
|--------|------:|
| Bars scanned | 1936 |
| **total_signals_generated** | **8** |
| blocked_by_session | 1516 |
| blocked_by_regime | 0 |
| blocked_by_confluence | 412 |
| blocked_by_h1_alignment | 114 |
| blocked_by_ema_sep | 66 |
| blocked_by_riskgate (estimated) | 3 |

## Execution results

| Metric | Value |
|--------|------:|
| executed_trades | 5 |
| profit_factor | 0.0 |
| expectancy | -4.601 |
| net_profit | -23.01 |
| return_pct | -11.5% |
| win_rate_pct | 0.0% |
| average_hold_hours | 0.5 |

## Exit reasons

```json
{
  "sl": 5
}
```

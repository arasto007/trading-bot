# RiskGate Spec

**Status:** VERIFIED (code order)  
**Last verified:** 2026-09-01  
**Epistemic-Role:** OWNER of RISKGATE hop order.  
**Operator-effective state:** UNKNOWN  
**Do not modify RiskGate.** This is documentation only.

Source: `tradingbot/adapters/risk_gate.py::RiskGate.evaluate` then `_live_gates`.

| # | Gate | Function | Reject when | Class | Unknowns |
|---|------|----------|-------------|-------|----------|
| 1 | Entry freeze | `entries_frozen()` | equity unavailable / stale overlay | PRODUCTION | |
| 2 | Capital-adaptive | `_capital_adaptive_gates` | profile/confluence/H1 rules fail | PRODUCTION | tier if equity missing |
| 3 | Max positions | `check_max_positions` | total / per-symbol (loss-streak cap 1) | PRODUCTION | |
| 4 | News | `check_news_gate` | inside blackout if enabled | PRODUCTION | calendar populated? |
| 5 | Friday | `check_friday_gate` | after no-entry hour | PRODUCTION | |
| 6 | Spread | `check_spread_gate` / `_live_spread_pips` | spread > max; **tick None → 999.0** | PRODUCTION | live pips UNKNOWN offline |
| 7 | Opposite | `check_no_opposite_position` | opposite open | PRODUCTION | |
| 8 | HTF | `check_htf_alignment` | required and mismatch; M5 required **false** | PRODUCTION | |
| 9 | Market filters | `check_market_filters` | ATR/regime vs preset | PRODUCTION | |
| 10 | Daily/cooldown | `_tracker.check_entry_allowed` | max trades / cooldown / daily loss | PRODUCTION | |
| 11 | Limits | `risk_logic.can_trade` | limit object | PRODUCTION | |
| 12 | Meta | `apply_pa_meta_decision` | gating and score < threshold; observer never rejects | PRODUCTION/SHADOW | `should_gate()` today |
| 13 | Sizing / micro | `evaluate_micro_feasible_risk` | `MICRO_*`, abnormal stop | PRODUCTION | tick value vs XAUUSD |

VOL signals skip some PA filters after opposite (`_is_vol_regime_signal` early return in `_live_gates`). On default lock, VOL is not **selected**, so this branch is unused for live orders.

Output: `RiskDecision(allowed, reason, ...)`.

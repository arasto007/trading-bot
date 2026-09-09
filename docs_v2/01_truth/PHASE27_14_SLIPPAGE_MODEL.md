# Phase 27.14 — Explicit Modeled Slippage Contract

**Status:** PASS  
**Artifact:** `logs/phase27_14_slippage_model.json`

## Operator decision

**MODELED.** Modeled slippage is permitted only with documented assumptions, parameters and limitations. It is **not** realized slippage.

Current implementation label: **`MODELED_PROXY`**.

## Contract

| Field | Value |
|---|---|
| policy | `MODELED` |
| status | `MODELED_PROXY` |
| model type | `session_hour_variable_proxy` |
| units | `pips_per_leg` |
| direction | Adverse-to-trader on SimulatedBroker: buy fill worse (price + half-spread + slip); sell fill worse (price - half-spread - slip). Same proxy applied per exit leg when modeled. |
| base pips | `0.8` (assumption) |
| session multipliers | `{'ny_overlap_12_17': 1.0, 'london_or_late_ny_8_12_or_17_21': 1.25, 'asian_0_7': 1.6, 'other': 1.4}` (assumption) |
| source / evidence basis | Configured research proxy. Operator deal tape does not provide a sufficient requested_price vs actual_fill_price history. |
| provenance | `tradingbot/backtest/config.py + tradingbot/domain/session_logic.py + Phase 27.14 contract` |
| realized sample count | `0` |
| statistically sufficient realized | **False** |
| MT5 deviation | `20` points — **not** realized slippage |

### Assumptions

- base_slippage_pips=0.8 is the existing BacktestConfig default, not a fill-derived estimate
- session_cost_multiplier(hour) from tradingbot.domain.session_logic is an inherited session-cost assumption, not a slippage fit
- statistically sufficient realized distribution requires >= 10 requested-vs-fill pairs (inherited Phase 27.5/27.7 language)
- entry_price is not requested_price and must not be used to invent a requested-vs-fill pair

### Limitations

- Not a historical execution distribution
- Not account-specific realized slippage
- MT5 deviation is a request tolerance, not slippage
- A configured parameter cannot close the cost-completeness gate
- Sparse or missing requested-vs-fill pairs remain UNKNOWN for REALIZED class

## Operator deal tape (not inflated)

| Source | requested_price | actual_fill | class |
|---|---|---|---|
| Demo | `False` | `False` | `UNKNOWN` |
| Real | `False` | `True` | `UNKNOWN` |

`entry_price` was **not** treated as `requested_price`. Real `actual_fill_price` without a requested price remains UNKNOWN.

## Semantics

| Claim | Result |
|---|---|
| MODELED ≠ REALIZED | **True** |
| MODELED_PROXY ≠ REALIZED | **True** |
| MT5 deviation ≠ realized slippage | **True** |
| Modeled parameter silently becomes zero | **False** (non-positive → UNKNOWN) |
| Cost completeness COMPLETE from modeled slippage alone | **False** (`PARTIAL`) |
| Cost-adjusted validation | **BLOCKED** |

`BacktestConfig.slippage_status=MODELED_PROXY` remains the research default. Simulation may apply the documented proxy. The COMPLETE cost gate stays closed because a proxy is not historical execution evidence.

## Production

**BLOCKED.** No RiskGate, strategy, or live execution semantic changes. No MT5. No fabricated realized slippage.

## Next

STOP after Phase 27.14.

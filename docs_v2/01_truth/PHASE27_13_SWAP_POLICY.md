# Phase 27.13 — Broker-Rate-Only Swap Policy

**Status:** PASS  
**Artifact:** `logs/phase27_13_swap_policy.json`

## Operator decision

**BROKER_RATE_ONLY.** Broker-provided swap rates may be retained as evidence. Historical swap behavior must **not** be fabricated from current rates.

## Observed XAUUSD_i broker-rate snapshot

| Field | Value | Class |
|---|---|---|
| swap_long | `-89.136` | BROKER_RATE_ONLY |
| swap_short | `3.45` | BROKER_RATE_ONLY |
| swap_rollover3days (Demo) | `None` | field absent on Demo snapshot |
| swap_rollover3days (Real) | `3` | present on Real spec |
| triple-swap weekday | `Wednesday` | Wednesday only when `swap_rollover3days=3` is evidenced |
| historical_swap_series | **UNKNOWN** | not synthesized |

Source: `logs/operator_broker_evidence_demo_raw.json` (STALE operator snapshot). Matches stated long `True` / short `True`.

The Demo closed deal shows realized swap `0.0` on a one-second hold. That does **not** prove a verified zero-swap policy.

## Semantics

| Claim | Result |
|---|---|
| BROKER_RATE_ONLY ≠ historical series | **True** |
| Realized zero ≠ verified zero | **True** |
| Historical series synthesized from current rates | **Forbidden** |
| Cost completeness COMPLETE from broker rates alone | **False** (`PARTIAL`) |
| Cost-adjusted validation | **BLOCKED** |

`BacktestConfig.swap_status=BROKER_RATE_ONLY` is now an explicit cost-model mode. Its value is **not** used as a daily accrual. Default `swap_status` remains `UNKNOWN` (fail-closed). SimulatedBroker still does not apply swap PnL.

## Production

**BLOCKED.** No RiskGate, execution, or strategy changes. No MT5. No invented rollover calendar.

## Next

STOP after Phase 27.13.

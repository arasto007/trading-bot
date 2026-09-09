# Phase 35 — Broker Cost, Execution & Live-Fill Reality

**Status:** PASS
**Class:** RESEARCH ONLY
**Live orders:** NO
**Parameters optimized:** NO
**FINAL_GATE:** `BLOCKED`
**Cost completeness:** `INCOMPLETE`

STOP AFTER PHASE 35. DO NOT START PHASE 36.

Offline synthesis of Phase 27 evidence. MODELED was **not** converted to VERIFIED.

---

## Evidence grades

Allowed: VERIFIED / OBSERVED / PROXY / MODELED / UNKNOWN.

| Component | Grade | AND status |
|---|---|---|
| symbol_binding | UNKNOWN | BLOCKED |
| economics | UNKNOWN | UNKNOWN |
| dataset_provenance | PROXY | PARTIAL |
| spread | PROXY | BLOCKED |
| commission | UNKNOWN | BLOCKED |
| swap | UNKNOWN | UNKNOWN |
| slippage | MODELED | UNKNOWN |
| execution_model | UNKNOWN | UNKNOWN |

## Spread

Production parquet: **PROXY** (OHLC only).  
Sidecar 27.26 tape: **OBSERVED** for that ~15-day window only — not a production DATASET.

Overall (price / pips): `{'price': {'n': 2952, 'median': 0.4099999999998545, 'p75': 0.42000000000007276, 'p90': 0.42000000000007276, 'p95': 0.5599999999994907, 'p99': 0.5799999999999272}, 'pips': {'n': 2952, 'median': 4.099999999998545, 'p75': 4.200000000000728, 'p90': 4.200000000000728, 'p95': 5.599999999994907, 'p99': 5.799999999999272}}`  
NY 15–16 UTC: `{'price': {'n': 132, 'median': 0.38000000000010914, 'p75': 0.4000000000005457, 'p90': 0.42000000000007276, 'p95': 0.42000000000007276, 'p99': 0.42000000000007276}, 'pips': {'n': 132, 'median': 3.8000000000010914, 'p75': 4.000000000005457, 'p90': 4.200000000000728, 'p95': 4.200000000000728, 'p99': 4.200000000000728}}`  
NY-open hour 15 UTC: `{'price': {'n': 132, 'median': 0.38000000000010914, 'p75': 0.4000000000005457, 'p90': 0.42000000000007276, 'p95': 0.42000000000007276, 'p99': 0.42000000000007276}, 'pips': {'n': 132, 'median': 3.8000000000010914, 'p75': 4.000000000005457, 'p90': 4.200000000000728, 'p95': 4.200000000000728, 'p99': 4.200000000000728}}`

## Commission

No account-applicable VERIFIED_SCHEDULE. Public pages GENERIC_SUPPORTING with applicability uncertainty. All-zero short tape is OBSERVED_ZERO_NOT_PROVEN — not zero commission.

## Swap

Current broker rates may be OBSERVED. Historical series UNKNOWN. Short-hold zeros do not prove historical zero swap.

## Slippage

Genuine requested-vs-fill pairs: `0`.  
MT5 deviation is **not** realized slippage. Grade remains MODELED / UNKNOWN.

## Execution

Requested volume/price not identifiable. Partials / rejections / requotes / latency not proven. Order↔deal linkage incomplete. SimulatedBroker is not realized. Missing pairs were not fabricated.

## Economics contract

minimum lot / volume step / contract size / tick value / tick size / volume constraints: **UNKNOWN** as current broker evidence.

## FINAL COST COMPLETENESS

AND-gate `0/8` COMPLETE.  
Classification: **INCOMPLETE**.  
Theoretical edge surviving broker economics: **NOT_PROVEN**. Cost-adjusted metrics remain forbidden.

## Safety

No live orders, no MT5 attach, no `.env`, no parquet rewrite. Phase 36 was **not** started.

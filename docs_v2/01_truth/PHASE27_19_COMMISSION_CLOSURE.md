# Phase 27.19 — Account-Applicable Commission Schedule Closure

**Status:** FAIL  
**Commission status:** `UNKNOWN / BLOCKED`  
**Artifact:** `logs/phase27_19_commission_closure.json`

## Operator decision

**VERIFIED_SCHEDULE.** Commission may only be accepted for validation when a verified, account-applicable schedule is obtained. Selecting the policy is a **gate**, not current verification.

Observed commission = 0 does **not** prove zero commission. The existing 50 gold deals remain **`OBSERVED_ZERO_NOT_PROVEN`**.

## Prior evidence inspected

| Source | Result |
|---|---|
| Phase 27.12 | `OBSERVED_ZERO_NOT_PROVEN`; verified found `False` |
| Phase 27.17 Real | attach `REAL_COLLECTED`; broker `LiteFinance Global LLC`; server `LiteFinance-MT5-Live`; environment `REAL`; verified claimed `False` |

## Applicability matrix

| Field | Evidenced value | Defensible for VERIFIED? |
|---|---|---|
| broker | `LiteFinance Global LLC` | `True` (context only) |
| server | `LiteFinance-MT5-Live` | `True` (context only) |
| account environment | `REAL` | `True` (environment, not product) |
| account / product type | `UNKNOWN` | **False — required, missing** |
| asset class | `gold` | supporting only |
| symbol | `XAUUSD_i` | supporting only |
| commission basis | `UNKNOWN` | **False — required, missing** |
| per-side vs round-turn | `UNKNOWN` | **False — required, missing** |
| currency | `USD` | account currency, not proven commission currency |
| effective date / version | `UNKNOWN` | **False — required, missing** |

Missing for VERIFIED: `basis, effective_date_or_version, applicability_established, account_product_type`.

## Public documentation (supporting only)

Official LiteFinance ECN page lists precious-metals commission **$5 per lot** on MT5, charged at open. The public markups PDF distinguishes ECN commission vs CLASSIC/CENT markup and states conditions in force from 2026-03-26.

These pages were **not** treated as this account's schedule. A broker-name match is not account-specific verification. Account product type remains **UNKNOWN**, so neither the public ECN $5 grid nor a Classic/Cent “no commission / markup in spread” reading can be applied.

## Observed gold deals

| Field | Value |
|---|---|
| unique gold deals | `2` |
| commission samples | `2` |
| observed zero | `2` |
| observed nonzero | `0` |
| classification | **`OBSERVED_ZERO_NOT_PROVEN`** |
| proves verified schedule | **False** |
| proves universal zero | **False** |

2 gold deal(s) show commission=0.0. Observed zero is not a verified schedule and does not prove universal zero.

`BacktestConfig.commission_per_lot=0.0` was **not** converted to `CostAvailability.ZERO`.

## Verified schedule

| Field | Value |
|---|---|
| found | **False** |
| accepted | **False** |
| status | **`UNKNOWN / BLOCKED`** |
| provenance | none |
| applicability established | **False** |
| public docs used as verified | **False** |

## Semantics

| Claim | Result |
|---|---|
| Observed zero ≠ verified schedule | **True** |
| Generic public schedule ≠ account-specific schedule | **True** |
| Broker-name match ≠ verification | **True** |
| Missing applicability ≠ VERIFIED | **True** |
| Complete applicability can be accepted | **True** (fixture only; not this account) |
| UNKNOWN / OBSERVED_ZERO / policy-gate-only block COMPLETE | **True** (`PARTIAL` / `PARTIAL` / `PARTIAL`) |
| Cost-adjusted validation | **BLOCKED** |
| FINAL_GATE | `BLOCKED` |

Default `BacktestConfig.commission_status` remains `UNKNOWN` (fail-closed).

## Production

**BLOCKED.** No Strategy, RiskGate, or execution changes. No MT5. No fabricated commission. Phase 27.20+ not started.

## Next

STOP after Phase 27.19.

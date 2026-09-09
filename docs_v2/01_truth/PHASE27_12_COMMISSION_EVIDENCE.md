# Phase 27.12 — Verified Commission Schedule Evidence

**Status:** PASS  
**Artifact:** `logs/phase27_12_commission_evidence.json`

## Operator decision

**VERIFIED_SCHEDULE.** Commission may only be accepted for validation when a verified, account-applicable schedule is obtained. Selecting the policy is a **gate**, not current verification.

## Context (operator evidence, not a schedule)

| Field | Value | Defensible as schedule applicability? |
|---|---|---|
| broker | `LiteFinance` | supporting context only |
| Demo server | `LiteFinance-MT5-Demo` | supporting context only |
| Real server | `LiteFinance-MT5-Live` | supporting context only |
| account type | Demo `DEMO` / Real `REAL` | environment label, not commission product |
| account product / commission tier | **UNKNOWN** | required, missing |
| asset class | `gold` | supporting context only |
| symbol | `XAUUSD_i` | supporting context only |
| account currency | Demo `USD` / Real `USD` | not proven commission currency |
| commission currency | **UNKNOWN** | required, missing |
| basis (per-lot / per-side / round-turn) | **UNKNOWN** | required, missing |
| effective date / version | **UNKNOWN** | required, missing |

EV-D-16 (Demo commission spec) and EV-R-16 (Real commission spec) remain **NOT COLLECTED**.

Public broker documentation was **not** treated as an account-specific verified schedule.

## Observed gold deals

| Field | Value |
|---|---|
| unique gold deals | `50` |
| commission samples | `50` |
| observed zero | `50` |
| observed nonzero | `0` |
| classification | **`OBSERVED_ZERO_NOT_PROVEN`** |
| proves verified schedule | **False** |
| proves universal zero | **False** |

50 gold deal(s) show commission=0.0. Observed zero is not a verified schedule and does not prove universal zero.

## Verified schedule

| Field | Value |
|---|---|
| found | **False** |
| status | **`BLOCKED`** |
| provenance | none |
| applicability established | **False** |
| public docs used as verified | **False** |
| rate | none |

## Semantics

| Claim | Result |
|---|---|
| Observed zero ≠ verified schedule | **True** |
| Generic public schedule ≠ account-specific schedule | **True** |
| Verified schedule requires applicability | **True** |
| UNKNOWN commission blocks COMPLETE | **True** (`PARTIAL`) |
| OBSERVED_ZERO_NOT_PROVEN blocks COMPLETE | **True** (`PARTIAL`) |
| VERIFIED_SCHEDULE gate without schedule blocks COMPLETE | **True** (`PARTIAL`) |
| Zero commission assumed from observed zeros | **False** |
| Cost-adjusted validation | **BLOCKED** |

`BacktestConfig.commission_status` default remains `UNKNOWN` (fail-closed). SimulatedBroker still refuses entry when commission is not explicit ZERO or MODELED.

## Production

**BLOCKED.** No RiskGate, strategy, or live execution semantic changes. No MT5. No fabricated commission. No zero-commission assumption.

## Next

STOP after Phase 27.12.

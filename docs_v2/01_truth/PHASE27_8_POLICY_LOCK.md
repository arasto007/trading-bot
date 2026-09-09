# Phase 27.8 — Operator Policy Lock & Evidence Alignment

**Status:** LOCKED  
**Artifact:** `logs/phase27_8_policy_lock.json`  
**Policy document:** `docs_v2/01_truth/OPERATOR_BROKER_POLICY_DECISION.md`

## Objective

Convert the operator's six selected broker-policy decisions into a formally locked, internally consistent policy document. Do **not** convert missing evidence into verified evidence.

## Epistemic rule

**POLICY ≠ EVIDENCE.** If repository evidence conflicts with the selected policy, preserve the operator policy and record the evidence gap. Never silently reconcile it.

## Locked policy decisions

| # | Topic | POLICY (operator) | EVIDENCE (repository) |
|---|---|---|---|
| 1 | Canonical gold symbol | `XAUUSD_i` | Demo/stale Real show XAUUSD_i present, XAUUSD absent. EV-EQ-01 **NOT_PROVEN** |
| 2 | Logical XAUUSD datasets | `ONLY_WITH_EXPLICIT_DATASET_MAP` | Silent bind forbidden. Explicit map required; maps not populated |
| 3 | Commission | `VERIFIED_SCHEDULE` | Status UNKNOWN. Verified schedule = False. Gate ≠ proof |
| 4 | Swap | `BROKER_RATE_ONLY` | historical_swap_series = UNKNOWN. Series must not be invented |
| 5 | Slippage | `MODELED` | Status UNKNOWN; realized samples = 0. MODELED ≠ realized |
| 6 | Validation gate | `COMPLETE_COSTS_REQUIRED` | Cost completeness UNKNOWN; complete datasets = 0 |

## Decision semantics

1. **XAUUSD_i** is the canonical gold symbol. It does **not** claim `XAUUSD` ≡ `XAUUSD_i`. EV-EQ-01 remains NOT_PROVEN.
2. **ONLY_WITH_EXPLICIT_DATASET_MAP** forbids silent automatic treatment of logical XAUUSD datasets as XAUUSD_i.
3. **VERIFIED_SCHEDULE** means commission may only be accepted for validation when a verified, account-applicable schedule is obtained. It does **not** mean a schedule has been verified.
4. **BROKER_RATE_ONLY** allows recorded broker swap rates where explicitly supported. Historical swap series must not be invented.
5. **MODELED** permits modeled slippage only with documented assumptions, parameters and limitations. It must never be represented as realized slippage.
6. **COMPLETE_COSTS_REQUIRED** blocks cost-adjusted validation unless the complete required cost contract is satisfied.

## AWAITING OPERATOR

Removed. The six decisions are locked. Remaining work is evidence closure, not policy selection.

## Evidence still missing

- EV-EQ-01 (XAUUSD ↔ XAUUSD_i equivalence) NOT_PROVEN
- Account-specific verified commission schedule
- Historical swap series (must not be invented)
- Historical M5 bid/ask tape
- Realized historical slippage distribution
- Cost completeness COMPLETE (0 datasets)
- Fresh Real MT5 operator evidence
- Explicit dataset_symbol_map entries for logical XAUUSD datasets

## Blockers remaining

| Blocker | Status | Class | Note |
|---|---|---|---|
| EV-EQ-01 | NOT_PROVEN | EVIDENCE | Decision 1 does not close equivalence |
| Explicit dataset_symbol_map for logical XAUUSD datasets | REQUIRED_NOT_POPULATED | EVIDENCE | Decision 2 locks the rule; it does not populate maps |
| Account-applicable verified commission schedule | MISSING | EVIDENCE | Decision 3 VERIFIED_SCHEDULE is a gate, not current verification |
| Historical swap series | UNKNOWN | EVIDENCE | Decision 4 forbids inventing a series |
| Realized historical slippage | INSUFFICIENT | EVIDENCE | Decision 5 MODELED is not realized slippage |
| Historical M5 bid/ask tape | MISSING | EVIDENCE | Required for DATASET spread completeness |
| Cost completeness COMPLETE | NOT_COMPLETE | EVIDENCE | Decision 6 blocks cost-adjusted validation |
| Fresh Real MT5 evidence | MISSING | EVIDENCE | Stale Real observations are not fresh Real evidence |
| Production readiness | BLOCKED | GATE | Policy lock does not authorize production |
| Operator policy pack (six decisions) | LOCKED | POLICY | No longer AWAITING OPERATOR |
| Canonical symbol policy selection | LOCKED | POLICY | XAUUSD_i selected; equivalence still NOT_PROVEN |

## Production

**BLOCKED** — `production_changes: NONE`. Policy lock does not enable trading, start MT5, place orders, alter `.env`, or modify Strategy / RiskGate / execution / sizing / RR / ML.

## Next

STOP after Phase 27.8. Do not begin Phase 27.9+.

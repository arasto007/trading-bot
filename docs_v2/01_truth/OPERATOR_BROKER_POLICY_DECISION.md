# Operator Broker Policy Decision

**Status:** LOCKED — Phase 27.8 operator policy lock
**Locked:** 2026-09-06
**Epistemic rule:** POLICY ≠ EVIDENCE. A selected treatment is an acceptance rule, not proof of the corresponding broker fact.

---

## Epistemic distinction

| Layer | Meaning |
|---|---|
| **POLICY** | What the operator decided must be used as the acceptance / validation rule |
| **EVIDENCE** | What the repository has actually proven |

Missing evidence is recorded as a gap. It is never converted into verified evidence because a policy option was selected.

Unchecked **UNDECIDED** options are retained as the rejected alternatives. They are not the selected state.

---

## DECISION 1: Canonical gold symbol

- [ ] XAUUSD
- [x] XAUUSD_i
- [ ] **UNDECIDED**

**POLICY:** Canonical gold symbol is `XAUUSD_i`.

**DOES NOT MEAN:** `XAUUSD` and `XAUUSD_i` are economically equivalent.

**EVIDENCE:** Observed Demo terminal contains `XAUUSD_i` and does not contain `XAUUSD`. Stale Real evidence also showed `XAUUSD_i` and no `XAUUSD`. Absence on observed terminals is not broker-wide proof.

**EV-EQ-01:** **NOT_PROVEN**. Remains NOT_PROVEN until evidence closes it.

---

## DECISION 2: May logical XAUUSD datasets be treated as XAUUSD_i?

- [ ] YES
- [ ] NO
- [x] ONLY_WITH_EXPLICIT_DATASET_MAP
- [ ] **UNDECIDED**

**POLICY:** Logical `XAUUSD` datasets may be bound to `XAUUSD_i` only through an explicit `dataset_symbol_map`.

**FORBIDDEN:** Silent automatic treatment of `XAUUSD` datasets as `XAUUSD_i`. Without an explicit map, `resolve_broker_symbol_for_dataset` must fail closed (`SYMBOL_MISMATCH`).

**EVIDENCE:** Many parquet datasets remain labeled `XAUUSD`. No automatic equivalence is authorized. An empty `dataset_symbol_map` does not create a relationship.

---

## DECISION 3: Commission treatment

- [x] VERIFIED_SCHEDULE
- [ ] OBSERVED_ZERO_NOT_PROVEN
- [ ] CONSERVATIVE_MODEL
- [ ] **UNDECIDED**

**POLICY:** `VERIFIED_SCHEDULE` means commission may only be accepted for validation when a verified, account-applicable schedule is obtained.

**DOES NOT MEAN:** A verified commission schedule currently exists. Selecting `VERIFIED_SCHEDULE` is a gate, not a verification.

**EVIDENCE:** No account-specific verified commission schedule has been established. Observed zero-commission deals do not prove universal zero.

**IMPLEMENTATION (Phase 27.12):** Gate implemented. No account-applicable schedule obtained. 50 gold deals at 0.0 classified `OBSERVED_ZERO_NOT_PROVEN`. Default `commission_status` remains UNKNOWN. Cost completeness remains fail-closed. See `docs_v2/01_truth/PHASE27_12_COMMISSION_EVIDENCE.md`.

---

## DECISION 4: Swap treatment

- [ ] HISTORICAL
- [x] BROKER_RATE_ONLY
- [ ] CONSERVATIVE_MODEL
- [ ] **UNDECIDED**

**POLICY:** `BROKER_RATE_ONLY` means broker swap rates may be recorded and used where explicitly supported, but historical swap series must not be invented.

**EVIDENCE:** Broker swap rates may appear on symbol spec snapshots. Historical swap series remains UNKNOWN. Short-hold zero swap does not prove a zero historical series.

---

## DECISION 5: Slippage treatment

- [ ] REALIZED
- [x] MODELED
- [ ] UNKNOWN
- [ ] **UNDECIDED**

**POLICY:** `MODELED` means modeled slippage is permitted only when its assumptions, parameters and limitations are explicitly documented. It must never be represented as realized slippage.

**EVIDENCE:** Slippage evidence is insufficient for realized historical slippage. MT5 deviation is not realized slippage.

---

## DECISION 6: Validation gate

- [x] COMPLETE_COSTS_REQUIRED
- [ ] CONSERVATIVE_COST_SCENARIO_ALLOWED
- [ ] **UNDECIDED**

**POLICY:** `COMPLETE_COSTS_REQUIRED` means cost-adjusted validation is blocked unless the complete required cost contract is satisfied.

**EVIDENCE:** Cost completeness is not complete. Cost-adjusted metrics remain disabled. Production readiness remains **BLOCKED**.

**IMPLEMENTATION (Phase 27.16):** FINAL_GATE = BLOCKED. Not strategy approval, profitability approval, or real-money authorization. See `docs_v2/01_truth/PHASE27_16_FINAL_VALIDATION_GATE.md`.

---

**Configured code defaults (NOT policy):** `PRIMARY_SYMBOL=XAUUSD_i`, `SYMBOL_BY_ENVIRONMENT` → XAUUSD_i for Demo and Real. Code default alignment with Decision 1 is CONFIGURED, not evidence that EV-EQ-01 is proven.

**Phase 27.8 artifact:** `logs/phase27_8_policy_lock.json`  
**Phase 27.8 document:** `docs_v2/01_truth/PHASE27_8_POLICY_LOCK.md`  
**Phase 27.12 commission evidence:** `logs/phase27_12_commission_evidence.json`  
**Phase 27.16 final validation gate:** `logs/phase27_16_FINAL_VALIDATION_GATE.json`

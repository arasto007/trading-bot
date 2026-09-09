# Demo / Real Symbol and Cost Design

**Status:** Phase 27 evidence baseline + Phase 27.8 operator policy lock  
**Scope:** LiteFinance MT5 Demo/Real symbol economics — design constraints. Operator policy is locked in `OPERATOR_BROKER_POLICY_DECISION.md`. POLICY ≠ EVIDENCE.

---

## Configured symbol map (code)

| Environment | Configured broker symbol | Class |
|---|---|---|
| DEMO | `XAUUSD_i` | CONFIGURED (`SYMBOL_BY_ENVIRONMENT`) |
| REAL | `XAUUSD_i` | CONFIGURED (default; `TRADINGBOT_REAL_SYMBOL` override UNKNOWN) |

`PRIMARY_SYMBOL = XAUUSD_i` — production kernel default.

**Strict resolution:** `SYMBOL_RESOLUTION_STRICT=True` — no silent ±`_i` hunt.

---

## Observed broker reality (STALE operator evidence 2026-09-02)

| Terminal | XAUUSD | XAUUSD_i |
|---|---|---|
| LiteFinance-MT5-Demo | absent | present |
| LiteFinance-MT5-Live | absent | present |

Fresh collection: Phase 27 operator command (`run_phase27_operator_evidence_collection`) — bounded attach-only.

---

## Dataset symbol binding

| Dataset label | Broker economics | Mapping required |
|---|---|---|
| `XAUUSD_i` | OBSERVED_BROKER_EVIDENCE (sidecar when deployed) | match |
| `XAUUSD` | none attached | explicit `dataset_symbol_map` only — **EV-EQ-01 NOT_PROVEN**; Phase 27.8 Decision 2 = `ONLY_WITH_EXPLICIT_DATASET_MAP` |

Fail-closed: `dataset_contract.resolve_broker_symbol_for_dataset` raises `SYMBOL_MISMATCH` without explicit map. An empty map is not a relationship. Silent `XAUUSD`→`XAUUSD_i` treatment is forbidden. Phase 27.20: 30 logical `XAUUSD` datasets remain BLOCKED (`INSUFFICIENT_PROVENANCE`); filename is not a map; 0 entries inserted.

Phase 28.0–36 performance research uses only defensible `XAUUSD_i` datasets (canonical M5 entry + H4 context if present). Logical `XAUUSD` tapes remain BLOCKED. Phase 28.3/30/33 cost shocks are MODELED / MODELED_PROXY and are **not** historical realized costs. Phase 35 does **not** convert MODELED into VERIFIED and does **not** place live orders. Phase 29 does **not** silently merge logical `XAUUSD` into `XAUUSD_i` and does **not** overwrite the Phase 28 M5 snapshot. That research does **not** authorize live trading or cost-adjusted validation.

---

## Cost stack by environment

| Component | Demo | Real | Backtest default |
|---|---|---|---|
| Spread | STALE tick snapshot | FRESH Real attach 2026-09-06 (`XAUUSD_i` bid/ask snapshot; not historical M5 tape). Phase 27.18: DATASET only from genuine historical Bid/Ask; live tick / PROXY / OHLC never converted | PROXY (OHLC) or DATASET (historical bid/ask only) |
| Commission | OBSERVED_ZERO_NOT_PROVEN | OBSERVED_ZERO_NOT_PROVEN | UNKNOWN default (fail-closed entry). Policy Decision 3 = `VERIFIED_SCHEDULE` (gate). Phase 27.19: 50 gold zeros remain OBSERVED_ZERO_NOT_PROVEN; public ECN/Classic pages supporting only; account/product type UNKNOWN; COMPLETE blocked |
| Swap | BROKER_RATE_ONLY | BROKER_RATE_ONLY | UNKNOWN default. Decision 4 implemented (Phase 27.13): rates may be recorded; historical series remains UNKNOWN; broker rates cannot make cost COMPLETE |
| Slippage | UNKNOWN / NOT_IDENTIFIABLE | UNKNOWN / NOT_IDENTIFIABLE | MODELED_PROXY default. Decision 5 implemented (Phase 27.14/27.30): documented session-hour proxy; 0 genuine requested-vs-fill pairs; price_open ≠ requested; MODELED ≠ realized; proxy cannot make cost COMPLETE |

**Cost-adjusted metrics:** BLOCKED until `CostCompleteness.COMPLETE`. Policy Decision 6 = `COMPLETE_COSTS_REQUIRED`.

---

## Design states

STATE A remains an evidence state. STATE B is now operator POLICY (Phase 27.8) without converting EV-EQ-01 into proven equivalence.

### STATE A — XAUUSD equivalence PROVEN
Requires both symbols on same terminal with critical field MATCH. **Not met.** EV-EQ-01 remains **NOT_PROVEN**.

### STATE B — XAUUSD_i-only acceptable without equivalence
**POLICY AUTHORIZED (Phase 27.8 Decision 1):** canonical gold symbol is `XAUUSD_i`. This does **not** prove `XAUUSD` ≡ `XAUUSD_i`. Logical `XAUUSD` datasets still require an explicit `dataset_symbol_map` (Decision 2). Evidence gaps are unchanged.

---

## Safety rules (Phase 27)

- Do not invent XAUUSD economics when absent
- Do not treat observed zero-commission deals (including 50 gold deals at 0.0) as a verified schedule or universal zero
- Do not treat MT5 deviation as realized slippage
- Do not modify historical datasets to appear complete

**Artifact:** `logs/phase27_broker_reality_audit.json`  
**Phase 27.5 gate:** `logs/phase27_5_final_broker_cost_gate.json`  
**Phase 27.6 gate:** `logs/phase27_6_final_evidence_gate.json`  
**Phase 27.7 closure:** `logs/phase27_7_final_blocker_closure.json`  
**Phase 27.8 policy lock:** `logs/phase27_8_policy_lock.json`  
**Phase 27.10 dataset binding:** `logs/phase27_10_dataset_symbol_binding.json` — no silent `XAUUSD`→`XAUUSD_i`; missing/invalid maps BLOCKED  
**Phase 27.13 swap policy:** `logs/phase27_13_swap_policy.json` — BROKER_RATE_ONLY implemented; historical swap UNKNOWN; cost-adjusted BLOCKED  
**Phase 27.14 slippage model:** `logs/phase27_14_slippage_model.json` — MODELED implemented as MODELED_PROXY; realized UNKNOWN; cost-adjusted BLOCKED  
**Phase 27.12 commission evidence:** `logs/phase27_12_commission_evidence.json` — VERIFIED_SCHEDULE gate; 50 gold zeros = OBSERVED_ZERO_NOT_PROVEN; schedule UNKNOWN/BLOCKED  
**Phase 27.19 commission closure:** `logs/phase27_19_commission_closure.json` — public LiteFinance schedule is supporting only; broker-name match ≠ account verification; commission remains UNKNOWN/BLOCKED  
**Phase 27.20 dataset mapping:** `logs/phase27_20_dataset_mapping_closure.json` — 30 logical XAUUSD BLOCKED; 0 maps inserted; filename ≠ map  
**Phase 27.21 evidence synthesis:** `logs/phase27_21_evidence_synthesis.json` — read-only matrix; 27.18 existence ≠ dataset coverage; FINAL_GATE remains BLOCKED  
**Phase 27.22 commission forensic:** `logs/phase27_22_commission_forensic.json` — account_product_type UNKNOWN; 50 zeros remain OBSERVED_ZERO_NOT_PROVEN; not VERIFIED_SCHEDULE  
**Phase 27.23 bid/ask expansion:** `logs/phase27_23_bidask_expansion.json` — logs-only expansion of 27.18; production `XAUUSD_i_5m` remains PROXY; C full-dataset coverage BLOCKED  
**Phase 27.24 execution/cost forensics:** `logs/phase27_24_execution_cost_forensics.json` — swap BROKER_RATE_ONLY; realized slippage only from genuine requested/fill; SimulatedBroker ≠ execution evidence  
**Phase 27.25 canonical bid/ask coverage:** `logs/phase27_25_canonical_bidask_coverage.json` — targeted dataset-range Bid/Ask only; production parquet unchanged  
**Phase 27.26 complete canonical bid/ask:** `logs/phase27_26_canonical_bidask_coverage.json` — merge + missing-interval collection; 27.25 tape preserved; production parquet unchanged  
**Phase 27.27 dataset symbol binding:** `logs/phase27_27_dataset_symbol_binding.json` — recomputed inventory; no silent map; EV-EQ-01 NOT_PROVEN  
**Phase 27.28 commission evidence:** `logs/phase27_28_commission_evidence.json` — observed zeros remain OBSERVED_ZERO_NOT_PROVEN; no account-applicable schedule  
**Phase 27.29 swap evidence:** `logs/phase27_29_swap_evidence.json` — BROKER_RATE_ONLY current snapshot; historical series UNKNOWN  
**Phase 27.30 slippage evidence:** `logs/phase27_30_slippage_evidence.json` — 0 genuine requested-vs-fill pairs; MODELED_PROXY remains implementation  
**Phase 27.31 execution evidence:** `logs/phase27_31_execution_evidence.json` — deal fill tape only; order lifecycle UNKNOWN; SimulatedBroker ≠ realized  
**Phase 27.32 final cost evidence gate:** `logs/phase27_32_final_cost_evidence_gate.json` — integrated audit; no grade upgrades; FINAL_GATE remains BLOCKED  
**Phase 27.33 EV-EQ resolution:** `logs/phase27_33_ev_eq_resolution.json` — NOT_PROVEN; State B is policy only; 0 maps inserted  

**Phase 27.16 final validation gate:** `logs/phase27_16_FINAL_VALIDATION_GATE.json` — **FINAL_GATE=BLOCKED** (not strategy/profitability/real-money approval)  
**Phase 27.17 Real evidence:** `logs/phase27_17_real_broker_evidence.json` — fresh Real attach only; Demo never overwrites stale Real; EV-EQ-01 not inferred  
**Phase 27.18 historical bid/ask:** `logs/phase27_18_historical_bidask.json` — PROXY / OHLC / live tick ≠ historical Bid/Ask; production datasets not rewritten

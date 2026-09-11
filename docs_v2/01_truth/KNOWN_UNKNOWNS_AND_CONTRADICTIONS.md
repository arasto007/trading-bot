# Known Unknowns and Contradictions

**Status:** Phase 27 baseline  
**Last verified:** 2026-09-09  
**Epistemic-Role:** OWNER of UNKNOWNS_CONTRADICTIONS. Explicit registry of unresolved contradictions — never silently reconciled.  
**Epistemic role:** Explicit registry of unresolved contradictions — never silently reconciled.

Classification: **PROVEN** / **CONFIGURED** / **SUPPORTED** / **UNKNOWN** / **DEFERRED** / **BLOCKED** / **SUPERSEDED**

---

## EV-EQ-01 (XAUUSD ↔ XAUUSD_i)

| Claim | Status |
|---|---|
| XAUUSD economically equivalent to XAUUSD_i | **BLOCKED** — NOT_PROVEN (Phase 27.33 state `B_POLICY_AUTHORIZED_XAUUSD_i_ONLY`; absence ≠ DISPROVEN; policy ≠ equivalence) |
| XAUUSD absent on observed Demo/Real LiteFinance terminals | **PROVEN** (fresh Real 2026-09-06: existence=NO; not broker-wide) |
| XAUUSD_i present on observed terminals | **PROVEN** (fresh Real 2026-09-06: existence=YES) |
| Absence on one terminal proves broker-wide absence | **UNKNOWN** — not inferable |

**Contradiction:** Code default `PRIMARY_SYMBOL=XAUUSD_i` vs many parquet datasets labeled `XAUUSD`.  
**Operator policy (Phase 27.8, LOCKED):** Decision 1 = `XAUUSD_i` (canonical symbol POLICY). Decision 2 = `ONLY_WITH_EXPLICIT_DATASET_MAP`. This does **not** prove EV-EQ-01.  
**Resolution:** Fail-closed — explicit `dataset_symbol_map` required; silent `XAUUSD`→`XAUUSD_i` treatment forbidden; equivalence not assumed (Phase 25E/27/27.8/27.10/27.20/27.27). Phase 27.27: 30 logical XAUUSD `MISSING_EXPLICIT_MAP`; 2 `DIRECT_CANONICAL_MATCH`; 0 `EXPLICIT_MAPPED`; 0 maps inserted; EV-EQ-01 remains NOT_PROVEN.

---

## Cost evidence

| Component | Status |
|---|---|
| Commission universal zero | **UNKNOWN / BLOCKED**. Policy Decision 3 = `VERIFIED_SCHEDULE` (gate). Phase 27.28 grade `OBSERVED_ZERO_NOT_PROVEN` / `OBSERVED_ZERO_NOT_PROVEN`; account_product_type UNKNOWN; public pages GENERIC_SUPPORTING only; observed zero ≠ verified schedule |
| Swap historical realized | **UNKNOWN**. Policy Decision 4 = `BROKER_RATE_ONLY`. Phase 27.29 grade `CURRENT_BROKER_RATE_ONLY`; current rates ≠ historical series; realized zero ≠ historical zero |
| Slippage realized distribution | **UNKNOWN / NOT_IDENTIFIABLE**. Decision 5 = `MODELED` / `MODELED_PROXY`. Phase 27.30 grade `REALIZED_UNKNOWN_NOT_IDENTIFIABLE`; genuine pairs `0`; price_open ≠ requested; MODELED_PROXY ≠ REALIZED |
| Spread on OHLC datasets | **CONFIGURED** PROXY — not observed. Phase 27.26 `PARTIAL_CANONICAL_COVERAGE` 2820/3000 (94.0%); historical_spread `PARTIAL`; remaining gaps are daily rollover / Sunday session-break (not unrequested tail); production parquet unchanged |
| Cost-adjusted profitability | **BLOCKED**. Policy Decision 6 = `COMPLETE_COSTS_REQUIRED`. Phase 27.16 **FINAL_GATE=BLOCKED** (not strategy/profitability/real-money approval). Phase 27.15 COST_READY_FOR_VALIDATION=false; 0 COMPLETE datasets |
| Execution / fill lifecycle | **UNKNOWN**. Phase 27.31 grade `DEAL_FILL_TAPE_ONLY`; full fills `NOT_PROVEN`; partials `NOT_PROVEN`; order→deal incomplete; SimulatedBroker full-fill ≠ realized |

---

## Operator / runtime

| Item | Status |
|---|---|
| Operator `.env` effective values | **UNKNOWN** — not read by audits |
| Fresh MT5 operator session | **REAL attached 2026-09-06** — read-only; see Phase 27.17 |
| Live account balance intent ($1000 tier) | **UNKNOWN** (Phase 26M) |

---

## Superseded claims

- Pre-Phase-25B BacktestConfig M1 default → **SUPERSEDED** (M5, Phase 25B/26N)
- Pre-Phase-25B backtest risk 1% → **SUPERSEDED** (0.005, Phase 25B/26N)
- Bare XAUUSD assumed equal to broker symbol → **SUPERSEDED** (Phase 25A/27)

---

## Preserved contradiction registry (CX / UNK — not silently reconciled)

Named items from prior audits remain **OPEN** unless explicitly RESOLVED with evidence. Full audit context: `PRODUCTION_READINESS_AUDIT.md`. Phase 27.7 adds broker-cost blockers above; does not resolve CX/UNK without new evidence.

### CX-001
Mode name `london_sweep` vs NY-session preset reality — **OPEN** (documented; optional rename).

### CX-002
Backtest defaults (M1 / 1% risk / uncosted) vs live — **PARTIALLY RESOLVED** (Phase 25B: M5 + 0.005 risk aligned; costs still uncosted).

### CX-003
**Naming (USER-PROVIDED FACT):** Demo=`XAUUSD_i` / Real=`XAUUSD`. This naming difference is **not** an automatic identity contradiction. **Economics: OPEN** (contract/economic equivalence **UNKNOWN** / NOT PROVEN — EV-EQ-01). Mapping vs observed terminals (both lack bare `XAUUSD`) — **OPEN**; economics **UNKNOWN** without fresh Real evidence. Phase 27.8 locks canonical symbol POLICY as `XAUUSD_i` but does **not** resolve this contradiction or EV-EQ-01.

### CX-004
Historical `docs/` Adaptive-as-default vs current PA lock — **OPEN** (ignore historical for live).

### CX-005
`DEMO_MODE=true` in config does not block `--execute` — **OPEN**.

### CX-006
Real-name `order_value` vs gold `contract_size` (1000× cap risk) — **OPEN** (P0-004).

### CX-007
`.env` can enable Adaptive/VOL and defeat PA production lock — **OPEN**.

### CX-008
Silent `resolve_broker_symbol` auto `_i` fallback vs explicit operator map — **OPEN** (see also CX-017).

### CX-009
Execution volume/stops/partials not fully broker-constrained at send — **OPEN** (P0-005).

### CX-010
Research/backtest OHLC proxy spread vs observed bid/ask — **OPEN** (Phase 27.18: evidence `DATASET`; production datasets `PROXY` / `BLOCKED_PENDING_DATA`; PROXY ≠ historical Bid/Ask; live tick ≠ historical tape).

### CX-011
Operator-effective `.env` values unknown to audits — **OPEN** (UNK-001).

### CX-012
Round-trip cost evidence incomplete — **OPEN** (P0-003; Phase 27.7: 0 COST_COMPLETE datasets).

### CX-013
Session TZ vs UTC hour alignment unverified offline — **OPEN** (P1-001).

### CX-014
Adaptive probe `_enabled` class default may enable probe if key missing — **OPEN** (UNK-009).

### CX-015
CLI `--tf M15` / `--symbol XAUUSD` vs daemon hardcoded M5/`XAUUSD_i` — **OPEN** (documented).

### CX-016
Credential fallbacks in `engine_settings.py` vs env overrides — **OPEN** (P1-005; secrets never documented).

### CX-017
Silent broker-symbol fallback vs explicit DEMO/REAL names — **SUPERSEDED** by Phase 25A strict resolution (code); historical reference retained in `PRODUCTION_READINESS_AUDIT.md`.

**UNK-001** — operator `.env` effective values UNKNOWN (not read by audits).  
**UNK-002** — Demo/Real contract economics continuous verification.  
**UNK-003** — round-trip cost evidence completeness.  
**UNK-004** through **UNK-013** — preserved in `PRODUCTION_READINESS_AUDIT.md`.

---

**Owner artifact:** `logs/phase27_broker_reality_audit.json`  
**Phase 27.5 gate:** `logs/phase27_5_final_broker_cost_gate.json`  
**Phase 27.6 gate:** `logs/phase27_6_final_evidence_gate.json`  
**Phase 27.7 closure:** `logs/phase27_7_final_blocker_closure.json`  
**Phase 27.8 policy lock:** `logs/phase27_8_policy_lock.json`  
**Phase 27.10 dataset binding:** `logs/phase27_10_dataset_symbol_binding.json`  
**Phase 27.13 swap policy:** `logs/phase27_13_swap_policy.json`  
**Phase 27.14 slippage model:** `logs/phase27_14_slippage_model.json`  
**Phase 27.12 commission evidence:** `logs/phase27_12_commission_evidence.json`  
**Phase 27.9 Real evidence:** `logs/phase27_9_real_broker_evidence.json`  
**Phase 27.11 historical bid/ask:** `logs/phase27_11_historical_bidask.json`  
**Phase 27.15 cost completeness gate:** `logs/phase27_15_cost_completeness_gate.json`  
**Phase 27.16 final validation gate:** `logs/phase27_16_FINAL_VALIDATION_GATE.json` — **FINAL_GATE=BLOCKED**  
**Phase 27.17 Real evidence:** `logs/phase27_17_real_broker_evidence.json`  
**Phase 27.18 historical bid/ask:** `logs/phase27_18_historical_bidask.json`  
**Phase 27.19 commission closure:** `logs/phase27_19_commission_closure.json`  
**Phase 27.20 dataset mapping:** `logs/phase27_20_dataset_mapping_closure.json`  
**Phase 27.21 evidence synthesis:** `logs/phase27_21_evidence_synthesis.json` — FINAL_GATE remains BLOCKED  
**Phase 27.22 commission forensic:** `logs/phase27_22_commission_forensic.json` — account_product_type UNKNOWN; classification remains OBSERVED_ZERO_NOT_PROVEN  
**Phase 27.23 bid/ask expansion:** `logs/phase27_23_bidask_expansion.json` — logs tape expanded; production parquet still PROXY; C full-dataset coverage BLOCKED  
**Phase 27.24 execution/cost forensics:** `logs/phase27_24_execution_cost_forensics.json` — swap BROKER_RATE_ONLY; realized slippage UNKNOWN unless genuine requested/fill pairs exist; execution not SimulatedBroker  
**Phase 27.25 canonical bid/ask coverage:** `logs/phase27_25_canonical_bidask_coverage.json` — classification `PARTIAL_CANONICAL_COVERAGE`; production parquet unchanged; C full coverage BLOCKED  
**Phase 27.26 canonical bid/ask coverage:** `logs/phase27_26_canonical_bidask_coverage.json` — `PARTIAL_CANONICAL_COVERAGE`; historical_spread `PARTIAL`; production parquet unchanged  
**Phase 27.27 dataset symbol binding:** `logs/phase27_27_dataset_symbol_binding.json` — `12` DIRECT_CANONICAL_MATCH; `30` MISSING_EXPLICIT_MAP; `0` EXPLICIT_MAPPED; `1` UNKNOWN_PROVENANCE; 0 maps inserted; EV-EQ-01 NOT_PROVEN  
**Phase 27.27 dataset symbol binding:** `logs/phase27_27_dataset_symbol_binding.json` — `6` DIRECT_CANONICAL_MATCH; `30` MISSING_EXPLICIT_MAP; `0` EXPLICIT_MAPPED; `1` UNKNOWN_PROVENANCE; 0 maps inserted; EV-EQ-01 NOT_PROVEN  
**Phase 27.27 dataset symbol binding:** `logs/phase27_27_dataset_symbol_binding.json` — `2` DIRECT_CANONICAL_MATCH; `30` MISSING_EXPLICIT_MAP; `0` EXPLICIT_MAPPED; `1` UNKNOWN_PROVENANCE; 0 maps inserted; EV-EQ-01 NOT_PROVEN  
**Phase 27.28 commission evidence:** `logs/phase27_28_commission_evidence.json` — grade `OBSERVED_ZERO_NOT_PROVEN`; final `OBSERVED_ZERO_NOT_PROVEN`; account_product_type UNKNOWN; VERIFIED_SCHEDULE not satisfied  
**Phase 27.29 swap evidence:** `logs/phase27_29_swap_evidence.json` — grade `REALIZED_ZERO_NOT_PROVEN`; historical series UNKNOWN; current broker rates ≠ historical  
**Phase 27.29 swap evidence:** `logs/phase27_29_swap_evidence.json` — grade `CURRENT_BROKER_RATE_ONLY`; historical series UNKNOWN; current broker rates ≠ historical  
**Phase 27.30 slippage evidence:** `logs/phase27_30_slippage_evidence.json` — grade `REALIZED_UNKNOWN_NOT_IDENTIFIABLE`; genuine pairs `0`; MODELED_PROXY ≠ REALIZED  
**Phase 27.31 execution evidence:** `logs/phase27_31_execution_evidence.json` — grade `DEAL_FILL_TAPE_ONLY`; classification `UNKNOWN`; fill tape ≠ lifecycle; SimulatedBroker ≠ realized  
**Phase 27.32 final cost evidence gate:** `logs/phase27_32_final_cost_evidence_gate.json` — COMPLETE_COSTS_REQUIRED `BLOCKED`; FINAL_GATE `BLOCKED`; AND-complete `0`/8  
**Phase 27.33 EV-EQ resolution:** `logs/phase27_33_ev_eq_resolution.json` — `NOT_PROVEN`; state `B_POLICY_AUTHORIZED_XAUUSD_i_ONLY`; 30 MISSING_EXPLICIT_MAP unchanged; no silent map  
**Operator policy:** `docs_v2/01_truth/OPERATOR_BROKER_POLICY_DECISION.md` (**LOCKED** — Phase 27.8; POLICY ≠ EVIDENCE)

## Performance validation (Phase 28.0)

| Claim | Status |
|---|---|
| Canonical XAUUSD_i M5 is the best defensible performance dataset | **SUPPORTED** |
| Logical XAUUSD tapes usable without explicit map | **BLOCKED** |
| Current gold_ny_sweep has proven trading edge | **DATA_INSUFFICIENT** — short canonical tape; do not invent confidence |
| 0 RiskGate-allowed trades proves no edge | **FALSE** — sample too small; gates unchanged |
| Phase 28.0 authorizes live trading | **NO** — RESEARCH ONLY; FINAL_GATE remains BLOCKED |

## Performance validation (Phase 28.1)

| Claim | Status |
|---|---|
| Chronological baseline uses only Phase 28.0 XAUUSD_i M5 | **SUPPORTED** |
| Logical XAUUSD 183d used as 28.1 range | **BLOCKED** — not used |
| Current strategy has proven edge on this tape | **DATA_INSUFFICIENT** |
| 0 executable trades proves no edge | **FALSE** |
| Phase 28.1 authorizes live trading | **NO** |

## Performance validation (Phase 28.2)

| Claim | Status |
|---|---|
| Walk-forward uses only Phase 28.0/28.1 XAUUSD_i M5 | **SUPPORTED** |
| TRAIN/VALIDATION used for optimization | **NO** — descriptive only |
| Strategy stable across TRAIN/VAL/OOS | **INSUFFICIENT_SAMPLE** |
| Phase 28.2 authorizes live trading | **NO** |

## Performance validation (Phase 28.3)

| Claim | Status |
|---|---|
| MC uses only Phase 28.1/28.2 baseline trades | **SUPPORTED** |
| Spread/slippage shocks are realized costs | **NO** — MODELED / MODELED_PROXY |
| Strategy is MC-robust | **INSUFFICIENT_SAMPLE** |
| Phase 28.3 authorizes live trading | **NO** |

## Performance validation (Phase 28.4)

| Claim | Status |
|---|---|
| Diagnosis uses stored 28.0–28.3 setups + read-only OHLC | **SUPPORTED** |
| 24 RAW rows are independent observations | **FALSE** — event clusters |
| Poor RAW path has a proven single structural cause | **NOT_PROVEN** — official answer J |
| Strategy is proven bad / good | **NOT_ALLOWED** — INSUFFICIENT_SAMPLE |
| Phase 28.4 authorizes live trading or optimization | **NO** |

## Research tape (Phase 29)

| Claim | Status |
|---|---|
| Longest defensible XAUUSD_i M5 tape is the Phase 28 15-day snapshot | **SUPPORTED** this run |
| 180-day XAUUSD_i M5 tape was collected | **NOT_OBSERVED** — attach-only; terminal not running |
| Logical XAUUSD 183d used as XAUUSD_i | **NO** — BLOCKED, not merged |
| Phase 29 authorizes live trading or optimization | **NO** |

## Performance validation (Phase 30)

| Claim | Status |
|---|---|
| Unchanged gold_ny_sweep evaluated on Phase 29 canonical XAUUSD_i M5 | **SUPPORTED** |
| 180-day tape used | **NO** — Phase 29 did not obtain one; 15-day snapshot used |
| Strategy has proven edge / no-edge | **INDETERMINATE** — DATA_INSUFFICIENT |
| 0 RiskGate allows proves strategy failure | **FALSE** |
| Phase 30 authorizes live trading or optimization | **NO** |

## Event independence (Phase 31)

| Claim | Status |
|---|---|
| Official event = (UTC date, Asian high, Asian low, side) | **SUPPORTED** |
| 24 RAW signals are independent observations | **FALSE** — HIGH_DEPENDENCE |
| Phase 28.4 30-minute clusters are the official event | **NO** — diagnostic heuristic only |
| Dependence is a strategy failure | **FALSE** |
| Signal-level bootstrap is independent evidence | **NO** |
| Phase 31 authorizes live trading or optimization | **NO** |

## Walk-forward (Phase 32)

| Claim | Status |
|---|---|
| Chronological 60/20/20 on frozen XAUUSD_i M5 | **SUPPORTED** |
| Rolling WINDOW 1/2/3 produced | **NO** — tape < 60 calendar days |
| Unchanged strategy generalizes | **INSUFFICIENT_SAMPLE** |
| TRAIN/VALIDATION used to optimize | **NO** |
| Phase 32 authorizes live trading | **NO** |

## Robustness (Phase 33)

| Claim | Status |
|---|---|
| Unchanged Phase 30/32 baseline used | **SUPPORTED** |
| Diagnostics are production parameter changes | **NO** |
| Strategy is proven ROBUST / FRAGILE | **INSUFFICIENT_SAMPLE** |
| Cost shocks are realized broker costs | **NO** — MODELED / MODELED_PROXY |
| Phase 33 authorizes live trading or optimization | **NO** |

## Statistical validation (Phase 34)

| Claim | Status |
|---|---|
| Signal-level bootstrap is independent evidence | **NO** — HIGH_DEPENDENCE |
| Event-level n=6 supports significance | **NO** — INSUFFICIENT_SAMPLE |
| Shuffle DD is broker-margin ruin | **NO** |
| Phase 34 authorizes live trading or optimization | **NO** |

## Execution reality (Phase 35)

| Claim | Status |
|---|---|
| Cost completeness AND-gate | **INCOMPLETE** |
| MODELED converted to VERIFIED | **NO** |
| Genuine requested-vs-fill slippage | **0** |
| Theoretical edge survives broker economics | **NOT_PROVEN** |
| Phase 35 placed live orders | **NO** |

## Strategy evidence verdict (Phase 36)

| Claim | Status |
|---|---|
| Strategy verdict | **INSUFFICIENT_EVIDENCE** |
| Evidence supports edge (A) | **NO** |
| Evidence supports no edge (C) | **NO** |
| Production changed or optimized | **NO** |
| FINAL_GATE | **BLOCKED** |
| Phase 37 started by Phase 36 | **NO** |

## Long-horizon tape (Phase 37)

| Claim | Status |
|---|---|
| Phase 37 status | **PASS** |
| Terminal | **ATTACHED** |
| Frozen Phase 28/30 M5 overwritten | **NO** |
| Silent XAUUSD→XAUUSD_i map | **NO** |
| MT5 started by this phase | **NO** |
| Production changed / optimized / strategy evaluated | **NO** |
| Phase 38 started | **NO** |

## Intelligent evidence acquisition (Phase 38)

| Claim | Status |
|---|---|
| Phase 38 status | **PASS** |
| Frozen Phase 28/30 M5 overwritten | **NO** |
| Silent XAUUSD map | **NO** |
| .env read | **NO** |
| Orders sent / bot started | **NO** |
| Phase 39 started | **NO** |
| Canonical XAUUSD_i M5 research tape (phase38) | **OBSERVED** — see PHASE38 artifact |
| EV-EQ-01 | **NOT_PROVEN** |
| Cost completeness | **INCOMPLETE** (gate not weakened) |
| Strategy profitability verdict | **NOT ISSUED** |

## Broker economics execution (Phase 39)

| Claim | Status |
|---|---|
| Phase 39 status | **PASS** |
| Frozen Phase 28/30 M5 overwritten | **NO** |
| Silent XAUUSD map | **NO** |
| cost_ready_for_validation | **FALSE** |
| Profitability verdict | **NOT ISSUED** |
| Phase 40 started | **NO** |

## Full-horizon unchanged strategy validation (Phase 40)

| Claim | Status |
|---|---|
| Phase 40 status | **PASS** |
| Frozen Phase 28/30 M5 overwritten | **NO** |
| Silent XAUUSD map | **NO** |
| Full tape scan completed | **YES** |
| Strategy RAW classification | **B** |
| Broker-realistic classification | **D** |
| Profitability verdict | **NOT ISSUED** |
| Phase 41 started | **YES** |

## Final evidence closure (Phase 41)

| Claim | Status |
|---|---|
| Phase 41 status | **PASS** |
| Phase 40 rescan | **NO** |
| Frozen Phase 28/30 M5 overwritten | **NO** |
| Silent XAUUSD map | **NO** |
| FINAL_GATE | **BLOCKED** |
| Overall research verdict | **INSUFFICIENT_EVIDENCE** |
| Profitability verdict | **NOT ISSUED** |
| Phase 42 started | **YES** |

## Broker cost execution closure (Phase 42)

| Claim | Status |
|---|---|
| Phase 42 status | **PASS** |
| Phase 40 rescan | **NO** |
| MT5 launched by phase | **NO** |
| Commission | **UNKNOWN** |
| EV-EQ-01 | **NOT_PROVEN** |
| Executable ready | **False** |
| FINAL_GATE | **BLOCKED** |
| Phase 43 started | **YES** |

## Broker cost execution validation (Phase 43)

| Claim | Status |
|---|---|
| Phase 43 status | **PASS** |
| Phase 40 rescan | **NO** |
| Account product | **UNKNOWN** |
| Commission | **UNKNOWN** |
| EV-EQ-01 | **NOT_PROVEN** |
| Executable ready | **False** |
| FINAL_GATE | **BLOCKED** |
| Phase 44 started | **YES** |

## Executable readiness / robustness / parity (Phases 44–46)

| Claim | Status |
|---|---|
| Phase 44 executable ready | **False / BLOCKED** |
| Phase 45 robustness | **FRAGILE** (RAW); cost-aware MODELED |
| Phase 46 production readiness | **NOT_READY** |
| Commission | **UNKNOWN** |
| FINAL_GATE | **BLOCKED** |
| Phase 47 started | **YES** |

## Final blocker / executable / robustness / parity (Phases 47–50)

| Claim | Status |
|---|---|
| Commission VERIFIED_SCHEDULE | **False** |
| Executable | **BLOCKED** |
| Robustness | **FRAGILE** |
| Production readiness | **NOT_READY** |
| FINAL_GATE | **BLOCKED** |
| NO-GO optimization/live | **YES** |
| Phase 51 started | **YES** |

## Final evidence / optimization gate / shadow spec (Phases 51–53)

| Claim | Status |
|---|---|
| Commission VERIFIED_SCHEDULE | **False** |
| EV-EQ-01 | **NOT_PROVEN** |
| Optimization gate | **BLOCKED** |
| Optimization executed | **NO** |
| Shadow framework | **SPECIFIED / NOT_ACTIVATED** |
| Shadow orders | **0** |
| FINAL_GATE | **BLOCKED** |
| Phase 54 started | **YES** |

## Account/broker discovery / cost scenarios / information-value (Phases 54–56)

| Claim | Status |
|---|---|
| Account product | **UNKNOWN** |
| Commission VERIFIED_SCHEDULE | **False** |
| EV-EQ-01 | **NOT_PROVEN** (absence ≠ CONTRADICTED) |
| CLASSIC/CENT R conversion | **UNKNOWN** |
| ECN $5/lot | **SCENARIO only** |
| FINAL_GATE | **BLOCKED** |
| Optimization / live | **NO-GO** |
| Project stopped | **NO** |
| Phase 57 started | **YES** |

## Account product / commission / symbol forensics (Phases 57–60)

| Claim | Status |
|---|---|
| G1 account product | **PARTIAL** |
| G2 commission | **PARTIAL** |
| G3 symbol equivalence | **FAIL** |
| AUTHORIZED_NEXT_PHASE | **TARGETED_EVIDENCE_COLLECTION** |
| FINAL_GATE | **BLOCKED** |
| Optimization / shadow / live | **NO-GO** |
| Phase 61 started | **YES** |

## Edge survival / next-step economics (Phases 61–63)

| Claim | Status |
|---|---|
| EDGE_QUALITY | **FRAGILE** |
| COST_TOLERANCE | **FAIL** |
| NEXT_PHASE | **STRATEGY_RESEARCH_BEFORE_BROKER_WORK** |
| FINAL_GATE | **BLOCKED** |
| Optimization / shadow / live | **NO-GO** |
| Phase 64 started | **YES** |

## Strategy causal diagnosis (Phases 64–67)

| Claim | Status |
|---|---|
| PRIMARY_ROOT_CAUSE | **EXIT_PROBLEM** |
| NEXT_RESEARCH_TARGET | **EXIT_RESEARCH** |
| Optimization | **NO** |
| Production strategy modified | **NO** |
| Broker forensics restarted | **NO** |
| FINAL_GATE | **BLOCKED** |
| Phase 68 started | **YES** |

## Exit forensics (Phases 68–73)

| Claim | Status |
|---|---|
| PRIMARY_CAUSE | **PROFIT_GIVEBACK** |
| NEXT_RESEARCH_TARGET | **PROFIT_PROTECTION_RESEARCH** |
| EXTREME_WINNER_CLASSIFICATION | **B_RARE_LEGITIMATE_STRUCTURAL** |
| Intervention implemented | **NO** |
| Optimization | **NO** |
| Production modified | **NO** |
| MT5 used | **NO** |
| FINAL_GATE | **BLOCKED** |
| Phase 74 started | **YES** |

## Profit-giveback exit research (Phases 74–81)

| Claim | Status |
|---|---|
| PRIMARY_EXIT_MECHANISM | **PROFIT_GIVEBACK** |
| NEXT_RESEARCH_TARGET | **PROFIT_PROTECTION_DESIGN** |
| BEST_STRUCTURAL_COUNTERFACTUAL | **E_TIME_EXIT_AFTER_FAVORABLE_EXCURSION** (NEUTRAL) |
| Intervention implemented | **NO** |
| Optimization | **NO** |
| Production modified | **NO** |
| MT5 used | **NO** |
| FINAL_GATE | **GO_RESEARCH** |
| Phase 82 started | **YES** |

## Profit-protection design research (Phases 82–89)

| Claim | Status |
|---|---|
| PROFIT_PROTECTION_STATUS | **PARTIALLY_SUPPORTED** |
| EXIT_DESIGN_SPEC | **INSUFFICIENT_EVIDENCE** |
| NEXT_RESEARCH_TARGET | **MORE_PROFIT_PROTECTION_FORENSICS** |
| TAIL_PRESERVATION | **DESTROYED** |
| Intervention implemented | **NO** |
| Optimization | **NO** |
| Parameter search | **NO** |
| Production modified | **NO** |
| MT5 used | **NO** |
| FINAL_GATE | **GO_RESEARCH** |
| Phase 90 started | **YES** |

## Profit-protection path forensics (Phases 90–97)

| Claim | Status |
|---|---|
| PROTECTION_STATUS | **PROTECTION_DESIGN_PARTIALLY_SUPPORTED** |
| EXIT_DESIGN_SPEC | **INSUFFICIENT_EVIDENCE** |
| NEXT_RESEARCH_TARGET | **MORE_PROFIT_PROTECTION_FORENSICS** |
| TAIL_DISCRIMINATOR | **NOT_ESTABLISHED** |
| Signals independent | **NO** (event unit required) |
| Intervention implemented | **NO** |
| Optimization | **NO** |
| Parameter search | **NO** |
| Production modified | **NO** |
| MT5 used | **NO** |
| FINAL_GATE | **GO_RESEARCH** |
| Phase 98 started | **YES** |

## Discriminator forensics (Phases 98–105)

| Claim | Status |
|---|---|
| DISCRIMINATOR_STATUS | **UNSUPPORTED** |
| EXIT_DESIGN_SPEC | **INSUFFICIENT_EVIDENCE** |
| NEXT_RESEARCH_TARGET | **NON_OHLC_DISCRIMINATOR_RESEARCH** |
| C/D vs E/F separable on frozen M5 OHLC | **NO** |
| +31.84R preserved by a candidate | **NO** |
| Intervention implemented | **NO** |
| Optimization | **NO** |
| Parameter search | **NO** |
| Production modified | **NO** |
| MT5 used | **NO** |
| FINAL_GATE | **GO_RESEARCH** |
| Phase 106 started | **YES** |

## Non-OHLC discriminator research (Phases 106–113)

| Claim | Status |
|---|---|
| DISCRIMINATOR_STATUS | **UNSUPPORTED** |
| TICK_DISCRIMINATOR_STATUS | **DATA_MISSING** |
| SPREAD_DISCRIMINATOR_STATUS | **DATA_MISSING** |
| HTF_DISCRIMINATOR_STATUS | **UNSUPPORTED** |
| NEWS_DISCRIMINATOR_STATUS | **DATA_MISSING** |
| MULTISOURCE_DISCRIMINATOR_STATUS | **DATA_MISSING** |
| EXIT_DESIGN_SPEC | **INSUFFICIENT_EVIDENCE** |
| NEXT_RESEARCH_TARGET | **FULL_HORIZON_NON_OHLC_DATA_ACQUISITION** |
| C/D vs E/F separable with non-OHLC | **NO** |
| Intervention implemented | **NO** |
| Data downloaded | **NO** |
| Optimization | **NO** |
| Production modified | **NO** |
| MT5 used | **NO** |
| FINAL_GATE | **GO_RESEARCH** |
| Phase 114 started | **YES** |

## Non-OHLC acquisition contract (Phase 114)

| Claim | Status |
|---|---|
| ACQUISITION_READY | **True** |
| DATA_ACQUIRED | **NO** |
| CONTRACT_COMPLETE | **True** |
| NEXT_RESEARCH_TARGET | **OPERATOR_AUTHORIZED_XAUUSD_I_INGEST** |
| Canonical symbol | **XAUUSD_i** (XAUUSD not a substitute) |
| Intervention implemented | **NO** |
| MT5 used | **NO** |
| ENV read | **NO** |
| FINAL_GATE | **GO_RESEARCH** |
| Phase 115 started | **YES** |

## Non-OHLC data acquisition (Phase 115)

| Claim | Status |
|---|---|
| PHASE115_STATUS | **PASS** |
| ACQUISITION_STATUS | **LOCAL_SIDECARS_ONLY** |
| INGESTION_STATUS | **COMPLETE_FOR_AVAILABLE_SOURCES** |
| DATA_QUALITY_STATUS | **PARTIAL** |
| PHASE116_READY | **False** |
| TICK_STATUS | **TICK_DATA_PARTIAL** |
| Canonical symbol | **XAUUSD_i** (XAUUSD not a substitute) |
| EV-EQ-01 | **NOT_PROVEN** |
| Intervention implemented | **NO** |
| MT5 used | **NO** |
| ENV read | **NO** |
| Exit design implemented | **NO** |
| FINAL_GATE | **GO_RESEARCH** |
| Phase 116 started | **YES** |

## Non-OHLC source research (Phase 116)

| Claim | Status |
|---|---|
| PHASE116_STATUS | **PASS** |
| SOURCE_RESEARCH_STATUS | **COMPLETE** |
| ACQUISITION_PATH_STATUS | **READY_WITH_OPERATOR_ACTION** |
| DATA_ACQUIRED | **NO** |
| Canonical symbol | **XAUUSD_i** (XAUUSD not a substitute) |
| EV-EQ-01 | **NOT_PROVEN** |
| MT5 used | **NO** |
| ENV read | **NO** |
| Exit design implemented | **NO** |
| FINAL_GATE | **GO_RESEARCH** |
| Phase 117 started | **YES** |

## Operator source resolution (Phase 117)

| Claim | Status |
|---|---|
| PHASE117_STATUS | **PASS** |
| ACQUISITION_STATUS | **OPERATOR_ACTION_REQUIRED** |
| DATA_ACQUIRED | **NO** |
| EXPORT_STATUS | **MISSING** |
| RAW_INTEGRITY_STATUS | **MISSING** |
| Canonical symbol | **XAUUSD_i** (XAUUSD not a substitute) |
| EV-EQ-01 | **NOT_PROVEN** |
| MT5 used | **NO** |
| ENV read | **NO** |
| Exit design implemented | **NO** |
| FINAL_GATE | **GO_RESEARCH** |
| Phase 117 started | **YES** |
| Phase 118 started | **YES** |

## Tick forensic validation (Phase 118)

| Claim | Status |
|---|---|
| PHASE118_STATUS | **PASS** |
| RAW_FILE_PRESENT | **YES** |
| SOURCE_IDENTITY_STATUS | **VERIFIED** |
| HISTORY_RANGE_STATUS | **PARTIAL** |
| TICK_EVENT_COVERAGE | **12** |
| AMBIGUOUS_394_RESOLVED | **12** |
| AMBIGUOUS_394_REMAINING | **382** |
| OUTLIER_31_84R_COVERAGE | **False** |
| OUTLIER_31_84R_CHRONOLOGY_STATUS | **DATA_INSUFFICIENT** |
| C_D_E_F_STATUS | **PARTIAL_LATE_2026_WINDOW_ONLY** |
| DATA_ACQUIRED | **YES** |
| Canonical symbol | **XAUUSD_i** |
| EV-EQ-01 | **NOT_PROVEN** |
| MT5 used | **NO** |
| ENV read | **NO** |
| Exit design implemented | **NO** |
| Phase 119 started | **YES** |

## Historical tick recovery (Phase 119)

| Claim | Status |
|---|---|
| PHASE119_STATUS | **PASS** |
| SOURCE_RESEARCH_STATUS | **COMPLETE** |
| CANONICAL_SOURCE_AVAILABLE | **False** |
| FULL_HORIZON_SOURCE_STATUS | **MISSING** |
| OUTLIER_31_84R_COVERAGE | **False** |
| ACQUISITION_STATUS | **OPERATOR_CONTACT_REQUIRED** |
| DATA_ACQUIRED | **NO** |
| NEXT_ACTION | **REQUEST_LITEFINANCE_XAUUSD_I_HISTORICAL_TICK_DUMP** |
| Canonical symbol | **XAUUSD_i** |
| EV-EQ-01 | **NOT_PROVEN** |
| MT5 used | **NO** |
| ENV read | **NO** |
| Exit design implemented | **NO** |
| Phase 120 started | **YES** |

## Tick export verification (Phase 120)

| Claim | Status |
|---|---|
| PHASE120_STATUS | **PASS** |
| NEW_EXPORT_FIRST_TICK | **2026-05-20T01:01:00.057000Z** |
| NEW_EXPORT_LAST_TICK | **2026-07-24T23:58:59.975000Z** |
| TICK_EVENT_COVERAGE | **27** |
| AMBIGUOUS_394_RESOLVED_TOTAL | **26** |
| AMBIGUOUS_394_REMAINING | **368** |
| OUTLIER_31_84R_TICK_COVERAGE | **False** |
| FULL_HORIZON_SOURCE_STATUS | **PARTIAL** |
| NEXT_ACTION | **REQUEST_NEXT_SMALL_BACKWARD_XAUUSD_I_EXPORT** |
| Canonical symbol | **XAUUSD_i** |
| MT5 used | **NO** |
| ENV read | **NO** |
| Exit design implemented | **NO** |
| Phase 121 started | **YES** |

## Tick export verification (Phase 121)

| Claim | Status |
|---|---|
| PHASE121_STATUS | **PASS** |
| NEW_EXPORT_FIRST_TICK | **2026-01-02T01:15:00.282000Z** |
| NEW_EXPORT_LAST_TICK | **2026-05-19T23:58:59.782000Z** |
| TICK_EVENT_COVERAGE | **61** |
| AMBIGUOUS_394_RESOLVED_TOTAL | **58** |
| AMBIGUOUS_394_REMAINING | **336** |
| OUTLIER_31_84R_TICK_COVERAGE | **True** |
| OUTLIER_31_84R_CHRONOLOGY_STATUS | **ADVERSE_FIRST** |
| FULL_HORIZON_SOURCE_STATUS | **PARTIAL** |
| NEXT_ACTION | **REQUEST_NEXT_SMALL_BACKWARD_XAUUSD_I_EXPORT** |
| Canonical symbol | **XAUUSD_i** |
| MT5 used | **NO** |
| ENV read | **NO** |
| Exit design implemented | **NO** |
| Phase 122 started | **YES** |

## Tick export verification (Phase 122)

| Claim | Status |
|---|---|
| PHASE122_STATUS | **PASS** |
| NEW_EXPORT_FIRST_TICK | **2025-11-03T01:06:00.068000Z** |
| NEW_EXPORT_LAST_TICK | **2026-01-02T23:58:59.935000Z** |
| TICK_EVENT_COVERAGE | **77** |
| AMBIGUOUS_394_RESOLVED_TOTAL | **72** |
| AMBIGUOUS_394_REMAINING | **322** |
| OUTLIER_31_84R_TICK_COVERAGE | **True** |
| OUTLIER_31_84R_CHRONOLOGY_STATUS | **ADVERSE_FIRST** |
| FULL_HORIZON_SOURCE_STATUS | **PARTIAL** |
| NEXT_ACTION | **REQUEST_NEXT_SMALL_BACKWARD_XAUUSD_I_EXPORT** |
| Canonical symbol | **XAUUSD_i** |
| MT5 used | **NO** |
| ENV read | **NO** |
| Exit design implemented | **NO** |
| Phase 123 started | **YES** |

## Engineering decision review (Phase 123)

| Claim | Status |
|---|---|
| PHASE123_STATUS | **PASS** |
| PRIMARY_RECOMMENDATION | **FREEZE_CURRENT_SYSTEM_AND_BUILD_RESEARCH_V2** |
| PRIMARY_ENGINEERING_TARGET | **EVENT_LEVEL_RESEARCH_FOUNDATION** |
| EXIT_ACTION | **FREEZE_EXIT_AND_REBUILD_ENTRY** |
| TAIL_POLICY | **PRESERVE** |
| ML_READINESS | **NOT_READY** |
| CANONICAL_RESEARCH_UNIT | **LIFECYCLE_EVENT** |
| NEW_TICK_EXPORT_REQUIRED | **FALSE** |
| PRODUCTION_CHANGE_ALLOWED | **FALSE** |
| Phase 124 started | **NO** |

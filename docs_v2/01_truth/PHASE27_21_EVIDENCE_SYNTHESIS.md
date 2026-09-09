# Phase 27.21 — Evidence Synthesis & Remaining Blocker Audit

**Status:** PASS  
**FINAL_GATE:** **BLOCKED**  
**Artifact:** `logs/phase27_21_evidence_synthesis.json`

Audit/synthesis only. Gates were not weakened. Strategy, RiskGate, execution, sizing, RR, and ML were not changed. No MT5 collection.

## Locked policy (not evidence)

| # | POLICY |
|---|---|
| 1 | Canonical gold = `XAUUSD_i` |
| 2 | Logical XAUUSD = `ONLY_WITH_EXPLICIT_DATASET_MAP` |
| 3 | Commission = `VERIFIED_SCHEDULE` |
| 4 | Swap = `BROKER_RATE_ONLY` |
| 5 | Slippage = `MODELED` |
| 6 | Validation = `COMPLETE_COSTS_REQUIRED` |

## 1. Current evidence matrix

| Component | Status | Evidence artifact |
|---|---|---|
| `symbol_binding` | **BLOCKED** | `logs/phase27_20_dataset_mapping_closure.json` |
| `EV-EQ-01` | **BLOCKED** | `logs/phase27_17_real_broker_evidence.json` |
| `broker_economics` | **PARTIAL** | `logs/phase27_17_real_broker_evidence.json` |
| `dataset_provenance` | **PARTIAL** | `logs/phase27_20_dataset_mapping_closure.json` |
| `historical_spread` | **BLOCKED** | `logs/phase27_18_historical_bidask.json` |
| `commission` | **BLOCKED** | `logs/phase27_19_commission_closure.json` |
| `swap` | **UNKNOWN** | `logs/phase27_13_swap_policy.json + logs/phase27_17_real_broker_evidence.json` |
| `slippage` | **UNKNOWN** | `logs/phase27_14_slippage_model.json` |
| `execution_model` | **UNKNOWN** | `tradingbot/backtest/broker.py SimulatedBroker; logs/phase27_15_cost_completeness_gate.json` |
| `cost_completeness` | **BLOCKED** | `logs/phase27_15_cost_completeness_gate.json` |

## 2. What Phase 27.17 actually closed

Fresh Real attach `REAL_COLLECTED` on LiteFinance-MT5-Live. `XAUUSD_i` existence `YES`. `XAUUSD` existence `NO`. Fresh `XAUUSD_i` economics collected. **EV-EQ-01 remains NOT_PROVEN.** Did not close commission, maps, or FINAL_GATE.

## 3. What Phase 27.18 actually closed

Historical Bid/Ask **existence** = `PROVEN` (`82` M5 bars; logs-only bounded window).

| Question | Status |
|---|---|
| A. Historical Bid/Ask exists | **PROVEN** |
| B. Historical spread for the entire canonical dataset | **BLOCKED** |
| C. Cost-aware validation of the production research dataset | **BLOCKED** |

A must not be treated as B or C.

## 4. EV-EQ-01

`XAUUSD` absent and `XAUUSD_i` present on this Real catalog does **not** prove equivalence and does **not** prove broker-wide absence. Decision 1 does not close EV-EQ-01. **NOT_PROVEN / BLOCKED.**

## 5. Dataset mapping

No new provenance justifies an explicit map. Filename, environment resolution, and broker-symbol similarity were not used. **30 logical XAUUSD remain BLOCKED.**

## 6. Commission

Still **UNKNOWN / BLOCKED**. 50 gold zeros remain `OBSERVED_ZERO_NOT_PROVEN`. `commission_per_lot=0.0` is not `ZERO`.

## 7. Swap (`BROKER_RATE_ONLY`)

Broker rates **PROVEN** (snapshot). Rollover day **PROVEN** (`3`). Historical series **UNKNOWN**. Current COMPLETE contract requires a historical series; `BROKER_RATE_ONLY` blocks completeness. Series was not synthesized.

## 8. Slippage (`MODELED`)

Realized samples = `0`. MODELED_PROXY is documented (`0.8` pips + session multiplier). Under current code, modeled slippage does **not** make COMPLETE. Lack of realized data **does** block COMPLETE.

## 9. Execution model

`SimulatedBroker` assumes full fill and fail-closes on UNKNOWN commission. Status remains **UNKNOWN** because 27.15 requires a realized execution tape for COMPLETE. This is mixed: documented simulation contract **and** missing realized fills. Not reclassified.

## 10. Minimum remaining evidence

| BLOCKER | CURRENT STATUS | WHY BLOCKED | MINIMUM EVIDENCE | FROM CURRENT REAL TERMINAL? | OPERATOR DECISION? | HISTORICAL DATA? | CODE CHANGE? |
|---|---|---|---|---|---|---|---|
| EV-EQ-01 | NOT_PROVEN / BLOCKED | XAUUSD absent and XAUUSD_i present on one Real terminal is not equivalence. | Both symbols on the same Real terminal with critical-field MATCH. | NO — XAUUSD is not in this catalog | NO (Decision 1 already locked; does not close EV-EQ-01) | NO | NO |
| symbol_binding / 30 logical XAUUSD | BLOCKED | ONLY_WITH_EXPLICIT_DATASET_MAP; filename/sidecar label is not a map. | Explicit per-dataset or BacktestConfig dataset_symbol_map plus provenance. | NO — mapping is authorization/provenance, not a tick download | YES — authorize explicit maps or leave blocked | NO (unless proving dataset origin) | NO |
| historical_spread dataset/validation coverage | BLOCKED | 82 M5 bars / one session prove existence only; production XAUUSD_i parquets are OHLC PROXY. | Historical Bid/Ask covering the canonical validation dataset range, stored as a bound tape (not live tick). | PARTIAL — copy_ticks_range if broker retains ticks; 100k cap / weekend limits apply | NO | YES | NO (ingest later; do not convert OHLC) |
| commission VERIFIED_SCHEDULE | UNKNOWN / BLOCKED | Account/product type, basis, and applicability missing. Observed zeros ≠ schedule. | Account-applicable schedule with product type, basis, currency, effective date. | NO — read-only account identity is not a schedule | YES — obtain/confirm product type and applicable schedule | NO | NO |
| swap historical series | UNKNOWN | Rates/rollover are snapshots. COMPLETE currently requires a historical series; BROKER_RATE_ONLY blocks completeness. | Historical swap series, or an explicit later policy change (not proposed). | NO — a single attach is not a series | NO (Decision 4 already locked) | YES (for COMPLETE under current code) | NO (changing this to COMPLETE from rates would weaken the gate) |
| slippage realized distribution | UNKNOWN | MODELED_PROXY is documented; 0 requested-vs-fill samples. MODELED ≠ COMPLETE. | Statistically sufficient requested-vs-fill pairs. | PARTIAL — only if deal history contains usable request vs fill | NO (Decision 5 already locked) | YES (realized tape) | NO |
| execution_model | UNKNOWN | SimulatedBroker full-fill is not a realized execution tape; 27.15 requires realized fills for COMPLETE. | Realized fill/partial tape, or a later documented simulation-contract path (not added here). | PARTIAL — live/history fills only if collected as an execution tape | NO | YES for realized COMPLETE | NO in this phase; classification-only path would be a later decision |
| cost_completeness / FINAL_GATE | BLOCKED | COMPLETE_COSTS_REQUIRED AND of all components is not COMPLETE. | Every required component COMPLETE without weakening the AND. | NO — multiple independent gaps remain | YES for maps and commission; NO for inventing COMPLETE | YES (spread coverage, swap series, realized slippage/execution) | NO |

## 11. Documentation / classification vs evidence

- **27.15/27.16 economics still cite Phase 27.9** — `DOCUMENTATION_OR_CLASSIFICATION_LAG` (not auto-fixed): 27.17 collected fresh Real XAUUSD_i economics. Re-pointing 27.15 would likely move economics UNKNOWN→PARTIAL, not COMPLETE (EV-EQ-01 still NOT_PROVEN). Not auto-fixed.
- **27.8 'evidence still missing' still lists fresh Real and M5 tape as MISSING** — `STALE_LOCKED_SNAPSHOT` (not auto-fixed): 27.8 is a locked snapshot. 27.17/27.18 closed those items at sample/fresh-attach level only.
- **execution_model UNKNOWN vs documented SimulatedBroker contract** — `MIXED_CLASSIFICATION_AND_EVIDENCE` (not auto-fixed): A documented full-fill simulator exists, but COMPLETE currently requires realized fills. Reclassifying simulation as COMPLETE would weaken Decision 6. Not auto-fixed.
- **27.18 logs tape vs 27.15 spread BLOCKED** — `NOT_DOCUMENTATION — COVERAGE GAP` (not auto-fixed): Existence is PROVEN. Dataset/validation coverage remains BLOCKED. Must not conflate A with B/C.

## Production

**BLOCKED.** `COST_READY_FOR_VALIDATION` = `False`. FINAL_GATE remains **BLOCKED**. Phase 27.22+ not started.

## Next

STOP after Phase 27.21.

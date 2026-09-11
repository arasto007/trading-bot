# AUDIT_2 — Failing Test Triage

**Generated (UTC):** 2026-09-09T15:05:11.060835+00:00
**Phase:** REPORT ONLY — diagnosis only; no fixes applied.
**Sources:** AUDIT_1 baseline + junit; isolation re-runs (docs/phase15b/ml_base_dir/phase25e); logs/phase27_*.json inspection.

## Epistemic / evidence-gate REAL_BUG flags (read first)

Do **not** casually mark these stale or delete them. They catch missing memory or overstated evidence.

| Test | Note |
|------|------|
| `test_owner_docs_have_epistemic_role` | CURRENT_RUNTIME_STATE.md empty (0 bytes HEAD); missing Epistemic-Role |
| `test_documentation_verification_gate` | failed_gates derived_labels/freshness_baseline/operator_state_separated |
| `test_no_proven_xauusd_equivalence_claims` | Scanner flags EV-EQ-01 NOT_PROVEN lines as equivalence claims |
| `test_blocker_matrix_covers_open_components` | spread omitted from blockers after status COMPLETE |
| `test_cost_ready_remains_blocked` | spread component marked COMPLETE |
| `test_proxy_spread_not_historical` | expects BLOCKED; artifact COMPLETE |
| `test_artifact_valid` | artifact status FAIL; complete_applicability_can_be_accepted=False |
| `test_evidence_gaps_recorded` | historical_m5_bidask True overclaim from ticks |
| `test_canonical_entry_remains_unique` | PROJECT_DECISION_BASELINE.md empty in HEAD |
| `test_demo_real_symbol_mapping_not_automatic_contradiction` | empty baseline md |
| `test_live_pa_ml_v41_lock` | empty baseline md |
| `test_code_default_vs_operator_state` | empty baseline md |
| `test_hierarchy_and_limits` | empty baseline md |
| `test_major_claims_have_evidence_references` | empty baseline md |

Highest severity: `PROJECT_DECISION_BASELINE.md` and `CURRENT_RUNTIME_STATE.md` are **0 bytes in git HEAD** (`0898515`).
Overclaim severity: `data/XAUUSD_i_ticks_phase38.parquet` counted as historical bid/ask, flipping spread COMPLETE / historical_m5_bidask=True while notes still say No M5 tape.

## 1. Summary table

| # | Test | Classification | One-line reason |
|---|------|----------------|-----------------|
| 1 | `test_documentation_memory_hardening_v2.py::test_owner_docs_have_epistemic_role` | **REAL_BUG** | CURRENT_RUNTIME_STATE.md empty (0 bytes HEAD); missing Epistemic-Role |
| 2 | `test_documentation_verification.py::test_documentation_verification_gate` | **REAL_BUG** | failed_gates derived_labels/freshness_baseline/operator_state_separated |
| 3 | `test_ml_base_dir.py::TestNormalizeMlBaseDir::test_build_strategy_registry_with_legacy_base_dir` | **STALE_TEST** | Expects MLKernelRegistry; gets MultiEngineRouterRegistry |
| 4 | `test_phase15b_kernel_integration.py::TestKernelAdapter::test_generate_signal_returns_trading_signal_or_none` | **FLAKY_OR_ENV** | pipeline_timeout in AUDIT_1; passed isolation re-run |
| 5 | `test_phase15b_kernel_integration.py::TestKernelAdapter::test_prediction_cache_hit` | **FLAKY_OR_ENV** | pipeline_timeout in AUDIT_1; passed isolation re-run |
| 6 | `test_phase15b_kernel_integration.py::TestKernelAdapter::test_produce_unified_signal` | **FLAKY_OR_ENV** | pipeline_timeout in AUDIT_1; passed isolation re-run |
| 7 | `test_phase15b_kernel_integration.py::TestLatency::test_adapter_latency_under_budget_cached` | **FLAKY_OR_ENV** | pipeline_timeout in AUDIT_1; passed isolation re-run |
| 8 | `test_phase15b_kernel_integration.py::TestUnifiedSignalIntegration::test_unified_validate_after_adapter` | **FLAKY_OR_ENV** | pipeline_timeout in AUDIT_1; passed isolation re-run |
| 9 | `test_phase15b_kernel_integration.py::TestExtraCoverage::test_registry_ml_success_count` | **FLAKY_OR_ENV** | 0 successes after timeouts; passed isolation re-run |
| 10 | `test_phase25e_sidecar_bidask.py::TestHistoricalBidAskSearch::test_repo_search` | **STALE_TEST** | bidask_dataset_count=1 (Phase38 ticks); test requires 0 |
| 11 | `test_phase26o_legacy_docs_truth_sweep.py::TestPhase26OArtifact::test_no_proven_xauusd_equivalence_claims` | **REAL_BUG** | Scanner flags EV-EQ-01 NOT_PROVEN lines as equivalence claims |
| 12 | `test_phase27_11_historical_bidask.py::TestPhase2711HistoricalBidAsk::test_repo_has_no_historical_bid_ask` | **STALE_TEST** | Same tick parquet makes count=1 |
| 13 | `test_phase27_15_cost_completeness_gate.py::TestPhase2715CostCompletenessGate::test_blocker_matrix_covers_open_components` | **REAL_BUG** | spread omitted from blockers after status COMPLETE |
| 14 | `test_phase27_15_cost_completeness_gate.py::TestPhase2715CostCompletenessGate::test_cost_ready_remains_blocked` | **REAL_BUG** | spread component marked COMPLETE |
| 15 | `test_phase27_15_cost_completeness_gate.py::TestPhase2715CostCompletenessGate::test_proxy_spread_not_historical` | **REAL_BUG** | expects BLOCKED; artifact COMPLETE |
| 16 | `test_phase27_16_final_validation_gate.py::TestPhase2716FinalValidationGate::test_blocker_matrix_precise` | **STALE_TEST** | historical_spread key absent from current matrix |
| 17 | `test_phase27_18_historical_bidask.py::TestPhase2718HistoricalBidAsk::test_repo_has_no_production_historical_bid_ask` | **STALE_TEST** | Same Phase38 tick count drift |
| 18 | `test_phase27_19_commission_closure.py::TestPhase2719CommissionClosure::test_artifact_valid` | **REAL_BUG** | artifact status FAIL; complete_applicability_can_be_accepted=False |
| 19 | `test_phase27_20_dataset_mapping_closure.py::TestPhase2720DatasetMappingClosure::test_artifact_valid` | **STALE_TEST** | canonical count expected 2 now 6 |
| 20 | `test_phase27_21_evidence_synthesis.py::TestPhase2721EvidenceSynthesis::test_artifact_and_final_gate_blocked` | **STALE_ARTIFACT** | collector status FAIL vs expected PASS |
| 21 | `test_phase27_21_evidence_synthesis.py::TestPhase2721EvidenceSynthesis::test_spread_coverage_not_conflated` | **STALE_ARTIFACT** | A/B coverage inverted vs expected |
| 22 | `test_phase27_30_slippage_evidence.py::TestPhase2730SlippageEvidence::test_zero_pairs_are_not_identifiable` | **STALE_ARTIFACT** | account_type UNKNOWN vs REAL |
| 23 | `test_phase27_31_execution_evidence.py::TestPhase2731ExecutionEvidence::test_artifact_schema_and_no_credentials` | **STALE_ARTIFACT** | account_type UNKNOWN vs REAL |
| 24 | `test_phase27_32_final_cost_evidence_gate.py::TestPhase2732FinalCostEvidenceGate::test_artifact_schema_and_no_credentials` | **STALE_ARTIFACT** | account_type UNKNOWN vs REAL |
| 25 | `test_phase27_32_final_cost_evidence_gate.py::TestPhase2732FinalCostEvidenceGate::test_no_component_is_complete_and_gate_blocked` | **STALE_TEST** | swap grade REALIZED_ZERO_NOT_PROVEN vs CURRENT_BROKER_RATE_ONLY |
| 26 | `test_phase27_33_ev_eq_resolution.py::TestPhase2733EvEqResolution::test_artifact_schema_and_no_credentials` | **STALE_ARTIFACT** | status FAILED from hard-coded census; account_type UNKNOWN |
| 27 | `test_phase27_33_ev_eq_resolution.py::TestPhase2733EvEqResolution::test_contract_and_inventory` | **STALE_TEST** | direct_XAUUSD_i expected 2 now 6 |
| 28 | `test_phase27_8_policy_lock.py::TestPhase278PolicyLock::test_evidence_gaps_recorded` | **REAL_BUG** | historical_m5_bidask True overclaim from ticks |
| 29 | `test_project_decision_baseline.py::test_canonical_entry_remains_unique` | **REAL_BUG** | PROJECT_DECISION_BASELINE.md empty in HEAD |
| 30 | `test_project_decision_baseline.py::test_demo_real_symbol_mapping_not_automatic_contradiction` | **REAL_BUG** | empty baseline md |
| 31 | `test_project_decision_baseline.py::test_live_pa_ml_v41_lock` | **REAL_BUG** | empty baseline md |
| 32 | `test_project_decision_baseline.py::test_code_default_vs_operator_state` | **REAL_BUG** | empty baseline md |
| 33 | `test_project_decision_baseline.py::test_hierarchy_and_limits` | **REAL_BUG** | empty baseline md |
| 34 | `test_project_decision_baseline.py::test_major_claims_have_evidence_references` | **REAL_BUG** | empty baseline md |

## 2. Per-test sections

### `tests/test_documentation_memory_hardening_v2.py::test_owner_docs_have_epistemic_role`

- **Classification:** **REAL_BUG**
- **One-line:** CURRENT_RUNTIME_STATE.md empty (0 bytes HEAD); missing Epistemic-Role
- **AUDIT_1 error (trimmed):**
```
E   AssertionError: docs_v2/01_truth/CURRENT_RUNTIME_STATE.md
    assert 'Epistemic-Role:' in ''
```
- **Expects vs actual:** Populated epistemic markdown; file reads as empty string.
- **Why:** REAL_BUG evidence/epistemic gap (not a kernel trading defect).
- **Minimal fix:** Restore empty markdown aligned with baseline.json/bootstrap. Do not delete these tests.

### `tests/test_documentation_verification.py::test_documentation_verification_gate`

- **Classification:** **REAL_BUG**
- **One-line:** failed_gates derived_labels/freshness_baseline/operator_state_separated
- **AUDIT_1 error (trimmed):**
```
E   AssertionError: ['derived_labels', 'freshness_baseline', 'operator_state_separated']
    assert ['derived_lab...te_separated'] == []
      
      Left contains 3 more items, first extra item: 'derived_labels'
      Use -v to get more diff
```
- **Expects vs actual:** failed_gates=[]; got derived_labels + freshness_baseline(STALE) + operator_state_separated.
- **Why:** Cascading empty owner docs + stale freshness.
- **Minimal fix:** Restore docs; refresh freshness snapshot deliberately; keep gate strict.

### `tests/test_ml_base_dir.py::TestNormalizeMlBaseDir::test_build_strategy_registry_with_legacy_base_dir`

- **Classification:** **STALE_TEST**
- **One-line:** Expects MLKernelRegistry; gets MultiEngineRouterRegistry
- **AUDIT_1 error (trimmed):**
```
E   AssertionError: <tradingbot.adapters.multi_engine_router.MultiEngineRouterRegistry object at 0x000001BD5652AE10> is not an instance of <class 'tradingbot.ml.integration.ml_kernel_registry.MLKernelRegistry'>
```
- **Expects vs actual:** MLKernelRegistry under USE_ML_KERNEL=true; got MultiEngineRouterRegistry (ML shadow-gated).
- **Why:** STALE_TEST — PA-primary multi-engine router is intentional live wiring.
- **Safe update:** Assert MultiEngineRouterRegistry, or MLKernelRegistry only when router off and ML gate open.

### `tests/test_phase15b_kernel_integration.py::TestKernelAdapter::test_generate_signal_returns_trading_signal_or_none`

- **Classification:** **FLAKY_OR_ENV**
- **One-line:** pipeline_timeout in AUDIT_1; passed isolation re-run
- **AUDIT_1 error (trimmed):**
```
E   tradingbot.ml.integration.health_gate.KernelFallbackError: pipeline_timeout:672.3ms
```
- **Expects vs actual:** Adapter within latency budget; AUDIT_1 pipeline_timeout; isolation re-run passed all six.
- **Why:** FLAKY_OR_ENV (load/timing).
- **Note:** Do not delete; any budget change needs measured p95 + human sign-off.

### `tests/test_phase15b_kernel_integration.py::TestKernelAdapter::test_prediction_cache_hit`

- **Classification:** **FLAKY_OR_ENV**
- **One-line:** pipeline_timeout in AUDIT_1; passed isolation re-run
- **AUDIT_1 error (trimmed):**
```
E   tradingbot.ml.integration.health_gate.KernelFallbackError: pipeline_timeout:684.4ms
```
- **Expects vs actual:** Adapter within latency budget; AUDIT_1 pipeline_timeout; isolation re-run passed all six.
- **Why:** FLAKY_OR_ENV (load/timing).
- **Note:** Do not delete; any budget change needs measured p95 + human sign-off.

### `tests/test_phase15b_kernel_integration.py::TestKernelAdapter::test_produce_unified_signal`

- **Classification:** **FLAKY_OR_ENV**
- **One-line:** pipeline_timeout in AUDIT_1; passed isolation re-run
- **AUDIT_1 error (trimmed):**
```
E   tradingbot.ml.integration.health_gate.KernelFallbackError: pipeline_timeout:680.8ms
```
- **Expects vs actual:** Adapter within latency budget; AUDIT_1 pipeline_timeout; isolation re-run passed all six.
- **Why:** FLAKY_OR_ENV (load/timing).
- **Note:** Do not delete; any budget change needs measured p95 + human sign-off.

### `tests/test_phase15b_kernel_integration.py::TestLatency::test_adapter_latency_under_budget_cached`

- **Classification:** **FLAKY_OR_ENV**
- **One-line:** pipeline_timeout in AUDIT_1; passed isolation re-run
- **AUDIT_1 error (trimmed):**
```
E   tradingbot.ml.integration.health_gate.KernelFallbackError: pipeline_timeout:683.2ms
```
- **Expects vs actual:** Adapter within latency budget; AUDIT_1 pipeline_timeout; isolation re-run passed all six.
- **Why:** FLAKY_OR_ENV (load/timing).
- **Note:** Do not delete; any budget change needs measured p95 + human sign-off.

### `tests/test_phase15b_kernel_integration.py::TestUnifiedSignalIntegration::test_unified_validate_after_adapter`

- **Classification:** **FLAKY_OR_ENV**
- **One-line:** pipeline_timeout in AUDIT_1; passed isolation re-run
- **AUDIT_1 error (trimmed):**
```
E   tradingbot.ml.integration.health_gate.KernelFallbackError: pipeline_timeout:755.8ms
```
- **Expects vs actual:** Adapter within latency budget; AUDIT_1 pipeline_timeout; isolation re-run passed all six.
- **Why:** FLAKY_OR_ENV (load/timing).
- **Note:** Do not delete; any budget change needs measured p95 + human sign-off.

### `tests/test_phase15b_kernel_integration.py::TestExtraCoverage::test_registry_ml_success_count`

- **Classification:** **FLAKY_OR_ENV**
- **One-line:** 0 successes after timeouts; passed isolation re-run
- **AUDIT_1 error (trimmed):**
```
E   AssertionError: 0 not greater than or equal to 1
```
- **Expects vs actual:** Adapter within latency budget; AUDIT_1 pipeline_timeout; isolation re-run passed all six.
- **Why:** FLAKY_OR_ENV (load/timing).
- **Note:** Do not delete; any budget change needs measured p95 + human sign-off.

### `tests/test_phase25e_sidecar_bidask.py::TestHistoricalBidAskSearch::test_repo_search`

- **Classification:** **STALE_TEST**
- **One-line:** bidask_dataset_count=1 (Phase38 ticks); test requires 0
- **AUDIT_1 error (trimmed):**
```
E   AssertionError: 1 != 0
```
- **Expects vs actual:** bidask_dataset_count==0; actual 1 (XAUUSD_i_ticks_phase38.parquet).
- **Why:** STALE_TEST inventory drift after Phase 38 ticks.
- **Safe update:** Identify tick file; assert it must not alone complete M5 OHLC historical spread (see overclaim REAL_BUG).

### `tests/test_phase26o_legacy_docs_truth_sweep.py::TestPhase26OArtifact::test_no_proven_xauusd_equivalence_claims`

- **Classification:** **REAL_BUG**
- **One-line:** Scanner flags EV-EQ-01 NOT_PROVEN lines as equivalence claims
- **AUDIT_1 error (trimmed):**
```
E   AssertionError: Lists differ: [{'file': 'docs/PHASE106_NON_OHLC_DATA_INV[1057 chars]i.'}] != []
    
    First list contains 6 additional elements.
    First extra element 0:
    {'file': 'docs/PHASE106_NON_OHLC_DATA_INVENTORY.md', 'line': '29', 'text': 'Logical `XAUUSD` files are not treated as canonical (EV-EQ-01 NOT_PROVEN).'}
    
    Diff is 1280 characters long. Set self.maxDiff to None to see it.
```
- **Expects vs actual:** equivalence_claims==[]; got NOT_PROVEN language flagged as claims.
- **Why:** REAL_BUG tooling false positive.
- **Minimal fix:** Tighten detector; keep test.

### `tests/test_phase27_11_historical_bidask.py::TestPhase2711HistoricalBidAsk::test_repo_has_no_historical_bid_ask`

- **Classification:** **STALE_TEST**
- **One-line:** Same tick parquet makes count=1
- **AUDIT_1 error (trimmed):**
```
E   AssertionError: 1 != 0
```
- **Expects vs actual:** bidask_dataset_count==0; actual 1 (XAUUSD_i_ticks_phase38.parquet).
- **Why:** STALE_TEST inventory drift after Phase 38 ticks.
- **Safe update:** Identify tick file; assert it must not alone complete M5 OHLC historical spread (see overclaim REAL_BUG).

### `tests/test_phase27_15_cost_completeness_gate.py::TestPhase2715CostCompletenessGate::test_blocker_matrix_covers_open_components`

- **Classification:** **REAL_BUG**
- **One-line:** spread omitted from blockers after status COMPLETE
- **AUDIT_1 error (trimmed):**
```
E   AssertionError: 'spread' not found in {'symbol_binding': {'blocker': 'symbol_binding', 'evidence': 'logs/phase27_10_dataset_symbol_binding.json', 'owner': 'DATA', 'remediation': 'Bind every validation dataset with MATCH or an explicit dataset_symbol_map; do not invent EV-EQ-01', 'severity': 'HIGH', 'status': 'BLOCKED'}, 'economics': {'blocker': 'economics', 'evidence': 'logs/phase27_9_real_broker_evidence.json + stale operator specs', 'owner': 'OPERATOR', 'remediation': 'Collect fresh Real (and Demo) XAUUSD_i economics; keep stale snapshots as stale', 'severity': 'HIGH', 'status': 'PARTIAL'}, 'dataset_provenance': {'blocker': 'dataset_provenance', 'evidence': 'dataset sidecars + Phase 27.10 inventory', 'owner': 'DATA', 'remediation': 'Complete sidecar cost fields from verified evidence only', 'severity': 'HIGH', 'status': 'PARTIAL'}, 'commission': {'blocker': 'commission', 'evidence': 'logs/phase27_12_commission_evidence.json', 'owner': 'OPERATOR', 'remediation': 'Obtain an account-applicable verified commission schedule', 'severity': 'HIGH', 'status': 'BLOCKED'}, 'swap': {'blocker': 'swap', 'evidence': 'logs/phase27_13_swap_policy.json', 'owner': 'DATA', 'remediation': 'Obtain
```
- **Expects vs actual:** Spread/historical M5 still blocked/missing; collectors mark COMPLETE/True from ticks while notes say No M5 tape.
- **Why:** REAL_BUG evidence/epistemic overclaim — tests correctly refuse.
- **Minimal fix:** Fix collector classification; keep tests.

### `tests/test_phase27_15_cost_completeness_gate.py::TestPhase2715CostCompletenessGate::test_cost_ready_remains_blocked`

- **Classification:** **REAL_BUG**
- **One-line:** spread component marked COMPLETE
- **AUDIT_1 error (trimmed):**
```
E   AssertionError: 'COMPLETE' == 'COMPLETE'
```
- **Expects vs actual:** Spread/historical M5 still blocked/missing; collectors mark COMPLETE/True from ticks while notes say No M5 tape.
- **Why:** REAL_BUG evidence/epistemic overclaim — tests correctly refuse.
- **Minimal fix:** Fix collector classification; keep tests.

### `tests/test_phase27_15_cost_completeness_gate.py::TestPhase2715CostCompletenessGate::test_proxy_spread_not_historical`

- **Classification:** **REAL_BUG**
- **One-line:** expects BLOCKED; artifact COMPLETE
- **AUDIT_1 error (trimmed):**
```
E   AssertionError: 'COMPLETE' != 'BLOCKED'
    - COMPLETE
    + BLOCKED
```
- **Expects vs actual:** Spread/historical M5 still blocked/missing; collectors mark COMPLETE/True from ticks while notes say No M5 tape.
- **Why:** REAL_BUG evidence/epistemic overclaim — tests correctly refuse.
- **Minimal fix:** Fix collector classification; keep tests.

### `tests/test_phase27_16_final_validation_gate.py::TestPhase2716FinalValidationGate::test_blocker_matrix_precise`

- **Classification:** **STALE_TEST**
- **One-line:** historical_spread key absent from current matrix
- **AUDIT_1 error (trimmed):**
```
E   AssertionError: 'historical_spread' not found in {'ev_eq_01': {'blocker': 'ev_eq_01', 'evidence': 'logs/phase27_9_real_broker_evidence.json', 'explicit': 'true', 'owner': 'GATE', 'remediation': 'Record an explicit ready-qualifying status. PARTIAL/UNKNOWN/BLOCKED cannot be inferred as READY.', 'severity': 'HIGH', 'status': 'NOT_PROVEN'}, 'broker_economics': {'blocker': 'broker_economics', 'evidence': 'logs/phase27_15_cost_completeness_gate.json', 'explicit': 'true', 'owner': 'GATE', 'remediation': 'Record an explicit ready-qualifying status. PARTIAL/UNKNOWN/BLOCKED cannot be inferred as READY.', 'severity': 'HIGH', 'status': 'PARTIAL'}, 'commission': {'blocker': 'commission', 'evidence': 'logs/phase27_12_commission_evidence.json', 'explicit': 'true', 'owner': 'GATE', 'remediation': 'Record an explicit ready-qualifying status. PARTIAL/UNKNOWN/BLOCKED cannot be inferred as READY.', 'severity': 'HIGH', 'status': 'BLOCKED'}, 'swap': {'blocker': 'swap', 'evidence': 'logs/phase27_13_swap_policy.json', 'explicit': 'true', 'owner': 'GATE', 'remediation': 'Record an explicit ready-qualifying status. PARTIAL/UNKNOWN/BLOCKED cannot be inferred as READY.', 'severity': 'HIGH', 'status': 'UNK
```
- **Expects vs actual:** blocker key historical_spread present; absent in current matrix.
- **Why:** STALE_TEST schema evolution.
- **Safe update:** Align keys after confirming spread still blocked in 27.15/27.32.

### `tests/test_phase27_18_historical_bidask.py::TestPhase2718HistoricalBidAsk::test_repo_has_no_production_historical_bid_ask`

- **Classification:** **STALE_TEST**
- **One-line:** Same Phase38 tick count drift
- **AUDIT_1 error (trimmed):**
```
E   AssertionError: 1 != 0
```
- **Expects vs actual:** bidask_dataset_count==0; actual 1 (XAUUSD_i_ticks_phase38.parquet).
- **Why:** STALE_TEST inventory drift after Phase 38 ticks.
- **Safe update:** Identify tick file; assert it must not alone complete M5 OHLC historical spread (see overclaim REAL_BUG).

### `tests/test_phase27_19_commission_closure.py::TestPhase2719CommissionClosure::test_artifact_valid`

- **Classification:** **REAL_BUG**
- **One-line:** artifact status FAIL; complete_applicability_can_be_accepted=False
- **AUDIT_1 error (trimmed):**
```
E   AssertionError: 'FAIL' != 'PASS'
    - FAIL
    + PASS
```
- **Expects vs actual:** status PASS; artifact FAIL (complete_applicability_can_be_accepted=False).
- **Why:** REAL_BUG in commission applicability self-check path.
- **Minimal fix:** Repair accept/self-check; do not force PASS in the test.

### `tests/test_phase27_20_dataset_mapping_closure.py::TestPhase2720DatasetMappingClosure::test_artifact_valid`

- **Classification:** **STALE_TEST**
- **One-line:** canonical count expected 2 now 6
- **AUDIT_1 error (trimmed):**
```
E   AssertionError: 6 != 2
```
- **Expects vs actual:** canonical/direct_XAUUSD_i count 2; actual 6.
- **Why:** STALE_TEST hard-coded census.
- **Safe update:** Expect 6 or bind to phase27_27 totals; keep maps_inserted=false.

### `tests/test_phase27_21_evidence_synthesis.py::TestPhase2721EvidenceSynthesis::test_artifact_and_final_gate_blocked`

- **Classification:** **STALE_ARTIFACT**
- **One-line:** collector status FAIL vs expected PASS
- **AUDIT_1 error (trimmed):**
```
E   AssertionError: 'FAIL' != 'PASS'
    - FAIL
    + PASS
```
- **Expects vs actual:** PASS with A=PROVEN/B=BLOCKED; artifact FAIL with A/B inverted.
- **Why:** STALE_ARTIFACT — needs human re-spec then regenerate.
- **Safe update:** Update collector required_ok + tests together; regenerate JSON/MD.

### `tests/test_phase27_21_evidence_synthesis.py::TestPhase2721EvidenceSynthesis::test_spread_coverage_not_conflated`

- **Classification:** **STALE_ARTIFACT**
- **One-line:** A/B coverage inverted vs expected
- **AUDIT_1 error (trimmed):**
```
E   AssertionError: 'BLOCKED' != 'PROVEN'
    - BLOCKED
    + PROVEN
```
- **Expects vs actual:** PASS with A=PROVEN/B=BLOCKED; artifact FAIL with A/B inverted.
- **Why:** STALE_ARTIFACT — needs human re-spec then regenerate.
- **Safe update:** Update collector required_ok + tests together; regenerate JSON/MD.

### `tests/test_phase27_30_slippage_evidence.py::TestPhase2730SlippageEvidence::test_zero_pairs_are_not_identifiable`

- **Classification:** **STALE_ARTIFACT**
- **One-line:** account_type UNKNOWN vs REAL
- **AUDIT_1 error (trimmed):**
```
E   AssertionError: 'UNKNOWN' != 'REAL'
    - UNKNOWN
    + REAL
```
- **Expects vs actual:** account_type REAL; artifact UNKNOWN after offline regenerate.
- **Why:** STALE_ARTIFACT identity provenance not reattached.
- **Safe update:** Restore identity from immutable prior REAL evidence without upgrading cost completeness.

### `tests/test_phase27_31_execution_evidence.py::TestPhase2731ExecutionEvidence::test_artifact_schema_and_no_credentials`

- **Classification:** **STALE_ARTIFACT**
- **One-line:** account_type UNKNOWN vs REAL
- **AUDIT_1 error (trimmed):**
```
E   AssertionError: 'UNKNOWN' != 'REAL'
    - UNKNOWN
    + REAL
```
- **Expects vs actual:** account_type REAL; artifact UNKNOWN after offline regenerate.
- **Why:** STALE_ARTIFACT identity provenance not reattached.
- **Safe update:** Restore identity from immutable prior REAL evidence without upgrading cost completeness.

### `tests/test_phase27_32_final_cost_evidence_gate.py::TestPhase2732FinalCostEvidenceGate::test_artifact_schema_and_no_credentials`

- **Classification:** **STALE_ARTIFACT**
- **One-line:** account_type UNKNOWN vs REAL
- **AUDIT_1 error (trimmed):**
```
E   AssertionError: 'UNKNOWN' != 'REAL'
    - UNKNOWN
    + REAL
```
- **Expects vs actual:** account_type REAL; artifact UNKNOWN after offline regenerate.
- **Why:** STALE_ARTIFACT identity provenance not reattached.
- **Safe update:** Restore identity from immutable prior REAL evidence without upgrading cost completeness.

### `tests/test_phase27_32_final_cost_evidence_gate.py::TestPhase2732FinalCostEvidenceGate::test_no_component_is_complete_and_gate_blocked`

- **Classification:** **STALE_TEST**
- **One-line:** swap grade REALIZED_ZERO_NOT_PROVEN vs CURRENT_BROKER_RATE_ONLY
- **AUDIT_1 error (trimmed):**
```
E   AssertionError: 'REALIZED_ZERO_NOT_PROVEN' != 'CURRENT_BROKER_RATE_ONLY'
    - REALIZED_ZERO_NOT_PROVEN
    + CURRENT_BROKER_RATE_ONLY
```
- **Expects vs actual:** swap grade CURRENT_BROKER_RATE_ONLY; actual REALIZED_ZERO_NOT_PROVEN; gate still BLOCKED.
- **Why:** STALE_TEST label drift.
- **Safe update:** Accept new label if meaning unchanged; keep not-COMPLETE / BLOCKED asserts.

### `tests/test_phase27_33_ev_eq_resolution.py::TestPhase2733EvEqResolution::test_artifact_schema_and_no_credentials`

- **Classification:** **STALE_ARTIFACT**
- **One-line:** status FAILED from hard-coded census; account_type UNKNOWN
- **AUDIT_1 error (trimmed):**
```
E   AssertionError: 'FAILED' not found in {'PASS', 'PASS_WITH_DEFERRAL'}
```
- **Expects vs actual:** status PASS/PASS_WITH_DEFERRAL; FAILED because required_ok still demands direct_XAUUSD_i==2.
- **Why:** STALE_ARTIFACT coupled to census hard-code.
- **Safe update:** Update collector+tests census; regenerate; keep EV-EQ NOT_PROVEN / FINAL_GATE BLOCKED.

### `tests/test_phase27_33_ev_eq_resolution.py::TestPhase2733EvEqResolution::test_contract_and_inventory`

- **Classification:** **STALE_TEST**
- **One-line:** direct_XAUUSD_i expected 2 now 6
- **AUDIT_1 error (trimmed):**
```
E   AssertionError: 6 != 2
```
- **Expects vs actual:** canonical/direct_XAUUSD_i count 2; actual 6.
- **Why:** STALE_TEST hard-coded census.
- **Safe update:** Expect 6 or bind to phase27_27 totals; keep maps_inserted=false.

### `tests/test_phase27_8_policy_lock.py::TestPhase278PolicyLock::test_evidence_gaps_recorded`

- **Classification:** **REAL_BUG**
- **One-line:** historical_m5_bidask True overclaim from ticks
- **AUDIT_1 error (trimmed):**
```
E   AssertionError: True is not false
```
- **Expects vs actual:** Spread/historical M5 still blocked/missing; collectors mark COMPLETE/True from ticks while notes say No M5 tape.
- **Why:** REAL_BUG evidence/epistemic overclaim — tests correctly refuse.
- **Minimal fix:** Fix collector classification; keep tests.

### `tests/test_project_decision_baseline.py::test_canonical_entry_remains_unique`

- **Classification:** **REAL_BUG**
- **One-line:** PROJECT_DECISION_BASELINE.md empty in HEAD
- **AUDIT_1 error (trimmed):**
```
E   AssertionError: assert '**Canonical-Entry:** false' in ''
     +  where '' = _text(WindowsPath('C:/Users/AMIR/Desktop/TradingBot new/docs_v2/01_truth/PROJECT_DECISION_BASELINE.md'))
```
- **Expects vs actual:** Populated epistemic markdown; file reads as empty string.
- **Why:** REAL_BUG evidence/epistemic gap (not a kernel trading defect).
- **Minimal fix:** Restore empty markdown aligned with baseline.json/bootstrap. Do not delete these tests.

### `tests/test_project_decision_baseline.py::test_demo_real_symbol_mapping_not_automatic_contradiction`

- **Classification:** **REAL_BUG**
- **One-line:** empty baseline md
- **AUDIT_1 error (trimmed):**
```
E   AssertionError: assert ('XAUUSD_i' in '')
```
- **Expects vs actual:** Populated epistemic markdown; file reads as empty string.
- **Why:** REAL_BUG evidence/epistemic gap (not a kernel trading defect).
- **Minimal fix:** Restore empty markdown aligned with baseline.json/bootstrap. Do not delete these tests.

### `tests/test_project_decision_baseline.py::test_live_pa_ml_v41_lock`

- **Classification:** **REAL_BUG**
- **One-line:** empty baseline md
- **AUDIT_1 error (trimmed):**
```
E   AssertionError: assert 'priceaction' in ''
```
- **Expects vs actual:** Populated epistemic markdown; file reads as empty string.
- **Why:** REAL_BUG evidence/epistemic gap (not a kernel trading defect).
- **Minimal fix:** Restore empty markdown aligned with baseline.json/bootstrap. Do not delete these tests.

### `tests/test_project_decision_baseline.py::test_code_default_vs_operator_state`

- **Classification:** **REAL_BUG**
- **One-line:** empty baseline md
- **AUDIT_1 error (trimmed):**
```
E   AssertionError: assert 'CODE DEFAULT' in ''
```
- **Expects vs actual:** Populated epistemic markdown; file reads as empty string.
- **Why:** REAL_BUG evidence/epistemic gap (not a kernel trading defect).
- **Minimal fix:** Restore empty markdown aligned with baseline.json/bootstrap. Do not delete these tests.

### `tests/test_project_decision_baseline.py::test_hierarchy_and_limits`

- **Classification:** **REAL_BUG**
- **One-line:** empty baseline md
- **AUDIT_1 error (trimmed):**
```
E   AssertionError: assert 'CODE > CANONICAL DOCS' in ''
```
- **Expects vs actual:** Populated epistemic markdown; file reads as empty string.
- **Why:** REAL_BUG evidence/epistemic gap (not a kernel trading defect).
- **Minimal fix:** Restore empty markdown aligned with baseline.json/bootstrap. Do not delete these tests.

### `tests/test_project_decision_baseline.py::test_major_claims_have_evidence_references`

- **Classification:** **REAL_BUG**
- **One-line:** empty baseline md
- **AUDIT_1 error (trimmed):**
```
E   AssertionError: live.py::PRIMARY_SYMBOL
    assert 'live.py::PRIMARY_SYMBOL' in ''
```
- **Expects vs actual:** Populated epistemic markdown; file reads as empty string.
- **Why:** REAL_BUG evidence/epistemic gap (not a kernel trading defect).
- **Minimal fix:** Restore empty markdown aligned with baseline.json/bootstrap. Do not delete these tests.

## 3. Classification counts

| Classification | Count |
|----------------|------:|
| REAL_BUG | 14 |
| STALE_TEST | 8 |
| STALE_ARTIFACT | 6 |
| FLAKY_OR_ENV | 6 |
| UNCLEAR | 0 |
| **Total** | **34** |

### REAL_BUG breakdown

- Evidence/epistemic **gaps** (empty docs): 8 (owner + verification + 6 baseline)
- Evidence/epistemic **overclaim** (27.15 x3 + 27.8): 4
- Tooling false positive (26O): 1
- Commission self-check FAIL (27.19): 1
- Ordinary strategy/RiskGate code defects in this set: **0**

## 4. Integrity

- Deliverable for this phase: `docs/AUDIT_2_FAILING_TEST_TRIAGE.md`.
- No intentional production/test source fixes.
- No MT5, .env credentials, live orders, or Phase 40 tape access.


# AUDIT_1 — Baseline Test Results

**Generated (UTC):** 2026-09-09T06:46:36.527551+00:00  
**Phase:** PROJECT_AUDIT_1 (read-only cleanup audit safety net)

## Exact command used (final recorded run)

`	ext
python -m pytest --continue-on-collection-errors -q --tb=line --junitxml=logs/audit1_junit.xml --ignore-glob=tests/test_ml_phase*.py
`

Working directory: repository root (TradingBot new).

### Why not bare pytest?

1. Initial pytest -v --tb=no -q collected **7190** items with **1 collection ERROR** on an earlier snapshot; later collect-only saw **7196**.
2. Unfiltered runs stalled for 10–20+ minutes inside GIL-bound multi-day bar replay tests (observed via py-spy in live_shadow_runner / paper_engine / router research backtests). On Windows, pytest-timeout cannot interrupt code holding the GIL.
3. Final baseline therefore used --ignore-glob=tests/test_ml_phase*.py (**~222** tests not executed). See logs/_audit1_pytest_exclusions.txt.

### Earlier attempts (not the recorded baseline)

- pytest --continue-on-collection-errors -v --tb=no -q — hung in 	ests/test_ml_phase10_2_live_shadow.py::test_kernel_execution_path.
- Timeout flags (--timeout=90/120/300) — ineffective against GIL-bound pandas loops on Windows.

## Collection

| Metric | Value |
|--------|------:|
| Collect-only (no ignore) | 7196 |
| Executed under final command | 6974 (= 6910 + 34 + 30) |
| Excluded via ignore-glob | ~222 (	ests/test_ml_phase*.py) |

Note: pytest tests/test_accounting.py alone can fail collection with ModuleNotFoundError: tradingbot if the package root is not on sys.path; full-suite collection from repo root succeeds.

## Results (final command)

| Metric | Count |
|--------|------:|
| **Passed** | **6910** |
| **Failed** | **34** |
| **Skipped** | **30** |
| **Warnings** | 3945 |
| **Duration** | 6664.99s (1:51:04) |

Pytest summary line:

`	ext
34 failed, 6910 passed, 30 skipped, 3945 warnings in 6664.99s (1:51:04)
`

Artifacts:
- Console log: logs/_audit1_pytest_baseline.txt
- JUnit XML: logs/audit1_junit.xml
- Failed list: logs/_audit1_failed_tests.txt

### Failed tests (34)

- tests/test_documentation_memory_hardening_v2.py::test_owner_docs_have_epistemic_role
- tests/test_documentation_verification.py::test_documentation_verification_gate
- tests/test_ml_base_dir.py::TestNormalizeMlBaseDir::test_build_strategy_registry_with_legacy_base_dir
- tests/test_phase15b_kernel_integration.py::TestKernelAdapter::test_generate_signal_returns_trading_signal_or_none
- tests/test_phase15b_kernel_integration.py::TestKernelAdapter::test_prediction_cache_hit
- tests/test_phase15b_kernel_integration.py::TestKernelAdapter::test_produce_unified_signal
- tests/test_phase15b_kernel_integration.py::TestLatency::test_adapter_latency_under_budget_cached
- tests/test_phase15b_kernel_integration.py::TestUnifiedSignalIntegration::test_unified_validate_after_adapter
- tests/test_phase15b_kernel_integration.py::TestExtraCoverage::test_registry_ml_success_count
- tests/test_phase25e_sidecar_bidask.py::TestHistoricalBidAskSearch::test_repo_search
- tests/test_phase26o_legacy_docs_truth_sweep.py::TestPhase26OArtifact::test_no_proven_xauusd_equivalence_claims
- tests/test_phase27_11_historical_bidask.py::TestPhase2711HistoricalBidAsk::test_repo_has_no_historical_bid_ask
- tests/test_phase27_15_cost_completeness_gate.py::TestPhase2715CostCompletenessGate::test_blocker_matrix_covers_open_components
- tests/test_phase27_15_cost_completeness_gate.py::TestPhase2715CostCompletenessGate::test_cost_ready_remains_blocked
- tests/test_phase27_15_cost_completeness_gate.py::TestPhase2715CostCompletenessGate::test_proxy_spread_not_historical
- tests/test_phase27_16_final_validation_gate.py::TestPhase2716FinalValidationGate::test_blocker_matrix_precise
- tests/test_phase27_18_historical_bidask.py::TestPhase2718HistoricalBidAsk::test_repo_has_no_production_historical_bid_ask
- tests/test_phase27_19_commission_closure.py::TestPhase2719CommissionClosure::test_artifact_valid
- tests/test_phase27_20_dataset_mapping_closure.py::TestPhase2720DatasetMappingClosure::test_artifact_valid
- tests/test_phase27_21_evidence_synthesis.py::TestPhase2721EvidenceSynthesis::test_artifact_and_final_gate_blocked
- tests/test_phase27_21_evidence_synthesis.py::TestPhase2721EvidenceSynthesis::test_spread_coverage_not_conflated
- tests/test_phase27_30_slippage_evidence.py::TestPhase2730SlippageEvidence::test_zero_pairs_are_not_identifiable
- tests/test_phase27_31_execution_evidence.py::TestPhase2731ExecutionEvidence::test_artifact_schema_and_no_credentials
- tests/test_phase27_32_final_cost_evidence_gate.py::TestPhase2732FinalCostEvidenceGate::test_artifact_schema_and_no_credentials
- tests/test_phase27_32_final_cost_evidence_gate.py::TestPhase2732FinalCostEvidenceGate::test_no_component_is_complete_and_gate_blocked
- tests/test_phase27_33_ev_eq_resolution.py::TestPhase2733EvEqResolution::test_artifact_schema_and_no_credentials
- tests/test_phase27_33_ev_eq_resolution.py::TestPhase2733EvEqResolution::test_contract_and_inventory
- tests/test_phase27_8_policy_lock.py::TestPhase278PolicyLock::test_evidence_gaps_recorded
- tests/test_project_decision_baseline.py::test_canonical_entry_remains_unique
- tests/test_project_decision_baseline.py::test_demo_real_symbol_mapping_not_automatic_contradiction
- tests/test_project_decision_baseline.py::test_live_pa_ml_v41_lock - As...
- tests/test_project_decision_baseline.py::test_code_default_vs_operator_state
- tests/test_project_decision_baseline.py::test_hierarchy_and_limits - A...
- tests/test_project_decision_baseline.py::test_major_claims_have_evidence_references


## Exclusions text

`	ext
﻿AUDIT_1 pytest exclusions:
--ignore-glob=tests/test_ml_phase*.py

Reason: Phase-numbered ML integration/research tests routinely execute multi-day
bar replay / router backtests through pandas feature pipelines. Observed via py-spy
to run 10–20+ minutes per test with GIL held (pytest-timeout cannot interrupt on Windows).
Full collect count without ignore: 7196. With ignore-glob: 6974 (~222 excluded).

Also note: tests/test_accounting.py previously ERROR on isolated collection when
PYTHONPATH not set; full suite collect succeeds (tradingbot importable from root).
`

## Integrity notes

- This baseline file and docs/AUDIT_1_CLEANUP_REPORT.md are intentional audit outputs.
- Analyzer scripts live under 	ools/audit/ (explicitly allowed throwaway/audit tooling).
- Running the suite refreshed some research JSON artifacts under 	radingbot/ml/research/phase24* (pytest side-effect). This audit did not hand-edit production packages for cleanup.
- Phase 40 frozen tape was not touched.
- No MT5 connection, .env credential read, or order placement was performed for the audit analysis itself.

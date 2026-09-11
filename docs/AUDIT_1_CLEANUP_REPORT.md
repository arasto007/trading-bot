# PROJECT_AUDIT_1 — Cleanup & Consolidation Report

**Generated (UTC):** 2026-09-09T06:46:36.630357+00:00
**Phase:** REPORT ONLY — no production files modified, deleted, renamed, or moved.
**Analyzer:** `tools/audit/project_audit_1_reachability.py` (+ getenv/flag helpers under `tools/audit/`).

## 1. Test baseline summary

Full details: [docs/AUDIT_1_BASELINE_TEST_RESULTS.md](AUDIT_1_BASELINE_TEST_RESULTS.md)

| Metric | Value |
|--------|------:|
| Exact command | python -m pytest --continue-on-collection-errors -q --tb=line --junitxml=logs/audit1_junit.xml --ignore-glob=tests/test_ml_phase*.py |
| Collect-only (no ignore) | 7196 |
| Executed (with ignore-glob) | 6974 |
| Passed | 6910 |
| Failed | 34 |
| Skipped | 30 |
| Warnings | 3945 |
| Duration | 6664.99s (1:51:04) |
| Excluded (`tests/test_ml_phase*.py`) | ~222 |

Pytest summary line: 34 failed, 6910 passed, 30 skipped, 3945 warnings in 6664.99s (1:51:04).

Unfiltered pytest was attempted first but stalled in GIL-bound multi-day bar-replay tests; see baseline doc for rationale and failed-test list.

## 2. Reachability / dependency graph

### Method

- Static AST import BFS from entry points:
  - `tradingbot.__main__`, `tradingbot.application.live_runner`, `tradingbot.application.bootstrap`, `tradingbot.backtest.engine`
  - Scripts referenced by root `دستورات_اجرایی.md` and `start/*.bat`
  - All `tests/**/*.py` imports and string path/module mentions of `tradingbot|engine|scripts`
- Inventory roots: `tradingbot/`, `engine/`, `scripts/`, root-level `*.py`
- Dynamic imports (`importlib`, string `__import__`) are **not** fully resolved — may under-count REACHABLE.

### Counts

| Metric | Count |
|--------|------:|
| Inventory `.py` files scanned | 2079 |
| REACHABLE (runtime entries ∪ tests) | 1564 |
| Runtime-only REACHABLE (no tests) | 670 |
| TEST_ONLY (reachable via tests, not runtime entries) | 894 |
| UNREACHABLE | 515 |
| UNREACHABLE → DEAD_CODE | 96 |
| UNREACHABLE → RESEARCH_ARCHIVE_CANDIDATE | 419 |
| UNREACHABLE → TEST_ONLY | 0 |

Script entry refs used:

- `MODULE:tradingbot`
- `scripts/backtest_custom_range.py`
- `scripts/build_ml_dataset.py`
- `scripts/check_live_setup.py`
- `scripts/collect_ml_data.py`
- `scripts/dashboard_server.py`
- `scripts/demo_proof_status.py`
- `scripts/diagnose_autotrading.py`
- `scripts/fix_mt5_experts_ini.py`
- `scripts/live_daily_report.py`
- `scripts/morning_go_live_check.py`
- `scripts/release_mt5_ipc_lock.py`
- `scripts/run_backtest.py`
- `scripts/run_live_watchdog.py`
- `scripts/run_phase17d_bundle_promotion.py`
- `scripts/scheduled_ml_refresh.py`
- `scripts/show_meta_stats.py`
- `scripts/smoke_test_execution.py`
- `scripts/start_bot.py`
- `scripts/status_live.py`
- `scripts/status_snapshot.py`
- `scripts/train_meta_labeler.py`
- `scripts/verify_ml_live_ready.py`
- `scripts/weekend_checklist.py`

### Classification notes

- `RESEARCH_ARCHIVE_CANDIDATE`: path/name contains `phaseNN` and/or lives under `tradingbot/ml/research/` (expected historical research; not "dead" runtime).
- `DEAD_CODE`: unreachable and not phase/research-classified. **Includes operator utility scripts** that are simply not wired from the documented bat/doc entry set — human review required before deletion.
- `TEST_ONLY`: imported/mentioned by tests but not by runtime entries. Listed separately (they are in REACHABLE by Task 2 definition).

### 2.1 REACHABLE full list

_1564 files_

```
engine/__init__.py
engine/config.py
engine/logger.py
engine/strategies/__init__.py
engine/strategies/base_strategy.py
engine/strategies/price_action_strategy.py
engine/strategy_manager.py
scripts/backtest_custom_range.py
scripts/build_ml_dataset.py
scripts/check_live_setup.py
scripts/check_vol_regime_live_setup.py
scripts/collect_ml_data.py
scripts/dashboard_server.py
scripts/demo_proof_status.py
scripts/diagnose_autotrading.py
scripts/fix_mt5_experts_ini.py
scripts/generate_dashboard_live_html.py
scripts/hta_html_fragments.py
scripts/live_daily_report.py
scripts/morning_go_live_check.py
scripts/release_mt5_ipc_lock.py
scripts/run_backtest.py
scripts/run_live_watchdog.py
scripts/run_phase17d_bundle_promotion.py
scripts/scheduled_ml_refresh.py
scripts/show_meta_stats.py
scripts/smoke_test_execution.py
scripts/start_bot.py
scripts/status_live.py
scripts/status_snapshot.py
scripts/train_meta_labeler.py
scripts/verify_ml_live_ready.py
scripts/weekend_checklist.py
tradingbot/__init__.py
tradingbot/__main__.py
tradingbot/accounting/__init__.py
tradingbot/accounting/broker_constraints.py
tradingbot/accounting/engine.py
tradingbot/accounting/ledger.py
tradingbot/accounting/metrics.py
tradingbot/accounting/pnl.py
tradingbot/accounting/position_sizing.py
tradingbot/adapters/__init__.py
tradingbot/adapters/adaptive_regime_strategy_registry.py
tradingbot/adapters/background_services.py
tradingbot/adapters/indicator_engine.py
tradingbot/adapters/legacy_loader.py
tradingbot/adapters/legacy_strategy_registry.py
tradingbot/adapters/market_cache.py
tradingbot/adapters/mt5_execution.py
tradingbot/adapters/mt5_health.py
tradingbot/adapters/mt5_market_data.py
tradingbot/adapters/mt5_position_manager.py
tradingbot/adapters/mt5_utils.py
tradingbot/adapters/multi_engine_router.py
tradingbot/adapters/risk_gate.py
tradingbot/adapters/shadow_strategy_registry.py
tradingbot/adapters/stubs.py
tradingbot/adapters/symbols.py
tradingbot/adapters/timeframes.py
tradingbot/adapters/vol_regime_strategy_registry.py
tradingbot/application/__init__.py
tradingbot/application/bootstrap.py
tradingbot/application/live_runner.py
tradingbot/backtest/__init__.py
tradingbot/backtest/bidask_ingestion.py
tradingbot/backtest/bidask_validation.py
tradingbot/backtest/broker.py
tradingbot/backtest/commission_policy.py
tradingbot/backtest/config.py
tradingbot/backtest/cost_evidence_audit.py
tradingbot/backtest/cost_evidence_schema.py
tradingbot/backtest/cost_model.py
tradingbot/backtest/data_source.py
tradingbot/backtest/dataset_contract.py
tradingbot/backtest/dataset_provenance.py
tradingbot/backtest/engine.py
tradingbot/backtest/historical_bidask.py
tradingbot/backtest/htf_provider.py
tradingbot/backtest/indicators.py
tradingbot/backtest/instrument.py
tradingbot/backtest/metrics.py
tradingbot/backtest/models.py
tradingbot/backtest/mt5_readonly_evidence.py
tradingbot/backtest/operator_evidence.py
tradingbot/backtest/optimization_gate.py
tradingbot/backtest/phase100_retrace_expansion_forensics.py
tradingbot/backtest/phase101_entry_vs_exit.py
tradingbot/backtest/phase102_cluster_timing_forensics.py
tradingbot/backtest/phase103_structure_at_retracement.py
tradingbot/backtest/phase104_minimal_discriminator.py
tradingbot/backtest/phase105_discriminator_gate.py
tradingbot/backtest/phase106_non_ohlc_data_inventory.py
tradingbot/backtest/phase107_tick_intrabar_research.py
tradingbot/backtest/phase108_spread_path_research.py
tradingbot/backtest/phase109_htf_context_research.py
tradingbot/backtest/phase110_news_context_research.py
tradingbot/backtest/phase111_multisource_alignment.py
tradingbot/backtest/phase112_non_ohlc_discriminator_gate.py
tradingbot/backtest/phase113_non_ohlc_final_gate.py
tradingbot/backtest/phase114_non_ohlc_acquisition_contract.py
tradingbot/backtest/phase115_non_ohlc_data_acquisition.py
tradingbot/backtest/phase116_data_source_research.py
tradingbot/backtest/phase117_operator_source_resolution.py
tradingbot/backtest/phase25f_run.py
tradingbot/backtest/phase25g_run.py
tradingbot/backtest/phase25h_run.py
tradingbot/backtest/phase25j_run.py
tradingbot/backtest/phase25k_run.py
tradingbot/backtest/phase25l_run.py
tradingbot/backtest/phase25m_run.py
tradingbot/backtest/phase26_validation_audit.py
tradingbot/backtest/phase26b_controlled_validation.py
tradingbot/backtest/phase26c_zero_signal_audit.py
tradingbot/backtest/phase26d_kernel_signal_trace.py
tradingbot/backtest/phase26e_riskgate_audit.py
tradingbot/backtest/phase26f_riskgate_correctness.py
tradingbot/backtest/phase26g_riskgate_counterfactual.py
tradingbot/backtest/phase26h_counterfactual_consistency.py
tradingbot/backtest/phase26i_full_tail_attribution.py
tradingbot/backtest/phase26j_decision_path_reconciliation.py
tradingbot/backtest/phase26k_full_engine_reconciliation.py
tradingbot/backtest/phase26l_riskgate_policy_audit.py
tradingbot/backtest/phase26m_operator_risk_budget_audit.py
tradingbot/backtest/phase26n_documentation_contradiction_cleanup.py
tradingbot/backtest/phase26o_legacy_docs_truth_sweep.py
tradingbot/backtest/phase26p_closure_audit.py
tradingbot/backtest/phase27_10_dataset_symbol_binding.py
tradingbot/backtest/phase27_11_historical_bidask.py
tradingbot/backtest/phase27_12_commission_evidence.py
tradingbot/backtest/phase27_13_swap_policy.py
tradingbot/backtest/phase27_14_slippage_model.py
tradingbot/backtest/phase27_15_cost_completeness_gate.py
tradingbot/backtest/phase27_16_final_validation_gate.py
tradingbot/backtest/phase27_17_real_broker_evidence.py
tradingbot/backtest/phase27_18_historical_bidask.py
tradingbot/backtest/phase27_19_commission_closure.py
tradingbot/backtest/phase27_20_dataset_mapping_closure.py
tradingbot/backtest/phase27_21_evidence_synthesis.py
tradingbot/backtest/phase27_22_commission_forensic.py
tradingbot/backtest/phase27_23_bidask_expansion.py
tradingbot/backtest/phase27_24_execution_cost_forensics.py
tradingbot/backtest/phase27_25_canonical_bidask_coverage.py
tradingbot/backtest/phase27_26_canonical_bidask_coverage.py
tradingbot/backtest/phase27_27_dataset_symbol_binding.py
tradingbot/backtest/phase27_28_commission_evidence.py
tradingbot/backtest/phase27_29_swap_evidence.py
tradingbot/backtest/phase27_30_slippage_evidence.py
tradingbot/backtest/phase27_31_execution_evidence.py
tradingbot/backtest/phase27_32_final_cost_evidence_gate.py
tradingbot/backtest/phase27_33_ev_eq_resolution.py
tradingbot/backtest/phase27_5_final_broker_cost_gate.py
tradingbot/backtest/phase27_5_operator_evidence.py
tradingbot/backtest/phase27_6_final_evidence_gate.py
tradingbot/backtest/phase27_6_real_operator_evidence.py
tradingbot/backtest/phase27_7_final_blocker_closure.py
tradingbot/backtest/phase27_8_policy_lock.py
tradingbot/backtest/phase27_9_real_broker_evidence.py
tradingbot/backtest/phase27_broker_reality_audit.py
tradingbot/backtest/phase27_operator_evidence.py
tradingbot/backtest/phase28_0_performance_foundation.py
tradingbot/backtest/phase28_1_full_baseline.py
tradingbot/backtest/phase28_2_walk_forward.py
tradingbot/backtest/phase28_3_monte_carlo.py
tradingbot/backtest/phase28_4_strategy_diagnosis.py
tradingbot/backtest/phase29_research_tape.py
tradingbot/backtest/phase30_unchanged_strategy_evaluation.py
tradingbot/backtest/phase31_event_independence.py
tradingbot/backtest/phase32_walk_forward.py
tradingbot/backtest/phase33_robustness.py
tradingbot/backtest/phase34_statistical_validation.py
tradingbot/backtest/phase35_execution_reality.py
tradingbot/backtest/phase36_strategy_verdict.py
tradingbot/backtest/phase37_long_horizon_tape.py
tradingbot/backtest/phase38_intelligent_evidence_acquisition.py
tradingbot/backtest/phase39_broker_economics_execution.py
tradingbot/backtest/phase40_full_horizon_validation.py
tradingbot/backtest/phase41_final_evidence_closure.py
tradingbot/backtest/phase42_broker_cost_execution_closure.py
tradingbot/backtest/phase42_cost_reconstruction.py
tradingbot/backtest/phase43_broker_cost_execution_validation.py
tradingbot/backtest/phase44_executable_backtest_readiness.py
tradingbot/backtest/phase45_event_oos_regime_robustness.py
tradingbot/backtest/phase46_production_live_parity_audit.py
tradingbot/backtest/phase47_blocker_closure.py
tradingbot/backtest/phase48_executable_backtest.py
tradingbot/backtest/phase49_final_event_oos_validation.py
tradingbot/backtest/phase50_final_production_parity.py
tradingbot/backtest/phase51_final_evidence_closure.py
tradingbot/backtest/phase52_optimization_gate.py
tradingbot/backtest/phase53_shadow_readiness.py
tradingbot/backtest/phase54_account_broker_evidence.py
tradingbot/backtest/phase55_cost_scenario_analysis.py
tradingbot/backtest/phase56_symbol_mapping_final_gate.py
tradingbot/backtest/phase57_account_product_forensics.py
tradingbot/backtest/phase58_commission_accountability.py
tradingbot/backtest/phase59_symbol_equivalence_forensics.py
tradingbot/backtest/phase60_unified_evidence_gate.py
tradingbot/backtest/phase61_edge_survival_forensics.py
tradingbot/backtest/phase62_operator_action_economics.py
tradingbot/backtest/phase63_next_step_gate.py
tradingbot/backtest/phase64_strategy_event_forensics.py
tradingbot/backtest/phase65_diagnostic_experiments.py
tradingbot/backtest/phase66_strategy_root_cause.py
tradingbot/backtest/phase67_next_research_gate.py
tradingbot/backtest/phase68_exit_forensics.py
tradingbot/backtest/phase69_exit_geometry.py
tradingbot/backtest/phase70_exit_counterfactuals.py
tradingbot/backtest/phase71_extreme_winner_forensics.py
tradingbot/backtest/phase72_exit_root_cause.py
tradingbot/backtest/phase73_exit_research_gate.py
tradingbot/backtest/phase74_profit_giveback_forensics.py
tradingbot/backtest/phase75_exit_counterfactuals.py
tradingbot/backtest/phase76_sl_vs_profit_protection.py
tradingbot/backtest/phase77_exit_geometry_forensics.py
tradingbot/backtest/phase78_time_exit_forensics.py
tradingbot/backtest/phase79_exit_side_regime.py
tradingbot/backtest/phase80_extreme_winner_audit.py
tradingbot/backtest/phase81_exit_research_gate.py
tradingbot/backtest/phase82_profit_protection_design.py
tradingbot/backtest/phase83_profit_protection_counterfactuals.py
tradingbot/backtest/phase84_tail_preservation.py
tradingbot/backtest/phase85_rescue_vs_destruction.py
tradingbot/backtest/phase86_profit_protection_oos.py
tradingbot/backtest/phase87_profit_protection_interactions.py
tradingbot/backtest/phase88_exit_design_spec.py
tradingbot/backtest/phase89_profit_protection_gate.py
tradingbot/backtest/phase90_profit_giveback_path_forensics.py
tradingbot/backtest/phase91_reversal_timing_forensics.py
tradingbot/backtest/phase92_mfe_mae_conditional_forensics.py
tradingbot/backtest/phase93_tail_preservation_forensics.py
tradingbot/backtest/phase94_cluster_forensics.py
tradingbot/backtest/phase95_protection_family_v2.py
tradingbot/backtest/phase96_protection_robustness_gate.py
tradingbot/backtest/phase97_profit_protection_final_gate.py
tradingbot/backtest/phase98_first_favorable_state.py
tradingbot/backtest/phase99_path_velocity_persistence.py
tradingbot/backtest/position_manager.py
tradingbot/backtest/request_fill_telemetry.py
tradingbot/backtest/risk.py
tradingbot/backtest/shadow_observation.py
tradingbot/backtest/slippage_policy.py
tradingbot/backtest/swap_policy.py
tradingbot/backtest/symbol_equivalence.py
tradingbot/config/__init__.py
tradingbot/config/dotenv_loader.py
tradingbot/config/engine_settings.py
tradingbot/config/legacy_settings.py
tradingbot/config/live.py
tradingbot/config/pa_symbol_tf_presets.py
tradingbot/config/price_action.py
tradingbot/config/prop_presets.py
tradingbot/config/settings.py
tradingbot/config/strategies.py
tradingbot/domain/__init__.py
tradingbot/domain/broker_economics.py
tradingbot/domain/enums.py
tradingbot/domain/filter_policy.py
tradingbot/domain/gold_strategies/__init__.py
tradingbot/domain/gold_strategies/h4_swing.py
tradingbot/domain/gold_strategies/m15_intraday.py
tradingbot/domain/gold_strategies/m5_london_sweep.py
tradingbot/domain/gold_strategies/m5_scalp.py
tradingbot/domain/gold_strategies/router.py
tradingbot/domain/htf_bias.py
tradingbot/domain/live_gates.py
tradingbot/domain/market_filters.py
tradingbot/domain/models.py
tradingbot/domain/news_logic.py
tradingbot/domain/ohlcv.py
tradingbot/domain/order_logic.py
tradingbot/domain/pa_hardening.py
tradingbot/domain/position_logic.py
tradingbot/domain/position_preset.py
tradingbot/domain/price_action.py
tradingbot/domain/professional_pm.py
tradingbot/domain/risk_logic.py
tradingbot/domain/session_logic.py
tradingbot/domain/signal_helpers.py
tradingbot/domain/trade_features.py
tradingbot/execution/__init__.py
tradingbot/execution/execution_costs.py
tradingbot/execution/execution_latency.py
tradingbot/execution/execution_models.py
tradingbot/execution/execution_simulator.py
tradingbot/execution/fill_model.py
tradingbot/execution/liquidity_model.py
tradingbot/execution/market_impact.py
tradingbot/execution/order_queue.py
tradingbot/infra/__init__.py
tradingbot/infra/logging.py
tradingbot/kernel/__init__.py
tradingbot/kernel/trading_kernel.py
tradingbot/ml/__init__.py
tradingbot/ml/abtest/__init__.py
tradingbot/ml/abtest/comparator.py
tradingbot/ml/abtest/logger.py
tradingbot/ml/abtest/metrics.py
tradingbot/ml/abtest/report.py
tradingbot/ml/abtest/schema.py
tradingbot/ml/audit/phase12_1/__init__.py
tradingbot/ml/audit/phase12_1/contribution_analyzer.py
tradingbot/ml/audit/phase12_1/dependency_analyzer.py
tradingbot/ml/audit/phase12_1/regime_strategy_analysis.py
tradingbot/ml/audit/phase12_1/replay_analyzer.py
tradingbot/ml/audit/phase12_1/report_generator.py
tradingbot/ml/audit/phase12_1/signal_tracer.py
tradingbot/ml/audit/phase12_1/strategy_discovery.py
tradingbot/ml/backtest/__init__.py
tradingbot/ml/backtest/broker_sim.py
tradingbot/ml/backtest/broker_simulator.py
tradingbot/ml/backtest/engine.py
tradingbot/ml/backtest/metrics.py
tradingbot/ml/backtest/model_loader.py
tradingbot/ml/backtest/phase97_engine.py
tradingbot/ml/backtest/report.py
tradingbot/ml/backtest/risk.py
tradingbot/ml/backtest/state.py
tradingbot/ml/backtest/strategy.py
tradingbot/ml/backtest/trade_state.py
tradingbot/ml/confidence_engine/__init__.py
tradingbot/ml/confidence_engine/calibration_policy.py
tradingbot/ml/confidence_engine/calibration_trace.py
tradingbot/ml/confidence_engine/calibration_types.py
tradingbot/ml/confidence_engine/calibrator.py
tradingbot/ml/confidence_engine/engine_calibrator.py
tradingbot/ml/confidence_engine/regime_calibrator.py
tradingbot/ml/confidence_engine/session_adjuster.py
tradingbot/ml/confidence_engine/validator.py
tradingbot/ml/confidence_engine/volatility_adjuster.py
tradingbot/ml/confidence_mapping/__init__.py
tradingbot/ml/confidence_mapping/confidence_mapper.py
tradingbot/ml/confidence_mapping/config.py
tradingbot/ml/confidence_mapping/equivalence_solver.py
tradingbot/ml/confidence_mapping/mapping_curve.py
tradingbot/ml/confidence_mapping/mapping_trace.py
tradingbot/ml/confidence_mapping/mapping_types.py
tradingbot/ml/confidence_mapping/mapping_validator.py
tradingbot/ml/confidence_mapping/orchestrator.py
tradingbot/ml/confidence_mapping/production_adapter.py
tradingbot/ml/confidence_mapping/production_replay.py
tradingbot/ml/confidence_mapping/report_generator.py
tradingbot/ml/confidence_mapping/research_parity.py
tradingbot/ml/confidence_mapping/safety_audit.py
tradingbot/ml/confidence_mapping/validator.py
tradingbot/ml/data/__init__.py
tradingbot/ml/data/collection_manifest.py
tradingbot/ml/data/collection_validation.py
tradingbot/ml/data/historical_collection_report.py
tradingbot/ml/data/historical_fetcher.py
tradingbot/ml/data/historical_quality_validator.py
tradingbot/ml/data/market_event_extractor.py
tradingbot/ml/data/metadata.py
tradingbot/ml/data/mt5_fetch.py
tradingbot/ml/data/news_calendar.py
tradingbot/ml/data/optimized_fetcher.py
tradingbot/ml/data/paths.py
tradingbot/ml/data/pipeline.py
tradingbot/ml/data/pipeline_report.py
tradingbot/ml/data/quality/__init__.py
tradingbot/ml/data/quality/anomaly_detector.py
tradingbot/ml/data/quality/candle_validator.py
tradingbot/ml/data/quality/gap_detector.py
tradingbot/ml/data/quality/report.py
tradingbot/ml/data/quality/tick_validator.py
tradingbot/ml/data/raw_fingerprint.py
tradingbot/ml/data/roles.py
tradingbot/ml/data/schema.py
tradingbot/ml/data/session_utils.py
tradingbot/ml/data/stores/__init__.py
tradingbot/ml/data/stores/candle_store.py
tradingbot/ml/data/stores/event_store.py
tradingbot/ml/data/stores/session_store.py
tradingbot/ml/data/stores/spread_store.py
tradingbot/ml/data/stores/tick_store.py
tradingbot/ml/dataset/__init__.py
tradingbot/ml/dataset/builder.py
tradingbot/ml/dataset/deep_audit.py
tradingbot/ml/dataset/feature_analysis.py
tradingbot/ml/dataset/fingerprint.py
tradingbot/ml/dataset/hardening.py
tradingbot/ml/dataset/label_analysis.py
tradingbot/ml/dataset/label_quality.py
tradingbot/ml/dataset/label_research.py
tradingbot/ml/dataset/labels.py
tradingbot/ml/dataset/leakage_report.py
tradingbot/ml/dataset/memory_cache.py
tradingbot/ml/dataset/phase9_production_build.py
tradingbot/ml/dataset/preflight.py
tradingbot/ml/dataset/production_builder.py
tradingbot/ml/dataset/production_dataset_v2.py
tradingbot/ml/dataset/regime_analysis.py
tradingbot/ml/dataset/release_manager.py
tradingbot/ml/dataset/report.py
tradingbot/ml/dataset/research_audit.py
tradingbot/ml/dataset/sanity_gate.py
tradingbot/ml/dataset/schema.py
tradingbot/ml/dataset/session_analysis.py
tradingbot/ml/dataset/sparse_event_builder.py
tradingbot/ml/dataset/splitter.py
tradingbot/ml/dataset/statistics.py
tradingbot/ml/dataset/store.py
tradingbot/ml/dataset/train_readiness_report.py
tradingbot/ml/dataset/validation.py
tradingbot/ml/decision/__init__.py
tradingbot/ml/decision/confidence.py
tradingbot/ml/decision/explain.py
tradingbot/ml/decision/logger.py
tradingbot/ml/decision/policy.py
tradingbot/ml/decision/predictor.py
tradingbot/ml/decision/schema.py
tradingbot/ml/decision/shadow.py
tradingbot/ml/decision_engine/__init__.py
tradingbot/ml/decision_engine/confidence_engine.py
tradingbot/ml/decision_engine/decision_policy.py
tradingbot/ml/decision_engine/decision_trace.py
tradingbot/ml/decision_engine/decision_types.py
tradingbot/ml/decision_engine/orchestrator.py
tradingbot/ml/decision_engine/strategy_selector.py
tradingbot/ml/decision_engine/validation.py
tradingbot/ml/decision_engine/vol_regime_branch.py
tradingbot/ml/deployment/__init__.py
tradingbot/ml/deployment/deployment_policy.py
tradingbot/ml/deployment/kill_switch.py
tradingbot/ml/deployment/live_readiness_engine.py
tradingbot/ml/deployment/logger.py
tradingbot/ml/deployment/readiness_scoring.py
tradingbot/ml/deployment/risk_gates.py
tradingbot/ml/deployment/schema.py
tradingbot/ml/deployment/shadow_validation.py
tradingbot/ml/deployment/stability_checker.py
tradingbot/ml/feature_alignment/__init__.py
tradingbot/ml/feature_alignment/alignment_trace.py
tradingbot/ml/feature_alignment/config.py
tradingbot/ml/feature_alignment/distribution_aligner.py
tradingbot/ml/feature_alignment/factory.py
tradingbot/ml/feature_alignment/feature_statistics.py
tradingbot/ml/feature_alignment/orchestrator.py
tradingbot/ml/feature_alignment/quantile_mapper.py
tradingbot/ml/feature_alignment/validator.py
tradingbot/ml/features/__init__.py
tradingbot/ml/features/align.py
tradingbot/ml/features/base.py
tradingbot/ml/features/builder.py
tradingbot/ml/features/quality/__init__.py
tradingbot/ml/features/quality/feature_report.py
tradingbot/ml/features/quality/feature_validator.py
tradingbot/ml/features/registry/__init__.py
tradingbot/ml/features/registry/enrichment.py
tradingbot/ml/features/registry/registry.py
tradingbot/ml/features/reproducibility.py
tradingbot/ml/features/scaling.py
tradingbot/ml/features/store.py
tradingbot/ml/features/unified_feature_store.py
tradingbot/ml/hybrid/__init__.py
tradingbot/ml/hybrid/config.py
tradingbot/ml/hybrid/conflict.py
tradingbot/ml/hybrid/engine.py
tradingbot/ml/hybrid/explain.py
tradingbot/ml/hybrid/logger.py
tradingbot/ml/hybrid/ml_adapter.py
tradingbot/ml/hybrid/rules_adapter.py
tradingbot/ml/hybrid/schema.py
tradingbot/ml/hybrid/scoring.py
tradingbot/ml/improvement/__init__.py
tradingbot/ml/improvement/analyzer.py
tradingbot/ml/improvement/experiment_queue.py
tradingbot/ml/improvement/feature_optimizer.py
tradingbot/ml/improvement/model_optimizer.py
tradingbot/ml/improvement/recommendation.py
tradingbot/ml/improvement/regime_optimizer.py
tradingbot/ml/improvement/reports.py
tradingbot/ml/improvement/schema.py
tradingbot/ml/improvement/threshold_optimizer.py
tradingbot/ml/infrastructure/__init__.py
tradingbot/ml/infrastructure/audit/__init__.py
tradingbot/ml/infrastructure/audit/audit_logger.py
tradingbot/ml/infrastructure/config/__init__.py
tradingbot/ml/infrastructure/config/runtime_config.py
tradingbot/ml/infrastructure/diagnostics/__init__.py
tradingbot/ml/infrastructure/diagnostics/diagnostic_report.py
tradingbot/ml/infrastructure/health/__init__.py
tradingbot/ml/infrastructure/health/health_checker.py
tradingbot/ml/infrastructure/health/schema.py
tradingbot/ml/infrastructure/recovery/__init__.py
tradingbot/ml/infrastructure/recovery/recovery_manager.py
tradingbot/ml/infrastructure/versioning/__init__.py
tradingbot/ml/infrastructure/versioning/model_version.py
tradingbot/ml/integration/__init__.py
tradingbot/ml/integration/composite_registry.py
tradingbot/ml/integration/config.py
tradingbot/ml/integration/error_audit/__init__.py
tradingbot/ml/integration/error_audit/error_report.py
tradingbot/ml/integration/error_audit/kernel_error_analyzer.py
tradingbot/ml/integration/error_audit/recovery_manager.py
tradingbot/ml/integration/error_audit/shadow_health_check.py
tradingbot/ml/integration/factory.py
tradingbot/ml/integration/health_gate.py
tradingbot/ml/integration/kernel_adapter.py
tradingbot/ml/integration/kernel_builder.py
tradingbot/ml/integration/kernel_run_logger.py
tradingbot/ml/integration/kernel_shadow_runner.py
tradingbot/ml/integration/live_market_adapter.py
tradingbot/ml/integration/live_metrics.py
tradingbot/ml/integration/live_preflight.py
tradingbot/ml/integration/live_run_logger.py
tradingbot/ml/integration/live_shadow_runner.py
tradingbot/ml/integration/ml_kernel_registry.py
tradingbot/ml/integration/ml_strategy.py
tradingbot/ml/integration/monitoring.py
tradingbot/ml/integration/phase15b_orchestrator.py
tradingbot/ml/integration/pipeline_cache.py
tradingbot/ml/integration/recovered_calibration.py
tradingbot/ml/integration/regime_filter_profiles.py
tradingbot/ml/integration/replay_market_data.py
tradingbot/ml/integration/replay_validator.py
tradingbot/ml/integration/shadow_execution_guard.py
tradingbot/ml/integration/signal_mapper.py
tradingbot/ml/integration/sl_tp_calculator.py
tradingbot/ml/integration/startup_diagnostics.py
tradingbot/ml/integration/timeout_diagnostics.py
tradingbot/ml/integration/trade_integrity.py
tradingbot/ml/integration/trade_integrity_logger.py
tradingbot/ml/integration/virtual_trade_builder.py
tradingbot/ml/live_gate/__init__.py
tradingbot/ml/live_gate/gate_engine.py
tradingbot/ml/live_gate/logger.py
tradingbot/ml/live_gate/safety_guard.py
tradingbot/ml/live_gate/schema.py
tradingbot/ml/live_gate/shadow_router.py
tradingbot/ml/live_pilot/__init__.py
tradingbot/ml/live_pilot/config.py
tradingbot/ml/live_pilot/execution_guard.py
tradingbot/ml/live_pilot/health_check.py
tradingbot/ml/live_pilot/kill_switch.py
tradingbot/ml/live_pilot/latency_tracker.py
tradingbot/ml/live_pilot/live_controller.py
tradingbot/ml/live_pilot/live_monitor.py
tradingbot/ml/live_pilot/position_limiter.py
tradingbot/ml/live_pilot/safety_manager.py
tradingbot/ml/live_pilot/slippage_tracker.py
tradingbot/ml/live_pilot/trade_journal.py
tradingbot/ml/live_validation/__init__.py
tradingbot/ml/live_validation/config.py
tradingbot/ml/live_validation/decision_compare.py
tradingbot/ml/live_validation/latency_monitor.py
tradingbot/ml/live_validation/live_health.py
tradingbot/ml/live_validation/orchestrator.py
tradingbot/ml/live_validation/report_generator.py
tradingbot/ml/live_validation/risk_compare.py
tradingbot/ml/live_validation/shadow_equity.py
tradingbot/ml/live_validation/shadow_mode.py
tradingbot/ml/live_validation/shadow_statistics.py
tradingbot/ml/live_validation/shadow_trade.py
tradingbot/ml/live_validation/signal_consistency.py
tradingbot/ml/live_validation/validator.py
tradingbot/ml/memory/__init__.py
tradingbot/ml/memory/calibration.py
tradingbot/ml/memory/evaluator.py
tradingbot/ml/memory/outcome.py
tradingbot/ml/memory/performance.py
tradingbot/ml/memory/reports.py
tradingbot/ml/memory/schema.py
tradingbot/ml/memory/store.py
tradingbot/ml/models/__init__.py
tradingbot/ml/models/artifacts.py
tradingbot/ml/models/base.py
tradingbot/ml/models/dataset_loader.py
tradingbot/ml/models/evaluator.py
tradingbot/ml/models/lightgbm_model.py
tradingbot/ml/models/logistic_model.py
tradingbot/ml/models/registry.py
tradingbot/ml/models/training.py
tradingbot/ml/models/xgboost_model.py
tradingbot/ml/monitoring/__init__.py
tradingbot/ml/monitoring/alerts.py
tradingbot/ml/monitoring/anomaly_detector.py
tradingbot/ml/monitoring/bundle_monitor.py
tradingbot/ml/monitoring/config.py
tradingbot/ml/monitoring/dashboard_data.py
tradingbot/ml/monitoring/dashboard_export.py
tradingbot/ml/monitoring/decision_logger.py
tradingbot/ml/monitoring/degradation.py
tradingbot/ml/monitoring/drift.py
tradingbot/ml/monitoring/engine_monitor.py
tradingbot/ml/monitoring/fallback_monitor.py
tradingbot/ml/monitoring/health.py
tradingbot/ml/monitoring/health_monitor.py
tradingbot/ml/monitoring/latency_monitor.py
tradingbot/ml/monitoring/long_run_manager.py
tradingbot/ml/monitoring/observer.py
tradingbot/ml/monitoring/orchestrator.py
tradingbot/ml/monitoring/performance_monitor.py
tradingbot/ml/monitoring/performance_tracker.py
tradingbot/ml/monitoring/prediction_monitor.py
tradingbot/ml/monitoring/reports.py
tradingbot/ml/monitoring/schema.py
tradingbot/ml/monitoring/session_report.py
tradingbot/ml/monitoring/shadow_monitor.py
tradingbot/ml/monitoring/stability_analyzer.py
tradingbot/ml/monitoring/statistics.py
tradingbot/ml/optimization/__init__.py
tradingbot/ml/optimization/_sim.py
tradingbot/ml/optimization/filters.py
tradingbot/ml/optimization/optimizer.py
tradingbot/ml/optimization/recommendation.py
tradingbot/ml/optimization/reports.py
tradingbot/ml/optimization/schema.py
tradingbot/ml/optimization/threshold.py
tradingbot/ml/optimization/weights.py
tradingbot/ml/orchestrator/__init__.py
tradingbot/ml/orchestrator/confidence_router.py
tradingbot/ml/orchestrator/decision_engine.py
tradingbot/ml/orchestrator/ensemble.py
tradingbot/ml/orchestrator/explain.py
tradingbot/ml/orchestrator/logger.py
tradingbot/ml/orchestrator/regime_gate.py
tradingbot/ml/orchestrator/risk_adjustment.py
tradingbot/ml/orchestrator/schema.py
tradingbot/ml/orchestrator/signals.py
tradingbot/ml/orchestrator/strategy_selector.py
tradingbot/ml/paper/__init__.py
tradingbot/ml/paper/_types.py
tradingbot/ml/paper/broker_sim.py
tradingbot/ml/paper/config.py
tradingbot/ml/paper/daily_report.py
tradingbot/ml/paper/engine.py
tradingbot/ml/paper/latency_model.py
tradingbot/ml/paper/metrics.py
tradingbot/ml/paper/paper_engine.py
tradingbot/ml/paper/paper_execution.py
tradingbot/ml/paper/performance.py
tradingbot/ml/paper/portfolio.py
tradingbot/ml/paper/portfolio_manager.py
tradingbot/ml/paper/session_analyzer.py
tradingbot/ml/paper/slippage_model.py
tradingbot/ml/paper/spread_model.py
tradingbot/ml/paper/trade_executor.py
tradingbot/ml/paper/trade_lifecycle.py
tradingbot/ml/paper/virtual_account.py
tradingbot/ml/paper/walk_forward_runner.py
tradingbot/ml/paper_trading/__init__.py
tradingbot/ml/paper_trading/market_stream.py
tradingbot/ml/paper_trading/model_registry.py
tradingbot/ml/paper_trading/paper_broker.py
tradingbot/ml/paper_trading/performance_tracker.py
tradingbot/ml/paper_trading/position_manager.py
tradingbot/ml/paper_trading/report.py
tradingbot/ml/paper_trading/shadow_engine.py
tradingbot/ml/paper_trading/signal_engine.py
tradingbot/ml/performance/__init__.py
tradingbot/ml/performance/benchmark.py
tradingbot/ml/performance/memory.py
tradingbot/ml/performance/optimization.py
tradingbot/ml/performance/profiler.py
tradingbot/ml/performance/report.py
tradingbot/ml/performance/schema.py
tradingbot/ml/performance/stress_latency.py
tradingbot/ml/phase15a/__init__.py
tradingbot/ml/phase15a/checklist.py
tradingbot/ml/phase15a/config.py
tradingbot/ml/phase15a/engine_discovery.py
tradingbot/ml/phase15a/engine_registry.py
tradingbot/ml/phase15a/health_check.py
tradingbot/ml/phase15a/interfaces.py
tradingbot/ml/phase15a/orchestrator.py
tradingbot/ml/phase15a/pipeline_validator.py
tradingbot/ml/phase15a/report_generator.py
tradingbot/ml/phase15a/trend_bundle.py
tradingbot/ml/phase15a/unified_signal.py
tradingbot/ml/phase15e_debug/__init__.py
tradingbot/ml/phase15e_debug/confidence_analysis.py
tradingbot/ml/phase15e_debug/config.py
tradingbot/ml/phase15e_debug/legacy_diff.py
tradingbot/ml/phase15e_debug/orchestrator.py
tradingbot/ml/phase15e_debug/regime_analysis.py
tradingbot/ml/phase15e_debug/report_generator.py
tradingbot/ml/phase15e_debug/root_cause.py
tradingbot/ml/phase15e_debug/signal_funnel.py
tradingbot/ml/phase15e_debug/stage_probe.py
tradingbot/ml/phase15f/__init__.py
tradingbot/ml/phase15f/bundle_audit.py
tradingbot/ml/phase15f/confidence_trace.py
tradingbot/ml/phase15f/config.py
tradingbot/ml/phase15f/decision_policy_audit.py
tradingbot/ml/phase15f/orchestrator.py
tradingbot/ml/phase15f/pipeline_compare.py
tradingbot/ml/phase15f/recovery_validator.py
tradingbot/ml/phase15f/report_generator.py
tradingbot/ml/phase17d/__init__.py
tradingbot/ml/phase17d/bundle_freeze.py
tradingbot/ml/phase17d/compatibility.py
tradingbot/ml/phase17d/config.py
tradingbot/ml/phase17d/health.py
tradingbot/ml/phase17d/live_safety.py
tradingbot/ml/phase17d/orchestrator.py
tradingbot/ml/phase17d/regression.py
tradingbot/ml/phase17d/rollback.py
tradingbot/ml/phase17d/v41_engine.py
tradingbot/ml/phase17d/verdict.py
tradingbot/ml/phase17d/versioning.py
tradingbot/ml/phase18b/__init__.py
tradingbot/ml/phase18b/checklist.py
tradingbot/ml/phase18b/config.py
tradingbot/ml/phase18b/failure_injection.py
tradingbot/ml/phase18b/health.py
tradingbot/ml/phase18b/live_safety.py
tradingbot/ml/phase18b/operational.py
tradingbot/ml/phase18b/orchestrator.py
tradingbot/ml/phase18b/production_audit.py
tradingbot/ml/phase18b/rollback.py
tradingbot/ml/phase18b/stability.py
tradingbot/ml/phase18b/verdict.py
tradingbot/ml/phase18c/__init__.py
tradingbot/ml/phase18c/bundles.py
tradingbot/ml/phase18c/checklist.py
tradingbot/ml/phase18c/config.py
tradingbot/ml/phase18c/configuration.py
tradingbot/ml/phase18c/engines.py
tradingbot/ml/phase18c/environment.py
tradingbot/ml/phase18c/mt5_check.py
tradingbot/ml/phase18c/orchestrator.py
tradingbot/ml/phase18c/shutdown.py
tradingbot/ml/phase18c/startup.py
tradingbot/ml/phase18c/verdict.py
tradingbot/ml/phase19a/__init__.py
tradingbot/ml/phase19a/backtest.py
tradingbot/ml/phase19a/capital.py
tradingbot/ml/phase19a/config.py
tradingbot/ml/phase19a/drawdown.py
tradingbot/ml/phase19a/metrics.py
tradingbot/ml/phase19a/orchestrator.py
tradingbot/ml/phase19a/regime_analysis.py
tradingbot/ml/phase19a/robustness.py
tradingbot/ml/phase19a/scoring.py
tradingbot/ml/phase19a/symbol_analysis.py
tradingbot/ml/phase19a/trade_quality.py
tradingbot/ml/phase19a/verdict.py
tradingbot/ml/phase19c/__init__.py
tradingbot/ml/phase19c/backtest.py
tradingbot/ml/phase19c/config.py
tradingbot/ml/phase19c/filters.py
tradingbot/ml/phase19c/montecarlo.py
tradingbot/ml/phase19c/rollback.py
tradingbot/ml/phase19c/verdict.py
tradingbot/ml/phase19c/walkforward.py
tradingbot/ml/phase19d/__init__.py
tradingbot/ml/phase19d/audit.py
tradingbot/ml/phase19d/capital.py
tradingbot/ml/phase19d/certification.py
tradingbot/ml/phase19d/config.py
tradingbot/ml/phase19d/deployment.py
tradingbot/ml/phase19d/live_safety.py
tradingbot/ml/phase19d/montecarlo.py
tradingbot/ml/phase19d/orchestrator.py
tradingbot/ml/phase19d/scoring.py
tradingbot/ml/phase19d/stress_test.py
tradingbot/ml/phase19d/verdict.py
tradingbot/ml/phase19d/walkforward.py
tradingbot/ml/phase20a/__init__.py
tradingbot/ml/phase20a/certification_gate.py
tradingbot/ml/phase20a/config.py
tradingbot/ml/phase20a/deployment_runner.py
tradingbot/ml/phase20a/execution_guard.py
tradingbot/ml/phase20a/kernel_observer.py
tradingbot/ml/phase20a/orchestrator.py
tradingbot/ml/phase20a/reporter.py
tradingbot/ml/phase20a/rollback.py
tradingbot/ml/phase20a/safety_monitor.py
tradingbot/ml/phase20a/strategy_registry.py
tradingbot/ml/phase20b/__init__.py
tradingbot/ml/phase20b/capital.py
tradingbot/ml/phase20b/config.py
tradingbot/ml/phase20b/drawdown.py
tradingbot/ml/phase20b/execution.py
tradingbot/ml/phase20b/filters.py
tradingbot/ml/phase20b/health.py
tradingbot/ml/phase20b/live_data.py
tradingbot/ml/phase20b/orchestrator.py
tradingbot/ml/phase20b/performance.py
tradingbot/ml/phase20b/risk_suggestions.py
tradingbot/ml/phase20b/trade_quality.py
tradingbot/ml/phase20b/verdict.py
tradingbot/ml/phase20c/__init__.py
tradingbot/ml/phase20c/broker_data.py
tradingbot/ml/phase20c/broker_quality.py
tradingbot/ml/phase20c/config.py
tradingbot/ml/phase20c/execution_audit.py
tradingbot/ml/phase20c/latency.py
tradingbot/ml/phase20c/orchestrator.py
tradingbot/ml/phase20c/risk_validation.py
tradingbot/ml/phase20c/scoring.py
tradingbot/ml/phase20c/simulation_compare.py
tradingbot/ml/phase20c/slippage.py
tradingbot/ml/phase20c/spread.py
tradingbot/ml/phase20c/stability.py
tradingbot/ml/phase20c/verdict.py
tradingbot/ml/research/__init__.py
tradingbot/ml/research/advanced_discovery/__init__.py
tradingbot/ml/research/advanced_discovery/experiment_runner.py
tradingbot/ml/research/advanced_discovery/experimental_features.py
tradingbot/ml/research/advanced_discovery/feature_discovery.py
tradingbot/ml/research/advanced_discovery/label_discovery.py
tradingbot/ml/research/advanced_discovery/model_discovery.py
tradingbot/ml/research/advanced_discovery/signal_mining.py
tradingbot/ml/research/documentation_consistency/__init__.py
tradingbot/ml/research/documentation_consistency/run.py
tradingbot/ml/research/documentation_consistency/scanner.py
tradingbot/ml/research/documentation_freshness/__init__.py
tradingbot/ml/research/documentation_freshness/scanner.py
tradingbot/ml/research/documentation_memory_hardening/__init__.py
tradingbot/ml/research/documentation_memory_hardening/baseline.py
tradingbot/ml/research/documentation_memory_hardening/memory_integrity.py
tradingbot/ml/research/documentation_memory_hardening_v2/__init__.py
tradingbot/ml/research/documentation_memory_hardening_v2/load_path.py
tradingbot/ml/research/documentation_memory_hardening_v2/run.py
tradingbot/ml/research/documentation_operationalization/run.py
tradingbot/ml/research/documentation_system_audit/__init__.py
tradingbot/ml/research/documentation_system_audit/run.py
tradingbot/ml/research/documentation_verification/run.py
tradingbot/ml/research/experiment_runner.py
tradingbot/ml/research/experiment_tracker.py
tradingbot/ml/research/feature_importance_analysis.py
tradingbot/ml/research/feature_research.py
tradingbot/ml/research/full_repo_audit/run.py
tradingbot/ml/research/hypothesis.py
tradingbot/ml/research/label_experiment.py
tradingbot/ml/research/live_l2/__init__.py
tradingbot/ml/research/live_l2/edge_discovery.py
tradingbot/ml/research/live_l2/edge_discovery_round2.py
tradingbot/ml/research/live_l2/sl_tp_sweep.py
tradingbot/ml/research/live_l3/__init__.py
tradingbot/ml/research/live_l3/execution_validation.py
tradingbot/ml/research/model_comparison.py
tradingbot/ml/research/model_optimizer.py
tradingbot/ml/research/model_selection.py
tradingbot/ml/research/pa_live_audit/__init__.py
tradingbot/ml/research/pa_live_audit/classify.py
tradingbot/ml/research/pa_live_audit/parity.py
tradingbot/ml/research/pa_live_audit/path.py
tradingbot/ml/research/pa_live_audit/replay.py
tradingbot/ml/research/phase11_5/__init__.py
tradingbot/ml/research/phase11_5/_metrics.py
tradingbot/ml/research/phase11_5/model_comparator.py
tradingbot/ml/research/phase11_5/optimizer_orchestrator.py
tradingbot/ml/research/phase11_5/regime_analysis.py
tradingbot/ml/research/phase11_5/report_generator.py
tradingbot/ml/research/phase11_5/risk_optimizer.py
tradingbot/ml/research/phase11_5/robustness_check.py
tradingbot/ml/research/phase11_5/sell_bias_analyzer.py
tradingbot/ml/research/phase11_5/session_optimizer.py
tradingbot/ml/research/phase11_5/threshold_optimizer.py
tradingbot/ml/research/phase13_10/__init__.py
tradingbot/ml/research/phase13_10/config.py
tradingbot/ml/research/phase13_10/monte_carlo.py
tradingbot/ml/research/phase13_10/orchestrator.py
tradingbot/ml/research/phase13_10/report_generator.py
tradingbot/ml/research/phase13_10/robust_score.py
tradingbot/ml/research/phase13_10/router_policy.py
tradingbot/ml/research/phase13_10/rule_comparator.py
tradingbot/ml/research/phase13_10/threshold_optimizer.py
tradingbot/ml/research/phase13_10/trend_audit/__init__.py
tradingbot/ml/research/phase13_10/trend_audit/funnel_analyzer.py
tradingbot/ml/research/phase13_10/trend_engines.py
tradingbot/ml/research/phase13_10/walk_forward.py
tradingbot/ml/research/phase13_7/__init__.py
tradingbot/ml/research/phase13_7/config.py
tradingbot/ml/research/phase13_7/initial_audit.py
tradingbot/ml/research/phase13_7/monte_carlo_validator.py
tradingbot/ml/research/phase13_7/orchestrator.py
tradingbot/ml/research/phase13_7/range_failure_analyzer.py
tradingbot/ml/research/phase13_7/report_generator.py
tradingbot/ml/research/phase13_7/robust_score.py
tradingbot/ml/research/phase13_7/router_recalibrator.py
tradingbot/ml/research/phase13_7/stability_optimizer.py
tradingbot/ml/research/phase13_7/trade_constraints.py
tradingbot/ml/research/phase13_7/trend_router_debugger.py
tradingbot/ml/research/phase13_7/walk_forward_validator.py
tradingbot/ml/research/phase13_8/__init__.py
tradingbot/ml/research/phase13_8/config.py
tradingbot/ml/research/phase13_8/monte_carlo.py
tradingbot/ml/research/phase13_8/orchestrator.py
tradingbot/ml/research/phase13_8/recovered_trend_engine.py
tradingbot/ml/research/phase13_8/report_generator.py
tradingbot/ml/research/phase13_8/router_simulator.py
tradingbot/ml/research/phase13_8/threshold_optimizer.py
tradingbot/ml/research/phase13_8/trend_audit.py
tradingbot/ml/research/phase13_8/trend_comparator.py
tradingbot/ml/research/phase13_8/trend_feature_research.py
tradingbot/ml/research/phase13_8/trend_label_v2.py
tradingbot/ml/research/phase13_8/trend_ml_retrainer.py
tradingbot/ml/research/phase13_8/trend_variants.py
tradingbot/ml/research/phase13_8/walk_forward.py
tradingbot/ml/research/phase13_9/__init__.py
tradingbot/ml/research/phase13_9/candle_prepare.py
tradingbot/ml/research/phase13_9/config.py
tradingbot/ml/research/phase13_9/feature_parity_checker.py
tradingbot/ml/research/phase13_9/monte_carlo_validator.py
tradingbot/ml/research/phase13_9/orchestrator.py
tradingbot/ml/research/phase13_9/report_generator.py
tradingbot/ml/research/phase13_9/router_pipeline_rebuilder.py
tradingbot/ml/research/phase13_9/signal_loss_analyzer.py
tradingbot/ml/research/phase13_9/trend_adapter_validator.py
tradingbot/ml/research/phase13_9/unified_features.py
tradingbot/ml/research/phase13_9/walk_forward_validator.py
tradingbot/ml/research/phase14_10/__init__.py
tradingbot/ml/research/phase14_10/adaptive_regime_policy.py
tradingbot/ml/research/phase14_10/adaptive_threshold_research.py
tradingbot/ml/research/phase14_10/config.py
tradingbot/ml/research/phase14_10/montecarlo_per_year.py
tradingbot/ml/research/phase14_10/orchestrator.py
tradingbot/ml/research/phase14_10/regime_transition_analysis.py
tradingbot/ml/research/phase14_10/report_generator.py
tradingbot/ml/research/phase14_10/robustness_rebuilder.py
tradingbot/ml/research/phase14_10/yearly_calibration_analysis.py
tradingbot/ml/research/phase14_10/yearly_confidence_distribution.py
tradingbot/ml/research/phase14_10/yearly_feature_drift.py
tradingbot/ml/research/phase14_10/yearly_performance.py
tradingbot/ml/research/phase14_10/yearly_regime_distribution.py
tradingbot/ml/research/phase14_10/yearly_threshold_analysis.py
tradingbot/ml/research/phase14_10/yearly_trade_distribution.py
tradingbot/ml/research/phase14_4/__init__.py
tradingbot/ml/research/phase14_4/confidence_optimizer.py
tradingbot/ml/research/phase14_4/config.py
tradingbot/ml/research/phase14_4/missed_trade_analyzer.py
tradingbot/ml/research/phase14_4/monte_carlo_validator.py
tradingbot/ml/research/phase14_4/orchestrator.py
tradingbot/ml/research/phase14_4/pipeline_simulator.py
tradingbot/ml/research/phase14_4/quality_optimizer.py
tradingbot/ml/research/phase14_4/report_generator.py
tradingbot/ml/research/phase14_4/risk_acceptance_analyzer.py
tradingbot/ml/research/phase14_4/robustness_validator.py
tradingbot/ml/research/phase14_4/threshold_optimizer.py
tradingbot/ml/research/phase14_4/trade_frequency_analyzer.py
tradingbot/ml/research/phase14_4/walk_forward_optimizer.py
tradingbot/ml/research/phase14_5/__init__.py
tradingbot/ml/research/phase14_5/adaptive_threshold_optimizer.py
tradingbot/ml/research/phase14_5/confidence_sweep.py
tradingbot/ml/research/phase14_5/config.py
tradingbot/ml/research/phase14_5/monte_carlo_validator.py
tradingbot/ml/research/phase14_5/opportunity_analyzer.py
tradingbot/ml/research/phase14_5/orchestrator.py
tradingbot/ml/research/phase14_5/pipeline_runner.py
tradingbot/ml/research/phase14_5/regime_threshold_optimizer.py
tradingbot/ml/research/phase14_5/report_generator.py
tradingbot/ml/research/phase14_5/walk_forward_validator.py
tradingbot/ml/research/phase14_6/__init__.py
tradingbot/ml/research/phase14_6/calibration_alternatives.py
tradingbot/ml/research/phase14_6/calibration_audit.py
tradingbot/ml/research/phase14_6/confidence_distribution.py
tradingbot/ml/research/phase14_6/config.py
tradingbot/ml/research/phase14_6/engine_confidence_analysis.py
tradingbot/ml/research/phase14_6/label_alignment.py
tradingbot/ml/research/phase14_6/monte_carlo_validator.py
tradingbot/ml/research/phase14_6/orchestrator.py
tradingbot/ml/research/phase14_6/pipeline_runner.py
tradingbot/ml/research/phase14_6/report_generator.py
tradingbot/ml/research/phase14_6/research_calibrator.py
tradingbot/ml/research/phase14_6/threshold_search.py
tradingbot/ml/research/phase14_6/walk_forward_validator.py
tradingbot/ml/research/phase14_7/__init__.py
tradingbot/ml/research/phase14_7/baseline_runner.py
tradingbot/ml/research/phase14_7/calibration_adapter.py
tradingbot/ml/research/phase14_7/config.py
tradingbot/ml/research/phase14_7/engine_contribution.py
tradingbot/ml/research/phase14_7/monte_carlo_validator.py
tradingbot/ml/research/phase14_7/orchestrator.py
tradingbot/ml/research/phase14_7/performance_analyzer.py
tradingbot/ml/research/phase14_7/pipeline_runner.py
tradingbot/ml/research/phase14_7/quality_adapter.py
tradingbot/ml/research/phase14_7/regime_analyzer.py
tradingbot/ml/research/phase14_7/report_generator.py
tradingbot/ml/research/phase14_7/risk_adapter.py
tradingbot/ml/research/phase14_7/router_runner.py
tradingbot/ml/research/phase14_7/trade_tracker.py
tradingbot/ml/research/phase14_7/walk_forward_validator.py
tradingbot/ml/research/phase14_8/__init__.py
tradingbot/ml/research/phase14_8/confidence_audit.py
tradingbot/ml/research/phase14_8/config.py
tradingbot/ml/research/phase14_8/drawdown_analyzer.py
tradingbot/ml/research/phase14_8/monte_carlo_extended.py
tradingbot/ml/research/phase14_8/multi_period_validator.py
tradingbot/ml/research/phase14_8/orchestrator.py
tradingbot/ml/research/phase14_8/range_engine_audit.py
tradingbot/ml/research/phase14_8/regime_stress_test.py
tradingbot/ml/research/phase14_8/report_generator.py
tradingbot/ml/research/phase14_8/risk_audit.py
tradingbot/ml/research/phase14_8/stress_runner.py
tradingbot/ml/research/phase14_8/trend_engine_audit.py
tradingbot/ml/research/phase14_8/walk_forward_extended.py
tradingbot/ml/research/phase14_9/__init__.py
tradingbot/ml/research/phase14_9/adaptive_router.py
tradingbot/ml/research/phase14_9/config.py
tradingbot/ml/research/phase14_9/dynamic_engine_weight.py
tradingbot/ml/research/phase14_9/orchestrator.py
tradingbot/ml/research/phase14_9/range_engine_analysis.py
tradingbot/ml/research/phase14_9/regime_performance_audit.py
tradingbot/ml/research/phase14_9/report_generator.py
tradingbot/ml/research/phase14_9/robustness_validator.py
tradingbot/ml/research/phase14_9/trend_engine_stability.py
tradingbot/ml/research/phase15g/__init__.py
tradingbot/ml/research/phase15g/bundle_probability_audit.py
tradingbot/ml/research/phase15g/bundle_statistics.py
tradingbot/ml/research/phase15g/confidence_ceiling.py
tradingbot/ml/research/phase15g/confidence_recovery.py
tradingbot/ml/research/phase15g/config.py
tradingbot/ml/research/phase15g/orchestrator.py
tradingbot/ml/research/phase15g/platt_curve_analysis.py
tradingbot/ml/research/phase15g/production_replay.py
tradingbot/ml/research/phase15g/report_generator.py
tradingbot/ml/research/phase15g/research_vs_bundle.py
tradingbot/ml/research/phase15g/risk_gate_simulator.py
tradingbot/ml/research/phase15g/threshold_equivalence.py
tradingbot/ml/research/phase15g/validator.py
tradingbot/ml/research/phase15i/__init__.py
tradingbot/ml/research/phase15i/config.py
tradingbot/ml/research/phase15i/orchestrator.py
tradingbot/ml/research/phase15i/phase99_signal_audit.py
tradingbot/ml/research/phase15i/quality_filter_audit.py
tradingbot/ml/research/phase15i/range_feature_validation.py
tradingbot/ml/research/phase15i/range_path_audit.py
tradingbot/ml/research/phase15i/range_router_validation.py
tradingbot/ml/research/phase15i/recovery_adapter.py
tradingbot/ml/research/phase15i/regime_distribution.py
tradingbot/ml/research/phase15i/replay.py
tradingbot/ml/research/phase15i/report_generator.py
tradingbot/ml/research/phase15i/risk_filter_audit.py
tradingbot/ml/research/phase15i/router_balance.py
tradingbot/ml/research/phase15i/signal_flow.py
tradingbot/ml/research/phase15i/validator.py
tradingbot/ml/research/phase15j/__init__.py
tradingbot/ml/research/phase15j/adapter_validation.py
tradingbot/ml/research/phase15j/bundle_validation.py
tradingbot/ml/research/phase15j/config.py
tradingbot/ml/research/phase15j/engine_probability_distribution.py
tradingbot/ml/research/phase15j/feature_drift.py
tradingbot/ml/research/phase15j/orchestrator.py
tradingbot/ml/research/phase15j/recommendation_engine.py
tradingbot/ml/research/phase15j/report_generator.py
tradingbot/ml/research/phase15j/root_cause_detector.py
tradingbot/ml/research/phase15j/stage_loss_report.py
tradingbot/ml/research/phase15j/trend_pipeline_trace.py
tradingbot/ml/research/phase15j/trend_signal_statistics.py
tradingbot/ml/research/phase15j/validator.py
tradingbot/ml/research/phase15k/__init__.py
tradingbot/ml/research/phase15k/ceiling_analyzer.py
tradingbot/ml/research/phase15k/config.py
tradingbot/ml/research/phase15k/data_access.py
tradingbot/ml/research/phase15k/distribution_drift_ceiling.py
tradingbot/ml/research/phase15k/engine_replay_trace.py
tradingbot/ml/research/phase15k/feature_ceiling_impact.py
tradingbot/ml/research/phase15k/model_behavior_simulator.py
tradingbot/ml/research/phase15k/orchestrator.py
tradingbot/ml/research/phase15k/pipeline_injection_audit.py
tradingbot/ml/research/phase15k/recommendation_ceiling.py
tradingbot/ml/research/phase15k/report_generator.py
tradingbot/ml/research/phase15k/trend_ceiling_root_cause.py
tradingbot/ml/research/phase15k/validator.py
tradingbot/ml/research/phase16b/__init__.py
tradingbot/ml/research/phase16b/alignment_metrics.py
tradingbot/ml/research/phase16b/config.py
tradingbot/ml/research/phase16b/kernel_replay.py
tradingbot/ml/research/phase16b/orchestrator.py
tradingbot/ml/research/phase16b/stress_tests.py
tradingbot/ml/research/phase16b/validator.py
tradingbot/ml/research/phase16c/__init__.py
tradingbot/ml/research/phase16c/config.py
tradingbot/ml/research/phase16c/feature_importance.py
tradingbot/ml/research/phase16c/funnel.py
tradingbot/ml/research/phase16c/orchestrator.py
tradingbot/ml/research/phase16c/pattern_analysis.py
tradingbot/ml/research/phase16c/rejection_clusters.py
tradingbot/ml/research/phase16c/rf_analysis.py
tradingbot/ml/research/phase16c/rule_diagnostics.py
tradingbot/ml/research/phase16c/threshold_simulation.py
tradingbot/ml/research/phase16c/verdict.py
tradingbot/ml/research/phase16d/__init__.py
tradingbot/ml/research/phase16d/candidate_compute.py
tradingbot/ml/research/phase16d/ceiling_analysis.py
tradingbot/ml/research/phase16d/ceiling_simulation.py
tradingbot/ml/research/phase16d/config.py
tradingbot/ml/research/phase16d/data_access.py
tradingbot/ml/research/phase16d/feature_catalog.py
tradingbot/ml/research/phase16d/information_gain.py
tradingbot/ml/research/phase16d/model_limitation.py
tradingbot/ml/research/phase16d/orchestrator.py
tradingbot/ml/research/phase16d/redundancy.py
tradingbot/ml/research/phase16d/verdict.py
tradingbot/ml/research/phase17a/__init__.py
tradingbot/ml/research/phase17a/architecture_matrix.py
tradingbot/ml/research/phase17a/compatibility.py
tradingbot/ml/research/phase17a/config.py
tradingbot/ml/research/phase17a/maintenance.py
tradingbot/ml/research/phase17a/orchestrator.py
tradingbot/ml/research/phase17a/risk_analysis.py
tradingbot/ml/research/phase17a/roadmap.py
tradingbot/ml/research/phase17a/scoring.py
tradingbot/ml/research/phase17a/verdict.py
tradingbot/ml/research/phase17b/__init__.py
tradingbot/ml/research/phase17b/acceptance.py
tradingbot/ml/research/phase17b/comparison.py
tradingbot/ml/research/phase17b/compatibility.py
tradingbot/ml/research/phase17b/config.py
tradingbot/ml/research/phase17b/dataset.py
tradingbot/ml/research/phase17b/research_engine.py
tradingbot/ml/research/phase17b/research_model.py
tradingbot/ml/research/phase17b/shadow_replay.py
tradingbot/ml/research/phase17b/top5_features.py
tradingbot/ml/research/phase17b/training_lab.py
tradingbot/ml/research/phase17b/verdict.py
tradingbot/ml/research/phase17c/__init__.py
tradingbot/ml/research/phase17c/config.py
tradingbot/ml/research/phase17c/dual_shadow.py
tradingbot/ml/research/phase17c/metrics.py
tradingbot/ml/research/phase17c/monte_carlo.py
tradingbot/ml/research/phase17c/orchestrator.py
tradingbot/ml/research/phase17c/range_regression.py
tradingbot/ml/research/phase17c/safety.py
tradingbot/ml/research/phase17c/stability.py
tradingbot/ml/research/phase17c/trend_quality.py
tradingbot/ml/research/phase17c/verdict.py
tradingbot/ml/research/phase17c/walk_forward.py
tradingbot/ml/research/phase18a/__init__.py
tradingbot/ml/research/phase18a/comparator.py
tradingbot/ml/research/phase18a/config.py
tradingbot/ml/research/phase18a/divergence.py
tradingbot/ml/research/phase18a/equity.py
tradingbot/ml/research/phase18a/latency.py
tradingbot/ml/research/phase18a/orchestrator.py
tradingbot/ml/research/phase18a/regime_validation.py
tradingbot/ml/research/phase18a/safety.py
tradingbot/ml/research/phase18a/shadow_runner.py
tradingbot/ml/research/phase18a/statistics.py
tradingbot/ml/research/phase18a/trade_logger.py
tradingbot/ml/research/phase18a/verdict.py
tradingbot/ml/research/phase19b/__init__.py
tradingbot/ml/research/phase19b/config.py
tradingbot/ml/research/phase19b/exit_study.py
tradingbot/ml/research/phase19b/filters.py
tradingbot/ml/research/phase19b/loss_analysis.py
tradingbot/ml/research/phase19b/montecarlo.py
tradingbot/ml/research/phase19b/orchestrator.py
tradingbot/ml/research/phase19b/position_sizing.py
tradingbot/ml/research/phase19b/recommendations.py
tradingbot/ml/research/phase19b/trade_dataset.py
tradingbot/ml/research/phase19b/verdict.py
tradingbot/ml/research/phase19b/walkforward.py
tradingbot/ml/research/phase19b/winner_analysis.py
tradingbot/ml/research/phase22aa/impact_forensics.py
tradingbot/ml/research/phase22ab/freeze_forensics.py
tradingbot/ml/research/phase22ac/registry_investigation.py
tradingbot/ml/research/phase22ad/__init__.py
tradingbot/ml/research/phase22ad/runtime_trace.py
tradingbot/ml/research/phase22ae/freeze_forensics.py
tradingbot/ml/research/phase22af/repair_design.py
tradingbot/ml/research/phase22ag/acceptance_forensics.py
tradingbot/ml/research/phase22ah/numeric_acceptance_validation.py
tradingbot/ml/research/phase22ai/acceptance_regression.py
tradingbot/ml/research/phase22aj/freeze_wiring_validation.py
tradingbot/ml/research/phase22aj0/winner_authority.py
tradingbot/ml/research/phase22ak/__init__.py
tradingbot/ml/research/phase22ak/freeze_execution.py
tradingbot/ml/research/phase22al/live_validation.py
tradingbot/ml/research/phase22c/__init__.py
tradingbot/ml/research/phase22c/config.py
tradingbot/ml/research/phase22c/hold_chain.py
tradingbot/ml/research/phase22c/thresholds.py
tradingbot/ml/research/phase22e/__init__.py
tradingbot/ml/research/phase22e/certification.py
tradingbot/ml/research/phase22e/config.py
tradingbot/ml/research/phase22e/distribution.py
tradingbot/ml/research/phase22e/metrics.py
tradingbot/ml/research/phase22e/walkforward.py
tradingbot/ml/research/phase22f/__init__.py
tradingbot/ml/research/phase22f/config.py
tradingbot/ml/research/phase22f/datasets.py
tradingbot/ml/research/phase22f/overfiltering.py
tradingbot/ml/research/phase22f/priority.py
tradingbot/ml/research/phase22f/rapid_runner.py
tradingbot/ml/research/phase22f/trace.py
tradingbot/ml/research/phase22f/workflow.py
tradingbot/ml/research/phase22i/__init__.py
tradingbot/ml/research/phase22i/candidates.py
tradingbot/ml/research/phase22i/selection.py
tradingbot/ml/research/phase22j/engine_candidates.py
tradingbot/ml/research/phase22j/selection.py
tradingbot/ml/research/phase22p/execution_trace.py
tradingbot/ml/research/phase22p/signal_loss.py
tradingbot/ml/research/phase22p/trade_path.py
tradingbot/ml/research/phase22s/parity_cert.py
tradingbot/ml/research/phase22t/__init__.py
tradingbot/ml/research/phase22t/compare.py
tradingbot/ml/research/phase22t/config.py
tradingbot/ml/research/phase22t/feature_source.py
tradingbot/ml/research/phase22t/patch.py
tradingbot/ml/research/phase22t/runner.py
tradingbot/ml/research/phase22u/model_audit.py
tradingbot/ml/research/phase22w/selection_audit.py
tradingbot/ml/research/phase22y/acceptance_forensics.py
tradingbot/ml/research/phase22z/__init__.py
tradingbot/ml/research/phase22z/overfitting_rule_validation.py
tradingbot/ml/research/phase23a/pipeline_trace.py
tradingbot/ml/research/phase23b/repair_validation.py
tradingbot/ml/research/phase23c/__init__.py
tradingbot/ml/research/phase23c/decision_gate_investigation.py
tradingbot/ml/research/phase23c/run_investigation.py
tradingbot/ml/research/phase23d/__init__.py
tradingbot/ml/research/phase23d/filter_validation_research.py
tradingbot/ml/research/phase23d/run_investigation.py
tradingbot/ml/research/phase23e/__init__.py
tradingbot/ml/research/phase23e/range_filter_study.py
tradingbot/ml/research/phase23e/run_study.py
tradingbot/ml/research/phase23f/__init__.py
tradingbot/ml/research/phase23f/run_validation.py
tradingbot/ml/research/phase23f/shadow_validation.py
tradingbot/ml/research/phase23g/integration_validation.py
tradingbot/ml/research/phase24a/__init__.py
tradingbot/ml/research/phase24a/live_shadow_validator.py
tradingbot/ml/research/phase24a/run_validation.py
tradingbot/ml/research/phase24b/__init__.py
tradingbot/ml/research/phase24b/architecture_audit.py
tradingbot/ml/research/phase24b/run_audit.py
tradingbot/ml/research/phase24c/__init__.py
tradingbot/ml/research/phase24c/latency_profiler.py
tradingbot/ml/research/phase24c/run_profiling.py
tradingbot/ml/research/phase24d/__init__.py
tradingbot/ml/research/phase24d/run_investigation.py
tradingbot/ml/research/phase24d/unified_frame_investigation.py
tradingbot/ml/research/phase24e/run_validation.py
tradingbot/ml/research/phase24f/__init__.py
tradingbot/ml/research/phase24f/incremental_frame.py
tradingbot/ml/research/phase24f/run_investigation.py
tradingbot/ml/research/phase24g/run_validation.py
tradingbot/ml/research/phase24h/__init__.py
tradingbot/ml/research/phase24h/pipeline_tracer.py
tradingbot/ml/research/phase24h/run_investigation.py
tradingbot/ml/research/phase24i/run_validation.py
tradingbot/ml/research/phase25b/__init__.py
tradingbot/ml/research/phase25b/parity_replay_adapter.py
tradingbot/ml/research/phase25b/replay_portfolio.py
tradingbot/ml/research/phase25b/replay_position_state.py
tradingbot/ml/research/phase25b/unified_pipeline_replay.py
tradingbot/ml/research/phase26b/__init__.py
tradingbot/ml/research/phase26b/analyzers.py
tradingbot/ml/research/phase26b/data_loader.py
tradingbot/ml/research/phase26b/run_investigation.py
tradingbot/ml/research/phase27a/__init__.py
tradingbot/ml/research/phase27a/metrics.py
tradingbot/ml/research/phase27l/__init__.py
tradingbot/ml/research/phase27l/exit_simulators.py
tradingbot/ml/research/phase27l/exit_trace.py
tradingbot/ml/research/phase27n/__init__.py
tradingbot/ml/research/phase27n/hybrid_simulators.py
tradingbot/ml/research/phase28c/metrics.py
tradingbot/ml/research/phase28d/__init__.py
tradingbot/ml/research/phase28d/trade_builder.py
tradingbot/ml/research/phase28e/__init__.py
tradingbot/ml/research/phase28e/auditors.py
tradingbot/ml/research/phase28e/run_investigation.py
tradingbot/ml/research/phase28f/__init__.py
tradingbot/ml/research/phase28f/engine_map.py
tradingbot/ml/research/phase28f/run_investigation.py
tradingbot/ml/research/phase29a/__init__.py
tradingbot/ml/research/phase29a/analysis.py
tradingbot/ml/research/phase29a/causality.py
tradingbot/ml/research/phase29a/features.py
tradingbot/ml/research/phase29a/run_investigation.py
tradingbot/ml/research/phase29a/scoring.py
tradingbot/ml/research/phase29a/stress.py
tradingbot/ml/research/phase29b/run_investigation.py
tradingbot/ml/research/phase30a/__init__.py
tradingbot/ml/research/phase30a/breaking_points.py
tradingbot/ml/research/phase30a/pipeline_audit.py
tradingbot/ml/research/phase30a/run_investigation.py
tradingbot/ml/research/phase30a/trade_replay.py
tradingbot/ml/research/phase30d/run_investigation.py
tradingbot/ml/research/phase30e/run_investigation.py
tradingbot/ml/research/phase30f/__init__.py
tradingbot/ml/research/phase30f/collectors/__init__.py
tradingbot/ml/research/phase30f/collectors/base.py
tradingbot/ml/research/phase30f/collectors/execution_logger.py
tradingbot/ml/research/phase30f/collectors/gap_extractor.py
tradingbot/ml/research/phase30f/collectors/history_sync.py
tradingbot/ml/research/phase30f/collectors/news_joiner.py
tradingbot/ml/research/phase30f/collectors/supervisor.py
tradingbot/ml/research/phase30f/collectors/symbol_snapshot.py
tradingbot/ml/research/phase30f/collectors/tick_backfill.py
tradingbot/ml/research/phase30f/collectors/tick_poller.py
tradingbot/ml/research/phase30f/config.py
tradingbot/ml/research/phase30f/mt5_client.py
tradingbot/ml/research/phase30f/run_investigation.py
tradingbot/ml/research/phase30f/storage/__init__.py
tradingbot/ml/research/phase30f/storage/checksums.py
tradingbot/ml/research/phase30f/storage/manifest.py
tradingbot/ml/research/phase30f/storage/parquet_store.py
tradingbot/ml/research/phase30f/storage/sqlite_store.py
tradingbot/ml/research/phase30f/validation/__init__.py
tradingbot/ml/research/phase30f/validation/integrity.py
tradingbot/ml/research/phase30f/validation/schema.py
tradingbot/ml/research/phase31a/__init__.py
tradingbot/ml/research/phase31a/clustering.py
tradingbot/ml/research/phase31a/data_loader.py
tradingbot/ml/research/phase31a/edge_analysis.py
tradingbot/ml/research/phase31a/importance.py
tradingbot/ml/research/phase31a/root_causes.py
tradingbot/ml/research/phase31a/run_investigation.py
tradingbot/ml/research/phase31b/__init__.py
tradingbot/ml/research/phase31b/counterfactuals.py
tradingbot/ml/research/phase31b/metrics.py
tradingbot/ml/research/phase31b/run_investigation.py
tradingbot/ml/research/phase31c/__init__.py
tradingbot/ml/research/phase31c/exit_simulators.py
tradingbot/ml/research/phase31c/ranking.py
tradingbot/ml/research/phase31c/run_investigation.py
tradingbot/ml/research/phase31c/validation.py
tradingbot/ml/research/phase31d/__init__.py
tradingbot/ml/research/phase31d/parity_audit.py
tradingbot/ml/research/phase31d/root_causes.py
tradingbot/ml/research/phase31d/run_investigation.py
tradingbot/ml/research/phase31e/run_investigation.py
tradingbot/ml/research/phase32g/run_validation.py
tradingbot/ml/research/phase33d/__init__.py
tradingbot/ml/research/phase33d/forensic_context.py
tradingbot/ml/research/phase33d/schema.py
tradingbot/ml/research/phase34a/__init__.py
tradingbot/ml/research/phase34a/collector.py
tradingbot/ml/research/phase34a/metrics.py
tradingbot/ml/research/phase34c/run_filter_audit.py
tradingbot/ml/research/phase35/__init__.py
tradingbot/ml/research/phase35/label_alignment.py
tradingbot/ml/research/phase36/__init__.py
tradingbot/ml/research/phase36/build_dataset_v3.py
tradingbot/ml/research/phase39/candle_sources.py
tradingbot/ml/research/phase39/expand_dataset.py
tradingbot/ml/research/phase40/retrain_sweep.py
tradingbot/ml/research/phase41/model_search.py
tradingbot/ml/research/phase42/event_bias_audit.py
tradingbot/ml/research/phase42/feature_parity.py
tradingbot/ml/research/phase43/subset_builder.py
tradingbot/ml/research/phase45/structure_dataset.py
tradingbot/ml/research/phase46/ml_signal_dataset.py
tradingbot/ml/research/phase49/bar_index.py
tradingbot/ml/research/phase49/historical_windows.py
tradingbot/ml/research/phase50/strict_walk_forward.py
tradingbot/ml/research/phase51/profitability_score.py
tradingbot/ml/research/ranking.py
tradingbot/ml/research/regime_detector/__init__.py
tradingbot/ml/research/regime_detector/orchestrator.py
tradingbot/ml/research/regime_detector/regime_classifier.py
tradingbot/ml/research/regime_detector/regime_features.py
tradingbot/ml/research/regime_detector/regime_optimizer.py
tradingbot/ml/research/regime_detector/regime_report.py
tradingbot/ml/research/regime_detector/regime_validator.py
tradingbot/ml/research/regime_optimization/__init__.py
tradingbot/ml/research/regime_optimization/event_filter_optimizer.py
tradingbot/ml/research/regime_optimization/optimization_orchestrator.py
tradingbot/ml/research/regime_optimization/regime_detector.py
tradingbot/ml/research/regime_optimization/regime_model_optimizer.py
tradingbot/ml/research/regime_optimization/regime_utils.py
tradingbot/ml/research/regime_optimization/stable_feature_selector.py
tradingbot/ml/research/regime_optimization/walk_forward_validator.py
tradingbot/ml/research/regime_router/__init__.py
tradingbot/ml/research/regime_router/config.py
tradingbot/ml/research/regime_router/phase99_feature_validation.py
tradingbot/ml/research/regime_router/range_engine_adapter.py
tradingbot/ml/research/regime_router/regime_performance.py
tradingbot/ml/research/regime_router/regime_router.py
tradingbot/ml/research/regime_router/report_generator.py
tradingbot/ml/research/regime_router/router_validator.py
tradingbot/ml/research/regime_router/signal_aggregator.py
tradingbot/ml/research/regime_router/trend_engine_adapter.py
tradingbot/ml/research/regime_router/unified_feature_input.py
tradingbot/ml/research/regime_router/walk_forward_router.py
tradingbot/ml/research/reports.py
tradingbot/ml/research/reproducibility.py
tradingbot/ml/research/research_orchestrator.py
tradingbot/ml/research/research_utils.py
tradingbot/ml/research/retrain_optimizer.py
tradingbot/ml/research/retrain_report.py
tradingbot/ml/research/robustness_optimizer/__init__.py
tradingbot/ml/research/robustness_optimizer/candidate_selector.py
tradingbot/ml/research/robustness_optimizer/freeze_bridge.py
tradingbot/ml/research/robustness_optimizer/model_regularization.py
tradingbot/ml/research/robustness_optimizer/optimization_orchestrator.py
tradingbot/ml/research/robustness_optimizer/probability_selection_gate.py
tradingbot/ml/research/robustness_optimizer/regime_robustness.py
tradingbot/ml/research/robustness_optimizer/report_generator.py
tradingbot/ml/research/robustness_optimizer/stable_feature_research.py
tradingbot/ml/research/robustness_optimizer/walk_forward_optimizer.py
tradingbot/ml/research/robustness_optimizer/window_validator.py
tradingbot/ml/research/router_optimizer/__init__.py
tradingbot/ml/research/router_optimizer/confidence_optimizer.py
tradingbot/ml/research/router_optimizer/engine_cache.py
tradingbot/ml/research/router_optimizer/failure_analyzer.py
tradingbot/ml/research/router_optimizer/optimizer_types.py
tradingbot/ml/research/router_optimizer/orchestrator.py
tradingbot/ml/research/router_optimizer/regime_weight_optimizer.py
tradingbot/ml/research/router_optimizer/report_generator.py
tradingbot/ml/research/router_optimizer/robustness_validator.py
tradingbot/ml/research/router_optimizer/router_optimizer.py
tradingbot/ml/research/router_optimizer/session_optimizer.py
tradingbot/ml/research/router_optimizer/threshold_optimizer.py
tradingbot/ml/research/router_optimizer/trade_filter_optimizer.py
tradingbot/ml/research/router_optimizer/walk_forward_optimizer.py
tradingbot/ml/research/sampling_analysis.py
tradingbot/ml/research/schema.py
tradingbot/ml/research/threshold_optimizer.py
tradingbot/ml/research/trend_ml/__init__.py
tradingbot/ml/research/trend_ml/feature_builder.py
tradingbot/ml/research/trend_ml/label_builder.py
tradingbot/ml/research/trend_ml/models.py
tradingbot/ml/research/trend_ml/optimizer.py
tradingbot/ml/research/trend_ml/report.py
tradingbot/ml/research/trend_ml/trend_ml_filter.py
tradingbot/ml/research/trend_ml/validator.py
tradingbot/ml/research/trend_strategy/__init__.py
tradingbot/ml/research/trend_strategy/report.py
tradingbot/ml/research/trend_strategy/trend_backtest.py
tradingbot/ml/research/trend_strategy/trend_features.py
tradingbot/ml/research/trend_strategy/trend_rules.py
tradingbot/ml/research/trend_strategy/trend_signal.py
tradingbot/ml/research/trend_strategy/walk_forward.py
tradingbot/ml/research/v41_isolated/__init__.py
tradingbot/ml/research/v41_isolated/cost_robustness.py
tradingbot/ml/research/v41_isolated/decision_audit.py
tradingbot/ml/research/v41_isolated/integrity.py
tradingbot/ml/research/v41_isolated/replay.py
tradingbot/ml/research/v41_isolated/robustness.py
tradingbot/ml/research/walk_forward/__init__.py
tradingbot/ml/research/walk_forward/model_validator.py
tradingbot/ml/research/walk_forward/report_generator.py
tradingbot/ml/research/walk_forward/robustness_analyzer.py
tradingbot/ml/research/walk_forward/walk_forward_engine.py
tradingbot/ml/research/walk_forward/walk_forward_metrics.py
tradingbot/ml/research/walk_forward/window_manager.py
tradingbot/ml/risk_intelligence/__init__.py
tradingbot/ml/risk_intelligence/adaptive_risk_engine.py
tradingbot/ml/risk_intelligence/confidence_risk_mapper.py
tradingbot/ml/risk_intelligence/drawdown_controller.py
tradingbot/ml/risk_intelligence/engine_performance.py
tradingbot/ml/risk_intelligence/regime_risk_adjuster.py
tradingbot/ml/risk_intelligence/risk_policy.py
tradingbot/ml/risk_intelligence/risk_trace.py
tradingbot/ml/risk_intelligence/risk_types.py
tradingbot/ml/risk_intelligence/session_risk_adjuster.py
tradingbot/ml/risk_intelligence/validator.py
tradingbot/ml/risk_intelligence/volatility_risk_adjuster.py
tradingbot/ml/shadow/__init__.py
tradingbot/ml/shadow/config.py
tradingbot/ml/shadow/decision_logger.py
tradingbot/ml/shadow/kernel_bridge.py
tradingbot/ml/shadow/ml_adapter.py
tradingbot/ml/shadow/phase49a_gate.py
tradingbot/ml/shadow/phase49a_metrics.py
tradingbot/ml/shadow/phase_d_metrics.py
tradingbot/ml/shadow/shadow_engine.py
tradingbot/ml/shadow/shadow_gate.py
tradingbot/ml/shadow/shadow_live_sync.py
tradingbot/ml/shadow/shadow_logger.py
tradingbot/ml/shadow/shadow_metrics.py
tradingbot/ml/shadow/shadow_observer.py
tradingbot/ml/shadow/shadow_signal.py
tradingbot/ml/stress/__init__.py
tradingbot/ml/stress/chaos_tests.py
tradingbot/ml/stress/resilience.py
tradingbot/ml/stress/scenarios.py
tradingbot/ml/stress/simulator.py
tradingbot/ml/trade_quality/__init__.py
tradingbot/ml/trade_quality/adapter.py
tradingbot/ml/trade_quality/engine_history.py
tradingbot/ml/trade_quality/liquidity_quality.py
tradingbot/ml/trade_quality/quality_engine.py
tradingbot/ml/trade_quality/quality_policy.py
tradingbot/ml/trade_quality/quality_trace.py
tradingbot/ml/trade_quality/quality_types.py
tradingbot/ml/trade_quality/regime_quality.py
tradingbot/ml/trade_quality/rr_quality.py
tradingbot/ml/trade_quality/signal_quality.py
tradingbot/ml/trade_quality/timing_quality.py
tradingbot/ml/trade_quality/validator.py
tradingbot/ml/trade_quality/volatility_quality.py
tradingbot/ml/training/__init__.py
tradingbot/ml/training/data_loader.py
tradingbot/ml/training/evaluation.py
tradingbot/ml/training/feature_pipeline.py
tradingbot/ml/training/model_factory.py
tradingbot/ml/training/model_registry.py
tradingbot/ml/training/phase9_production.py
tradingbot/ml/training/train_state.py
tradingbot/ml/training/trainer.py
tradingbot/ml/validation/__init__.py
tradingbot/ml/validation/_utils.py
tradingbot/ml/validation/calibration.py
tradingbot/ml/validation/cross_validation.py
tradingbot/ml/validation/feature_ablation.py
tradingbot/ml/validation/regime_test.py
tradingbot/ml/validation/report.py
tradingbot/ml/validation/robustness.py
tradingbot/ml/validation/threshold_optimizer.py
tradingbot/ml/validation/trading_simulator.py
tradingbot/ml/validation/walk_forward.py
tradingbot/pipeline/__init__.py
tradingbot/pipeline/base.py
tradingbot/pipeline/data_stage.py
tradingbot/pipeline/execution_stage.py
tradingbot/pipeline/indicator_stage.py
tradingbot/pipeline/risk_stage.py
tradingbot/pipeline/signal_filter_stage.py
tradingbot/pipeline/signal_stage.py
tradingbot/ports/__init__.py
tradingbot/ports/execution.py
tradingbot/ports/indicators.py
tradingbot/ports/market_data.py
tradingbot/ports/position_manager.py
tradingbot/ports/risk.py
tradingbot/ports/storage.py
tradingbot/ports/strategies.py
tradingbot/research/__init__.py
tradingbot/research/orb_forward_demo.py
tradingbot/research/phase17a_forensic.py
tradingbot/services/__init__.py
tradingbot/services/daily_engine_report.py
tradingbot/services/demo_account_guard.py
tradingbot/services/drift_monitor.py
tradingbot/services/emergency_stop_state.py
tradingbot/services/engine_telemetry.py
tradingbot/services/execution_mode.py
tradingbot/services/exit_mode.py
tradingbot/services/exit_policy.py
tradingbot/services/jsonl_rotation.py
tradingbot/services/kill_switch.py
tradingbot/services/live_loop_health.py
tradingbot/services/live_ops_service.py
tradingbot/services/live_reporting.py
tradingbot/services/live_risk_tracker.py
tradingbot/services/manual_stop.py
tradingbot/services/meta_decision_log.py
tradingbot/services/meta_false_negative.py
tradingbot/services/meta_labeler.py
tradingbot/services/mt5_order_guard.py
tradingbot/services/notifier.py
tradingbot/services/pa_production_lock.py
tradingbot/services/paper_fill_resolver.py
tradingbot/services/paper_trade_exit.py
tradingbot/services/paper_trade_recorder.py
tradingbot/services/phase47c_forward_tracker.py
tradingbot/services/phase51a_forward_cert.py
tradingbot/services/position_protector.py
tradingbot/services/position_recovery_service.py
tradingbot/services/rejection_events.py
tradingbot/services/router_decision_log.py
tradingbot/services/runtime_truth.py
tradingbot/services/signal_filter_log.py
tradingbot/services/signal_filter_mode.py
tradingbot/services/startup_validator.py
tradingbot/services/trade_journal.py
tradingbot/services/winner_population_signal_quality_filter.py
tradingbot/services/wpsqf_calibration.py
tradingbot/services/wpsqf_features.py
tradingbot/services/wpsqf_scoring.py
tradingbot/strategies/__init__.py
tradingbot/strategies/adaptive_quality_engine.py
tradingbot/strategies/adaptive_regime.py
tradingbot/strategies/vol_regime_signal.py
```

### 2.2 Runtime-only REACHABLE (subset)

_670 files_

```
engine/__init__.py
engine/config.py
engine/logger.py
engine/strategies/__init__.py
engine/strategies/base_strategy.py
engine/strategy_manager.py
scripts/backtest_custom_range.py
scripts/build_ml_dataset.py
scripts/check_live_setup.py
scripts/check_vol_regime_live_setup.py
scripts/collect_ml_data.py
scripts/dashboard_server.py
scripts/demo_proof_status.py
scripts/diagnose_autotrading.py
scripts/fix_mt5_experts_ini.py
scripts/live_daily_report.py
scripts/morning_go_live_check.py
scripts/release_mt5_ipc_lock.py
scripts/run_backtest.py
scripts/run_live_watchdog.py
scripts/run_phase17d_bundle_promotion.py
scripts/scheduled_ml_refresh.py
scripts/show_meta_stats.py
scripts/smoke_test_execution.py
scripts/start_bot.py
scripts/status_live.py
scripts/status_snapshot.py
scripts/train_meta_labeler.py
scripts/verify_ml_live_ready.py
scripts/weekend_checklist.py
tradingbot/__init__.py
tradingbot/__main__.py
tradingbot/accounting/__init__.py
tradingbot/accounting/broker_constraints.py
tradingbot/accounting/engine.py
tradingbot/accounting/ledger.py
tradingbot/accounting/metrics.py
tradingbot/accounting/pnl.py
tradingbot/accounting/position_sizing.py
tradingbot/adapters/__init__.py
tradingbot/adapters/adaptive_regime_strategy_registry.py
tradingbot/adapters/background_services.py
tradingbot/adapters/indicator_engine.py
tradingbot/adapters/legacy_loader.py
tradingbot/adapters/legacy_strategy_registry.py
tradingbot/adapters/market_cache.py
tradingbot/adapters/mt5_execution.py
tradingbot/adapters/mt5_health.py
tradingbot/adapters/mt5_market_data.py
tradingbot/adapters/mt5_position_manager.py
tradingbot/adapters/mt5_utils.py
tradingbot/adapters/multi_engine_router.py
tradingbot/adapters/risk_gate.py
tradingbot/adapters/shadow_strategy_registry.py
tradingbot/adapters/stubs.py
tradingbot/adapters/symbols.py
tradingbot/adapters/timeframes.py
tradingbot/adapters/vol_regime_strategy_registry.py
tradingbot/application/__init__.py
tradingbot/application/bootstrap.py
tradingbot/application/live_runner.py
tradingbot/backtest/__init__.py
tradingbot/backtest/broker.py
tradingbot/backtest/config.py
tradingbot/backtest/cost_model.py
tradingbot/backtest/data_source.py
tradingbot/backtest/dataset_contract.py
tradingbot/backtest/dataset_provenance.py
tradingbot/backtest/engine.py
tradingbot/backtest/htf_provider.py
tradingbot/backtest/indicators.py
tradingbot/backtest/instrument.py
tradingbot/backtest/metrics.py
tradingbot/backtest/models.py
tradingbot/backtest/position_manager.py
tradingbot/backtest/risk.py
tradingbot/config/__init__.py
tradingbot/config/dotenv_loader.py
tradingbot/config/engine_settings.py
tradingbot/config/legacy_settings.py
tradingbot/config/live.py
tradingbot/config/pa_symbol_tf_presets.py
tradingbot/config/price_action.py
tradingbot/config/prop_presets.py
tradingbot/config/settings.py
tradingbot/config/strategies.py
tradingbot/domain/__init__.py
tradingbot/domain/broker_economics.py
tradingbot/domain/enums.py
tradingbot/domain/filter_policy.py
tradingbot/domain/htf_bias.py
tradingbot/domain/live_gates.py
tradingbot/domain/market_filters.py
tradingbot/domain/models.py
tradingbot/domain/news_logic.py
tradingbot/domain/ohlcv.py
tradingbot/domain/position_logic.py
tradingbot/domain/position_preset.py
tradingbot/domain/price_action.py
tradingbot/domain/professional_pm.py
tradingbot/domain/risk_logic.py
tradingbot/domain/session_logic.py
tradingbot/domain/signal_helpers.py
tradingbot/domain/trade_features.py
tradingbot/infra/__init__.py
tradingbot/infra/logging.py
tradingbot/kernel/__init__.py
tradingbot/kernel/trading_kernel.py
tradingbot/ml/__init__.py
tradingbot/ml/backtest/__init__.py
tradingbot/ml/backtest/broker_sim.py
tradingbot/ml/backtest/engine.py
tradingbot/ml/backtest/metrics.py
tradingbot/ml/backtest/model_loader.py
tradingbot/ml/backtest/phase97_engine.py
tradingbot/ml/backtest/report.py
tradingbot/ml/backtest/risk.py
tradingbot/ml/backtest/state.py
tradingbot/ml/backtest/strategy.py
tradingbot/ml/backtest/trade_state.py
tradingbot/ml/confidence_engine/__init__.py
tradingbot/ml/confidence_engine/calibration_policy.py
tradingbot/ml/confidence_engine/calibration_trace.py
tradingbot/ml/confidence_engine/calibration_types.py
tradingbot/ml/confidence_engine/calibrator.py
tradingbot/ml/confidence_engine/engine_calibrator.py
tradingbot/ml/confidence_engine/regime_calibrator.py
tradingbot/ml/confidence_engine/session_adjuster.py
tradingbot/ml/confidence_engine/validator.py
tradingbot/ml/confidence_engine/volatility_adjuster.py
tradingbot/ml/confidence_mapping/__init__.py
tradingbot/ml/confidence_mapping/confidence_mapper.py
tradingbot/ml/confidence_mapping/config.py
tradingbot/ml/confidence_mapping/equivalence_solver.py
tradingbot/ml/confidence_mapping/mapping_curve.py
tradingbot/ml/confidence_mapping/mapping_trace.py
tradingbot/ml/confidence_mapping/mapping_types.py
tradingbot/ml/confidence_mapping/mapping_validator.py
tradingbot/ml/confidence_mapping/orchestrator.py
tradingbot/ml/confidence_mapping/production_adapter.py
tradingbot/ml/confidence_mapping/production_replay.py
tradingbot/ml/confidence_mapping/report_generator.py
tradingbot/ml/confidence_mapping/research_parity.py
tradingbot/ml/confidence_mapping/safety_audit.py
tradingbot/ml/confidence_mapping/validator.py
tradingbot/ml/data/__init__.py
tradingbot/ml/data/collection_manifest.py
tradingbot/ml/data/collection_validation.py
tradingbot/ml/data/historical_collection_report.py
tradingbot/ml/data/historical_fetcher.py
tradingbot/ml/data/historical_quality_validator.py
tradingbot/ml/data/market_event_extractor.py
tradingbot/ml/data/metadata.py
tradingbot/ml/data/mt5_fetch.py
tradingbot/ml/data/news_calendar.py
tradingbot/ml/data/optimized_fetcher.py
tradingbot/ml/data/paths.py
tradingbot/ml/data/pipeline.py
tradingbot/ml/data/pipeline_report.py
tradingbot/ml/data/quality/__init__.py
tradingbot/ml/data/quality/anomaly_detector.py
tradingbot/ml/data/quality/candle_validator.py
tradingbot/ml/data/quality/gap_detector.py
tradingbot/ml/data/quality/report.py
tradingbot/ml/data/quality/tick_validator.py
tradingbot/ml/data/raw_fingerprint.py
tradingbot/ml/data/roles.py
tradingbot/ml/data/schema.py
tradingbot/ml/data/session_utils.py
tradingbot/ml/data/stores/__init__.py
tradingbot/ml/data/stores/candle_store.py
tradingbot/ml/data/stores/event_store.py
tradingbot/ml/data/stores/session_store.py
tradingbot/ml/data/stores/spread_store.py
tradingbot/ml/data/stores/tick_store.py
tradingbot/ml/dataset/__init__.py
tradingbot/ml/dataset/builder.py
tradingbot/ml/dataset/deep_audit.py
tradingbot/ml/dataset/feature_analysis.py
tradingbot/ml/dataset/fingerprint.py
tradingbot/ml/dataset/hardening.py
tradingbot/ml/dataset/label_analysis.py
tradingbot/ml/dataset/label_quality.py
tradingbot/ml/dataset/label_research.py
tradingbot/ml/dataset/labels.py
tradingbot/ml/dataset/leakage_report.py
tradingbot/ml/dataset/memory_cache.py
tradingbot/ml/dataset/phase9_production_build.py
tradingbot/ml/dataset/preflight.py
tradingbot/ml/dataset/production_builder.py
tradingbot/ml/dataset/production_dataset_v2.py
tradingbot/ml/dataset/regime_analysis.py
tradingbot/ml/dataset/report.py
tradingbot/ml/dataset/sanity_gate.py
tradingbot/ml/dataset/schema.py
tradingbot/ml/dataset/sparse_event_builder.py
tradingbot/ml/dataset/splitter.py
tradingbot/ml/dataset/statistics.py
tradingbot/ml/dataset/store.py
tradingbot/ml/dataset/train_readiness_report.py
tradingbot/ml/dataset/validation.py
tradingbot/ml/decision/__init__.py
tradingbot/ml/decision/confidence.py
tradingbot/ml/decision/explain.py
tradingbot/ml/decision/logger.py
tradingbot/ml/decision/policy.py
tradingbot/ml/decision/predictor.py
tradingbot/ml/decision/schema.py
tradingbot/ml/decision/shadow.py
tradingbot/ml/decision_engine/__init__.py
tradingbot/ml/decision_engine/confidence_engine.py
tradingbot/ml/decision_engine/decision_policy.py
tradingbot/ml/decision_engine/decision_trace.py
tradingbot/ml/decision_engine/decision_types.py
tradingbot/ml/decision_engine/orchestrator.py
tradingbot/ml/decision_engine/strategy_selector.py
tradingbot/ml/decision_engine/validation.py
tradingbot/ml/decision_engine/vol_regime_branch.py
tradingbot/ml/feature_alignment/__init__.py
tradingbot/ml/feature_alignment/alignment_trace.py
tradingbot/ml/feature_alignment/config.py
tradingbot/ml/feature_alignment/distribution_aligner.py
tradingbot/ml/feature_alignment/factory.py
tradingbot/ml/feature_alignment/feature_statistics.py
tradingbot/ml/feature_alignment/quantile_mapper.py
tradingbot/ml/features/__init__.py
tradingbot/ml/features/base.py
tradingbot/ml/features/builder.py
tradingbot/ml/features/quality/__init__.py
tradingbot/ml/features/quality/feature_report.py
tradingbot/ml/features/quality/feature_validator.py
tradingbot/ml/features/registry/__init__.py
tradingbot/ml/features/registry/enrichment.py
tradingbot/ml/features/registry/registry.py
tradingbot/ml/features/reproducibility.py
tradingbot/ml/features/scaling.py
tradingbot/ml/features/store.py
tradingbot/ml/features/unified_feature_store.py
tradingbot/ml/hybrid/__init__.py
tradingbot/ml/hybrid/config.py
tradingbot/ml/hybrid/conflict.py
tradingbot/ml/hybrid/engine.py
tradingbot/ml/hybrid/explain.py
tradingbot/ml/hybrid/logger.py
tradingbot/ml/hybrid/ml_adapter.py
tradingbot/ml/hybrid/rules_adapter.py
tradingbot/ml/hybrid/schema.py
tradingbot/ml/hybrid/scoring.py
tradingbot/ml/integration/__init__.py
tradingbot/ml/integration/composite_registry.py
tradingbot/ml/integration/config.py
tradingbot/ml/integration/error_audit/__init__.py
tradingbot/ml/integration/error_audit/error_report.py
tradingbot/ml/integration/error_audit/kernel_error_analyzer.py
tradingbot/ml/integration/error_audit/recovery_manager.py
tradingbot/ml/integration/error_audit/shadow_health_check.py
tradingbot/ml/integration/factory.py
tradingbot/ml/integration/health_gate.py
tradingbot/ml/integration/kernel_adapter.py
tradingbot/ml/integration/kernel_builder.py
tradingbot/ml/integration/kernel_run_logger.py
tradingbot/ml/integration/kernel_shadow_runner.py
tradingbot/ml/integration/live_market_adapter.py
tradingbot/ml/integration/live_metrics.py
tradingbot/ml/integration/live_preflight.py
tradingbot/ml/integration/live_run_logger.py
tradingbot/ml/integration/live_shadow_runner.py
tradingbot/ml/integration/ml_kernel_registry.py
tradingbot/ml/integration/ml_strategy.py
tradingbot/ml/integration/monitoring.py
tradingbot/ml/integration/pipeline_cache.py
tradingbot/ml/integration/recovered_calibration.py
tradingbot/ml/integration/regime_filter_profiles.py
tradingbot/ml/integration/replay_market_data.py
tradingbot/ml/integration/shadow_execution_guard.py
tradingbot/ml/integration/signal_mapper.py
tradingbot/ml/integration/sl_tp_calculator.py
tradingbot/ml/integration/startup_diagnostics.py
tradingbot/ml/integration/timeout_diagnostics.py
tradingbot/ml/integration/trade_integrity.py
tradingbot/ml/integration/trade_integrity_logger.py
tradingbot/ml/integration/virtual_trade_builder.py
tradingbot/ml/memory/__init__.py
tradingbot/ml/memory/calibration.py
tradingbot/ml/memory/evaluator.py
tradingbot/ml/memory/outcome.py
tradingbot/ml/memory/performance.py
tradingbot/ml/memory/reports.py
tradingbot/ml/memory/schema.py
tradingbot/ml/memory/store.py
tradingbot/ml/models/__init__.py
tradingbot/ml/models/artifacts.py
tradingbot/ml/models/base.py
tradingbot/ml/models/dataset_loader.py
tradingbot/ml/models/evaluator.py
tradingbot/ml/models/lightgbm_model.py
tradingbot/ml/models/logistic_model.py
tradingbot/ml/models/registry.py
tradingbot/ml/models/training.py
tradingbot/ml/models/xgboost_model.py
tradingbot/ml/monitoring/__init__.py
tradingbot/ml/monitoring/bundle_monitor.py
tradingbot/ml/monitoring/config.py
tradingbot/ml/monitoring/decision_logger.py
tradingbot/ml/monitoring/engine_monitor.py
tradingbot/ml/monitoring/fallback_monitor.py
tradingbot/ml/monitoring/health_monitor.py
tradingbot/ml/monitoring/latency_monitor.py
tradingbot/ml/monitoring/observer.py
tradingbot/ml/monitoring/performance_monitor.py
tradingbot/ml/monitoring/prediction_monitor.py
tradingbot/ml/monitoring/schema.py
tradingbot/ml/monitoring/statistics.py
tradingbot/ml/paper_trading/__init__.py
tradingbot/ml/paper_trading/market_stream.py
tradingbot/ml/paper_trading/model_registry.py
tradingbot/ml/paper_trading/paper_broker.py
tradingbot/ml/paper_trading/performance_tracker.py
tradingbot/ml/paper_trading/position_manager.py
tradingbot/ml/paper_trading/report.py
tradingbot/ml/paper_trading/shadow_engine.py
tradingbot/ml/paper_trading/signal_engine.py
tradingbot/ml/phase15a/__init__.py
tradingbot/ml/phase15a/checklist.py
tradingbot/ml/phase15a/config.py
tradingbot/ml/phase15a/engine_discovery.py
tradingbot/ml/phase15a/engine_registry.py
tradingbot/ml/phase15a/health_check.py
tradingbot/ml/phase15a/interfaces.py
tradingbot/ml/phase15a/orchestrator.py
tradingbot/ml/phase15a/pipeline_validator.py
tradingbot/ml/phase15a/report_generator.py
tradingbot/ml/phase15a/trend_bundle.py
tradingbot/ml/phase15a/unified_signal.py
tradingbot/ml/phase17d/__init__.py
tradingbot/ml/phase17d/bundle_freeze.py
tradingbot/ml/phase17d/compatibility.py
tradingbot/ml/phase17d/config.py
tradingbot/ml/phase17d/health.py
tradingbot/ml/phase17d/live_safety.py
tradingbot/ml/phase17d/orchestrator.py
tradingbot/ml/phase17d/regression.py
tradingbot/ml/phase17d/rollback.py
tradingbot/ml/phase17d/v41_engine.py
tradingbot/ml/phase17d/verdict.py
tradingbot/ml/phase17d/versioning.py
tradingbot/ml/phase19c/__init__.py
tradingbot/ml/phase19c/config.py
tradingbot/ml/phase19c/filters.py
tradingbot/ml/research/__init__.py
tradingbot/ml/research/experiment_runner.py
tradingbot/ml/research/experiment_tracker.py
tradingbot/ml/research/feature_research.py
tradingbot/ml/research/hypothesis.py
tradingbot/ml/research/label_experiment.py
tradingbot/ml/research/live_l2/__init__.py
tradingbot/ml/research/live_l2/edge_discovery.py
tradingbot/ml/research/live_l2/edge_discovery_round2.py
tradingbot/ml/research/live_l2/sl_tp_sweep.py
tradingbot/ml/research/live_l3/__init__.py
tradingbot/ml/research/live_l3/execution_validation.py
tradingbot/ml/research/model_comparison.py
tradingbot/ml/research/model_selection.py
tradingbot/ml/research/phase11_5/__init__.py
tradingbot/ml/research/phase11_5/_metrics.py
tradingbot/ml/research/phase11_5/model_comparator.py
tradingbot/ml/research/phase11_5/optimizer_orchestrator.py
tradingbot/ml/research/phase11_5/regime_analysis.py
tradingbot/ml/research/phase11_5/report_generator.py
tradingbot/ml/research/phase11_5/risk_optimizer.py
tradingbot/ml/research/phase11_5/robustness_check.py
tradingbot/ml/research/phase11_5/sell_bias_analyzer.py
tradingbot/ml/research/phase11_5/session_optimizer.py
tradingbot/ml/research/phase11_5/threshold_optimizer.py
tradingbot/ml/research/phase13_8/__init__.py
tradingbot/ml/research/phase13_8/config.py
tradingbot/ml/research/phase13_8/monte_carlo.py
tradingbot/ml/research/phase13_8/orchestrator.py
tradingbot/ml/research/phase13_8/recovered_trend_engine.py
tradingbot/ml/research/phase13_8/report_generator.py
tradingbot/ml/research/phase13_8/router_simulator.py
tradingbot/ml/research/phase13_8/threshold_optimizer.py
tradingbot/ml/research/phase13_8/trend_audit.py
tradingbot/ml/research/phase13_8/trend_comparator.py
tradingbot/ml/research/phase13_8/trend_feature_research.py
tradingbot/ml/research/phase13_8/trend_label_v2.py
tradingbot/ml/research/phase13_8/trend_ml_retrainer.py
tradingbot/ml/research/phase13_8/trend_variants.py
tradingbot/ml/research/phase13_8/walk_forward.py
tradingbot/ml/research/phase13_9/__init__.py
tradingbot/ml/research/phase13_9/candle_prepare.py
tradingbot/ml/research/phase13_9/config.py
tradingbot/ml/research/phase13_9/feature_parity_checker.py
tradingbot/ml/research/phase13_9/monte_carlo_validator.py
tradingbot/ml/research/phase13_9/orchestrator.py
tradingbot/ml/research/phase13_9/report_generator.py
tradingbot/ml/research/phase13_9/router_pipeline_rebuilder.py
tradingbot/ml/research/phase13_9/signal_loss_analyzer.py
tradingbot/ml/research/phase13_9/trend_adapter_validator.py
tradingbot/ml/research/phase13_9/unified_features.py
tradingbot/ml/research/phase13_9/walk_forward_validator.py
tradingbot/ml/research/phase14_4/__init__.py
tradingbot/ml/research/phase14_4/confidence_optimizer.py
tradingbot/ml/research/phase14_4/config.py
tradingbot/ml/research/phase14_4/missed_trade_analyzer.py
tradingbot/ml/research/phase14_4/monte_carlo_validator.py
tradingbot/ml/research/phase14_4/orchestrator.py
tradingbot/ml/research/phase14_4/pipeline_simulator.py
tradingbot/ml/research/phase14_4/quality_optimizer.py
tradingbot/ml/research/phase14_4/report_generator.py
tradingbot/ml/research/phase14_4/risk_acceptance_analyzer.py
tradingbot/ml/research/phase14_4/robustness_validator.py
tradingbot/ml/research/phase14_4/threshold_optimizer.py
tradingbot/ml/research/phase14_4/trade_frequency_analyzer.py
tradingbot/ml/research/phase14_4/walk_forward_optimizer.py
tradingbot/ml/research/phase14_6/__init__.py
tradingbot/ml/research/phase14_6/calibration_alternatives.py
tradingbot/ml/research/phase14_6/calibration_audit.py
tradingbot/ml/research/phase14_6/confidence_distribution.py
tradingbot/ml/research/phase14_6/config.py
tradingbot/ml/research/phase14_6/engine_confidence_analysis.py
tradingbot/ml/research/phase14_6/label_alignment.py
tradingbot/ml/research/phase14_6/monte_carlo_validator.py
tradingbot/ml/research/phase14_6/orchestrator.py
tradingbot/ml/research/phase14_6/pipeline_runner.py
tradingbot/ml/research/phase14_6/report_generator.py
tradingbot/ml/research/phase14_6/research_calibrator.py
tradingbot/ml/research/phase14_6/threshold_search.py
tradingbot/ml/research/phase14_6/walk_forward_validator.py
tradingbot/ml/research/phase14_7/__init__.py
tradingbot/ml/research/phase14_7/baseline_runner.py
tradingbot/ml/research/phase14_7/calibration_adapter.py
tradingbot/ml/research/phase14_7/config.py
tradingbot/ml/research/phase14_7/engine_contribution.py
tradingbot/ml/research/phase14_7/monte_carlo_validator.py
tradingbot/ml/research/phase14_7/orchestrator.py
tradingbot/ml/research/phase14_7/performance_analyzer.py
tradingbot/ml/research/phase14_7/pipeline_runner.py
tradingbot/ml/research/phase14_7/quality_adapter.py
tradingbot/ml/research/phase14_7/regime_analyzer.py
tradingbot/ml/research/phase14_7/report_generator.py
tradingbot/ml/research/phase14_7/risk_adapter.py
tradingbot/ml/research/phase14_7/router_runner.py
tradingbot/ml/research/phase14_7/trade_tracker.py
tradingbot/ml/research/phase14_7/walk_forward_validator.py
tradingbot/ml/research/phase15i/__init__.py
tradingbot/ml/research/phase15i/recovery_adapter.py
tradingbot/ml/research/phase17b/__init__.py
tradingbot/ml/research/phase17b/config.py
tradingbot/ml/research/phase17b/dataset.py
tradingbot/ml/research/phase17b/research_engine.py
tradingbot/ml/research/phase17b/research_model.py
tradingbot/ml/research/phase17b/shadow_replay.py
tradingbot/ml/research/phase17b/top5_features.py
tradingbot/ml/research/phase17b/training_lab.py
tradingbot/ml/research/phase22c/__init__.py
tradingbot/ml/research/phase22c/config.py
tradingbot/ml/research/phase22c/hold_chain.py
tradingbot/ml/research/phase22c/thresholds.py
tradingbot/ml/research/phase22e/__init__.py
tradingbot/ml/research/phase22e/metrics.py
tradingbot/ml/research/phase26b/__init__.py
tradingbot/ml/research/phase26b/analyzers.py
tradingbot/ml/research/phase26b/data_loader.py
tradingbot/ml/research/phase26b/run_investigation.py
tradingbot/ml/research/phase35/__init__.py
tradingbot/ml/research/phase35/label_alignment.py
tradingbot/ml/research/phase36/__init__.py
tradingbot/ml/research/phase36/build_dataset_v3.py
tradingbot/ml/research/phase39/candle_sources.py
tradingbot/ml/research/phase39/expand_dataset.py
tradingbot/ml/research/ranking.py
tradingbot/ml/research/regime_detector/__init__.py
tradingbot/ml/research/regime_detector/orchestrator.py
tradingbot/ml/research/regime_detector/regime_classifier.py
tradingbot/ml/research/regime_detector/regime_features.py
tradingbot/ml/research/regime_detector/regime_optimizer.py
tradingbot/ml/research/regime_detector/regime_report.py
tradingbot/ml/research/regime_detector/regime_validator.py
tradingbot/ml/research/regime_optimization/__init__.py
tradingbot/ml/research/regime_optimization/event_filter_optimizer.py
tradingbot/ml/research/regime_optimization/optimization_orchestrator.py
tradingbot/ml/research/regime_optimization/regime_detector.py
tradingbot/ml/research/regime_optimization/regime_model_optimizer.py
tradingbot/ml/research/regime_optimization/regime_utils.py
tradingbot/ml/research/regime_optimization/stable_feature_selector.py
tradingbot/ml/research/regime_optimization/walk_forward_validator.py
tradingbot/ml/research/regime_router/__init__.py
tradingbot/ml/research/regime_router/config.py
tradingbot/ml/research/regime_router/phase99_feature_validation.py
tradingbot/ml/research/regime_router/range_engine_adapter.py
tradingbot/ml/research/regime_router/regime_performance.py
tradingbot/ml/research/regime_router/regime_router.py
tradingbot/ml/research/regime_router/report_generator.py
tradingbot/ml/research/regime_router/router_validator.py
tradingbot/ml/research/regime_router/signal_aggregator.py
tradingbot/ml/research/regime_router/trend_engine_adapter.py
tradingbot/ml/research/regime_router/unified_feature_input.py
tradingbot/ml/research/regime_router/walk_forward_router.py
tradingbot/ml/research/reports.py
tradingbot/ml/research/reproducibility.py
tradingbot/ml/research/research_utils.py
tradingbot/ml/research/retrain_optimizer.py
tradingbot/ml/research/retrain_report.py
tradingbot/ml/research/robustness_optimizer/__init__.py
tradingbot/ml/research/robustness_optimizer/candidate_selector.py
tradingbot/ml/research/robustness_optimizer/freeze_bridge.py
tradingbot/ml/research/robustness_optimizer/model_regularization.py
tradingbot/ml/research/robustness_optimizer/optimization_orchestrator.py
tradingbot/ml/research/robustness_optimizer/probability_selection_gate.py
tradingbot/ml/research/robustness_optimizer/regime_robustness.py
tradingbot/ml/research/robustness_optimizer/report_generator.py
tradingbot/ml/research/robustness_optimizer/stable_feature_research.py
tradingbot/ml/research/robustness_optimizer/walk_forward_optimizer.py
tradingbot/ml/research/robustness_optimizer/window_validator.py
tradingbot/ml/research/router_optimizer/__init__.py
tradingbot/ml/research/router_optimizer/confidence_optimizer.py
tradingbot/ml/research/router_optimizer/engine_cache.py
tradingbot/ml/research/router_optimizer/failure_analyzer.py
tradingbot/ml/research/router_optimizer/optimizer_types.py
tradingbot/ml/research/router_optimizer/orchestrator.py
tradingbot/ml/research/router_optimizer/regime_weight_optimizer.py
tradingbot/ml/research/router_optimizer/report_generator.py
tradingbot/ml/research/router_optimizer/robustness_validator.py
tradingbot/ml/research/router_optimizer/router_optimizer.py
tradingbot/ml/research/router_optimizer/session_optimizer.py
tradingbot/ml/research/router_optimizer/threshold_optimizer.py
tradingbot/ml/research/router_optimizer/trade_filter_optimizer.py
tradingbot/ml/research/router_optimizer/walk_forward_optimizer.py
tradingbot/ml/research/schema.py
tradingbot/ml/research/trend_ml/__init__.py
tradingbot/ml/research/trend_ml/feature_builder.py
tradingbot/ml/research/trend_ml/label_builder.py
tradingbot/ml/research/trend_ml/models.py
tradingbot/ml/research/trend_ml/optimizer.py
tradingbot/ml/research/trend_ml/report.py
tradingbot/ml/research/trend_ml/trend_ml_filter.py
tradingbot/ml/research/trend_ml/validator.py
tradingbot/ml/research/trend_strategy/__init__.py
tradingbot/ml/research/trend_strategy/report.py
tradingbot/ml/research/trend_strategy/trend_backtest.py
tradingbot/ml/research/trend_strategy/trend_features.py
tradingbot/ml/research/trend_strategy/trend_rules.py
tradingbot/ml/research/trend_strategy/trend_signal.py
tradingbot/ml/research/trend_strategy/walk_forward.py
tradingbot/ml/research/walk_forward/__init__.py
tradingbot/ml/research/walk_forward/model_validator.py
tradingbot/ml/research/walk_forward/report_generator.py
tradingbot/ml/research/walk_forward/robustness_analyzer.py
tradingbot/ml/research/walk_forward/walk_forward_engine.py
tradingbot/ml/research/walk_forward/walk_forward_metrics.py
tradingbot/ml/research/walk_forward/window_manager.py
tradingbot/ml/risk_intelligence/__init__.py
tradingbot/ml/risk_intelligence/adaptive_risk_engine.py
tradingbot/ml/risk_intelligence/confidence_risk_mapper.py
tradingbot/ml/risk_intelligence/drawdown_controller.py
tradingbot/ml/risk_intelligence/engine_performance.py
tradingbot/ml/risk_intelligence/regime_risk_adjuster.py
tradingbot/ml/risk_intelligence/risk_policy.py
tradingbot/ml/risk_intelligence/risk_trace.py
tradingbot/ml/risk_intelligence/risk_types.py
tradingbot/ml/risk_intelligence/session_risk_adjuster.py
tradingbot/ml/risk_intelligence/validator.py
tradingbot/ml/risk_intelligence/volatility_risk_adjuster.py
tradingbot/ml/shadow/__init__.py
tradingbot/ml/shadow/config.py
tradingbot/ml/shadow/decision_logger.py
tradingbot/ml/shadow/kernel_bridge.py
tradingbot/ml/shadow/ml_adapter.py
tradingbot/ml/shadow/phase49a_gate.py
tradingbot/ml/shadow/phase49a_metrics.py
tradingbot/ml/shadow/phase_d_metrics.py
tradingbot/ml/shadow/shadow_engine.py
tradingbot/ml/shadow/shadow_gate.py
tradingbot/ml/shadow/shadow_live_sync.py
tradingbot/ml/shadow/shadow_logger.py
tradingbot/ml/shadow/shadow_metrics.py
tradingbot/ml/shadow/shadow_observer.py
tradingbot/ml/shadow/shadow_signal.py
tradingbot/ml/trade_quality/__init__.py
tradingbot/ml/trade_quality/adapter.py
tradingbot/ml/trade_quality/engine_history.py
tradingbot/ml/trade_quality/liquidity_quality.py
tradingbot/ml/trade_quality/quality_engine.py
tradingbot/ml/trade_quality/quality_policy.py
tradingbot/ml/trade_quality/quality_types.py
tradingbot/ml/trade_quality/regime_quality.py
tradingbot/ml/trade_quality/rr_quality.py
tradingbot/ml/trade_quality/signal_quality.py
tradingbot/ml/trade_quality/timing_quality.py
tradingbot/ml/trade_quality/volatility_quality.py
tradingbot/ml/training/__init__.py
tradingbot/ml/training/data_loader.py
tradingbot/ml/training/evaluation.py
tradingbot/ml/training/feature_pipeline.py
tradingbot/ml/training/model_factory.py
tradingbot/ml/training/model_registry.py
tradingbot/ml/training/phase9_production.py
tradingbot/ml/training/train_state.py
tradingbot/ml/training/trainer.py
tradingbot/ml/validation/__init__.py
tradingbot/ml/validation/_utils.py
tradingbot/ml/validation/calibration.py
tradingbot/ml/validation/cross_validation.py
tradingbot/ml/validation/feature_ablation.py
tradingbot/ml/validation/regime_test.py
tradingbot/ml/validation/report.py
tradingbot/ml/validation/robustness.py
tradingbot/ml/validation/threshold_optimizer.py
tradingbot/ml/validation/trading_simulator.py
tradingbot/ml/validation/walk_forward.py
tradingbot/pipeline/__init__.py
tradingbot/pipeline/base.py
tradingbot/pipeline/data_stage.py
tradingbot/pipeline/execution_stage.py
tradingbot/pipeline/indicator_stage.py
tradingbot/pipeline/risk_stage.py
tradingbot/pipeline/signal_filter_stage.py
tradingbot/pipeline/signal_stage.py
tradingbot/ports/__init__.py
tradingbot/ports/execution.py
tradingbot/ports/indicators.py
tradingbot/ports/market_data.py
tradingbot/ports/position_manager.py
tradingbot/ports/risk.py
tradingbot/ports/storage.py
tradingbot/ports/strategies.py
tradingbot/services/__init__.py
tradingbot/services/daily_engine_report.py
tradingbot/services/demo_account_guard.py
tradingbot/services/drift_monitor.py
tradingbot/services/emergency_stop_state.py
tradingbot/services/engine_telemetry.py
tradingbot/services/execution_mode.py
tradingbot/services/exit_mode.py
tradingbot/services/exit_policy.py
tradingbot/services/jsonl_rotation.py
tradingbot/services/kill_switch.py
tradingbot/services/live_loop_health.py
tradingbot/services/live_ops_service.py
tradingbot/services/live_reporting.py
tradingbot/services/live_risk_tracker.py
tradingbot/services/manual_stop.py
tradingbot/services/meta_decision_log.py
tradingbot/services/meta_labeler.py
tradingbot/services/mt5_order_guard.py
tradingbot/services/notifier.py
tradingbot/services/pa_production_lock.py
tradingbot/services/paper_fill_resolver.py
tradingbot/services/paper_trade_exit.py
tradingbot/services/paper_trade_recorder.py
tradingbot/services/phase47c_forward_tracker.py
tradingbot/services/phase51a_forward_cert.py
tradingbot/services/position_protector.py
tradingbot/services/position_recovery_service.py
tradingbot/services/rejection_events.py
tradingbot/services/router_decision_log.py
tradingbot/services/runtime_truth.py
tradingbot/services/signal_filter_log.py
tradingbot/services/signal_filter_mode.py
tradingbot/services/startup_validator.py
tradingbot/services/trade_journal.py
tradingbot/services/winner_population_signal_quality_filter.py
tradingbot/services/wpsqf_calibration.py
tradingbot/services/wpsqf_features.py
tradingbot/services/wpsqf_scoring.py
tradingbot/strategies/__init__.py
tradingbot/strategies/adaptive_quality_engine.py
tradingbot/strategies/adaptive_regime.py
tradingbot/strategies/vol_regime_signal.py
```

### 2.3 TEST_ONLY (reachable via tests, not runtime entries)

_894 files_

```
engine/strategies/price_action_strategy.py
scripts/generate_dashboard_live_html.py
scripts/hta_html_fragments.py
tradingbot/backtest/bidask_ingestion.py
tradingbot/backtest/bidask_validation.py
tradingbot/backtest/commission_policy.py
tradingbot/backtest/cost_evidence_audit.py
tradingbot/backtest/cost_evidence_schema.py
tradingbot/backtest/historical_bidask.py
tradingbot/backtest/mt5_readonly_evidence.py
tradingbot/backtest/operator_evidence.py
tradingbot/backtest/optimization_gate.py
tradingbot/backtest/phase100_retrace_expansion_forensics.py
tradingbot/backtest/phase101_entry_vs_exit.py
tradingbot/backtest/phase102_cluster_timing_forensics.py
tradingbot/backtest/phase103_structure_at_retracement.py
tradingbot/backtest/phase104_minimal_discriminator.py
tradingbot/backtest/phase105_discriminator_gate.py
tradingbot/backtest/phase106_non_ohlc_data_inventory.py
tradingbot/backtest/phase107_tick_intrabar_research.py
tradingbot/backtest/phase108_spread_path_research.py
tradingbot/backtest/phase109_htf_context_research.py
tradingbot/backtest/phase110_news_context_research.py
tradingbot/backtest/phase111_multisource_alignment.py
tradingbot/backtest/phase112_non_ohlc_discriminator_gate.py
tradingbot/backtest/phase113_non_ohlc_final_gate.py
tradingbot/backtest/phase114_non_ohlc_acquisition_contract.py
tradingbot/backtest/phase115_non_ohlc_data_acquisition.py
tradingbot/backtest/phase116_data_source_research.py
tradingbot/backtest/phase117_operator_source_resolution.py
tradingbot/backtest/phase25f_run.py
tradingbot/backtest/phase25g_run.py
tradingbot/backtest/phase25h_run.py
tradingbot/backtest/phase25j_run.py
tradingbot/backtest/phase25k_run.py
tradingbot/backtest/phase25l_run.py
tradingbot/backtest/phase25m_run.py
tradingbot/backtest/phase26_validation_audit.py
tradingbot/backtest/phase26b_controlled_validation.py
tradingbot/backtest/phase26c_zero_signal_audit.py
tradingbot/backtest/phase26d_kernel_signal_trace.py
tradingbot/backtest/phase26e_riskgate_audit.py
tradingbot/backtest/phase26f_riskgate_correctness.py
tradingbot/backtest/phase26g_riskgate_counterfactual.py
tradingbot/backtest/phase26h_counterfactual_consistency.py
tradingbot/backtest/phase26i_full_tail_attribution.py
tradingbot/backtest/phase26j_decision_path_reconciliation.py
tradingbot/backtest/phase26k_full_engine_reconciliation.py
tradingbot/backtest/phase26l_riskgate_policy_audit.py
tradingbot/backtest/phase26m_operator_risk_budget_audit.py
tradingbot/backtest/phase26n_documentation_contradiction_cleanup.py
tradingbot/backtest/phase26o_legacy_docs_truth_sweep.py
tradingbot/backtest/phase26p_closure_audit.py
tradingbot/backtest/phase27_10_dataset_symbol_binding.py
tradingbot/backtest/phase27_11_historical_bidask.py
tradingbot/backtest/phase27_12_commission_evidence.py
tradingbot/backtest/phase27_13_swap_policy.py
tradingbot/backtest/phase27_14_slippage_model.py
tradingbot/backtest/phase27_15_cost_completeness_gate.py
tradingbot/backtest/phase27_16_final_validation_gate.py
tradingbot/backtest/phase27_17_real_broker_evidence.py
tradingbot/backtest/phase27_18_historical_bidask.py
tradingbot/backtest/phase27_19_commission_closure.py
tradingbot/backtest/phase27_20_dataset_mapping_closure.py
tradingbot/backtest/phase27_21_evidence_synthesis.py
tradingbot/backtest/phase27_22_commission_forensic.py
tradingbot/backtest/phase27_23_bidask_expansion.py
tradingbot/backtest/phase27_24_execution_cost_forensics.py
tradingbot/backtest/phase27_25_canonical_bidask_coverage.py
tradingbot/backtest/phase27_26_canonical_bidask_coverage.py
tradingbot/backtest/phase27_27_dataset_symbol_binding.py
tradingbot/backtest/phase27_28_commission_evidence.py
tradingbot/backtest/phase27_29_swap_evidence.py
tradingbot/backtest/phase27_30_slippage_evidence.py
tradingbot/backtest/phase27_31_execution_evidence.py
tradingbot/backtest/phase27_32_final_cost_evidence_gate.py
tradingbot/backtest/phase27_33_ev_eq_resolution.py
tradingbot/backtest/phase27_5_final_broker_cost_gate.py
tradingbot/backtest/phase27_5_operator_evidence.py
tradingbot/backtest/phase27_6_final_evidence_gate.py
tradingbot/backtest/phase27_6_real_operator_evidence.py
tradingbot/backtest/phase27_7_final_blocker_closure.py
tradingbot/backtest/phase27_8_policy_lock.py
tradingbot/backtest/phase27_9_real_broker_evidence.py
tradingbot/backtest/phase27_broker_reality_audit.py
tradingbot/backtest/phase27_operator_evidence.py
tradingbot/backtest/phase28_0_performance_foundation.py
tradingbot/backtest/phase28_1_full_baseline.py
tradingbot/backtest/phase28_2_walk_forward.py
tradingbot/backtest/phase28_3_monte_carlo.py
tradingbot/backtest/phase28_4_strategy_diagnosis.py
tradingbot/backtest/phase29_research_tape.py
tradingbot/backtest/phase30_unchanged_strategy_evaluation.py
tradingbot/backtest/phase31_event_independence.py
tradingbot/backtest/phase32_walk_forward.py
tradingbot/backtest/phase33_robustness.py
tradingbot/backtest/phase34_statistical_validation.py
tradingbot/backtest/phase35_execution_reality.py
tradingbot/backtest/phase36_strategy_verdict.py
tradingbot/backtest/phase37_long_horizon_tape.py
tradingbot/backtest/phase38_intelligent_evidence_acquisition.py
tradingbot/backtest/phase39_broker_economics_execution.py
tradingbot/backtest/phase40_full_horizon_validation.py
tradingbot/backtest/phase41_final_evidence_closure.py
tradingbot/backtest/phase42_broker_cost_execution_closure.py
tradingbot/backtest/phase42_cost_reconstruction.py
tradingbot/backtest/phase43_broker_cost_execution_validation.py
tradingbot/backtest/phase44_executable_backtest_readiness.py
tradingbot/backtest/phase45_event_oos_regime_robustness.py
tradingbot/backtest/phase46_production_live_parity_audit.py
tradingbot/backtest/phase47_blocker_closure.py
tradingbot/backtest/phase48_executable_backtest.py
tradingbot/backtest/phase49_final_event_oos_validation.py
tradingbot/backtest/phase50_final_production_parity.py
tradingbot/backtest/phase51_final_evidence_closure.py
tradingbot/backtest/phase52_optimization_gate.py
tradingbot/backtest/phase53_shadow_readiness.py
tradingbot/backtest/phase54_account_broker_evidence.py
tradingbot/backtest/phase55_cost_scenario_analysis.py
tradingbot/backtest/phase56_symbol_mapping_final_gate.py
tradingbot/backtest/phase57_account_product_forensics.py
tradingbot/backtest/phase58_commission_accountability.py
tradingbot/backtest/phase59_symbol_equivalence_forensics.py
tradingbot/backtest/phase60_unified_evidence_gate.py
tradingbot/backtest/phase61_edge_survival_forensics.py
tradingbot/backtest/phase62_operator_action_economics.py
tradingbot/backtest/phase63_next_step_gate.py
tradingbot/backtest/phase64_strategy_event_forensics.py
tradingbot/backtest/phase65_diagnostic_experiments.py
tradingbot/backtest/phase66_strategy_root_cause.py
tradingbot/backtest/phase67_next_research_gate.py
tradingbot/backtest/phase68_exit_forensics.py
tradingbot/backtest/phase69_exit_geometry.py
tradingbot/backtest/phase70_exit_counterfactuals.py
tradingbot/backtest/phase71_extreme_winner_forensics.py
tradingbot/backtest/phase72_exit_root_cause.py
tradingbot/backtest/phase73_exit_research_gate.py
tradingbot/backtest/phase74_profit_giveback_forensics.py
tradingbot/backtest/phase75_exit_counterfactuals.py
tradingbot/backtest/phase76_sl_vs_profit_protection.py
tradingbot/backtest/phase77_exit_geometry_forensics.py
tradingbot/backtest/phase78_time_exit_forensics.py
tradingbot/backtest/phase79_exit_side_regime.py
tradingbot/backtest/phase80_extreme_winner_audit.py
tradingbot/backtest/phase81_exit_research_gate.py
tradingbot/backtest/phase82_profit_protection_design.py
tradingbot/backtest/phase83_profit_protection_counterfactuals.py
tradingbot/backtest/phase84_tail_preservation.py
tradingbot/backtest/phase85_rescue_vs_destruction.py
tradingbot/backtest/phase86_profit_protection_oos.py
tradingbot/backtest/phase87_profit_protection_interactions.py
tradingbot/backtest/phase88_exit_design_spec.py
tradingbot/backtest/phase89_profit_protection_gate.py
tradingbot/backtest/phase90_profit_giveback_path_forensics.py
tradingbot/backtest/phase91_reversal_timing_forensics.py
tradingbot/backtest/phase92_mfe_mae_conditional_forensics.py
tradingbot/backtest/phase93_tail_preservation_forensics.py
tradingbot/backtest/phase94_cluster_forensics.py
tradingbot/backtest/phase95_protection_family_v2.py
tradingbot/backtest/phase96_protection_robustness_gate.py
tradingbot/backtest/phase97_profit_protection_final_gate.py
tradingbot/backtest/phase98_first_favorable_state.py
tradingbot/backtest/phase99_path_velocity_persistence.py
tradingbot/backtest/request_fill_telemetry.py
tradingbot/backtest/shadow_observation.py
tradingbot/backtest/slippage_policy.py
tradingbot/backtest/swap_policy.py
tradingbot/backtest/symbol_equivalence.py
tradingbot/domain/gold_strategies/__init__.py
tradingbot/domain/gold_strategies/h4_swing.py
tradingbot/domain/gold_strategies/m15_intraday.py
tradingbot/domain/gold_strategies/m5_london_sweep.py
tradingbot/domain/gold_strategies/m5_scalp.py
tradingbot/domain/gold_strategies/router.py
tradingbot/domain/order_logic.py
tradingbot/domain/pa_hardening.py
tradingbot/execution/__init__.py
tradingbot/execution/execution_costs.py
tradingbot/execution/execution_latency.py
tradingbot/execution/execution_models.py
tradingbot/execution/execution_simulator.py
tradingbot/execution/fill_model.py
tradingbot/execution/liquidity_model.py
tradingbot/execution/market_impact.py
tradingbot/execution/order_queue.py
tradingbot/ml/abtest/__init__.py
tradingbot/ml/abtest/comparator.py
tradingbot/ml/abtest/logger.py
tradingbot/ml/abtest/metrics.py
tradingbot/ml/abtest/report.py
tradingbot/ml/abtest/schema.py
tradingbot/ml/audit/phase12_1/__init__.py
tradingbot/ml/audit/phase12_1/contribution_analyzer.py
tradingbot/ml/audit/phase12_1/dependency_analyzer.py
tradingbot/ml/audit/phase12_1/regime_strategy_analysis.py
tradingbot/ml/audit/phase12_1/replay_analyzer.py
tradingbot/ml/audit/phase12_1/report_generator.py
tradingbot/ml/audit/phase12_1/signal_tracer.py
tradingbot/ml/audit/phase12_1/strategy_discovery.py
tradingbot/ml/backtest/broker_simulator.py
tradingbot/ml/dataset/release_manager.py
tradingbot/ml/dataset/research_audit.py
tradingbot/ml/dataset/session_analysis.py
tradingbot/ml/deployment/__init__.py
tradingbot/ml/deployment/deployment_policy.py
tradingbot/ml/deployment/kill_switch.py
tradingbot/ml/deployment/live_readiness_engine.py
tradingbot/ml/deployment/logger.py
tradingbot/ml/deployment/readiness_scoring.py
tradingbot/ml/deployment/risk_gates.py
tradingbot/ml/deployment/schema.py
tradingbot/ml/deployment/shadow_validation.py
tradingbot/ml/deployment/stability_checker.py
tradingbot/ml/feature_alignment/orchestrator.py
tradingbot/ml/feature_alignment/validator.py
tradingbot/ml/features/align.py
tradingbot/ml/improvement/__init__.py
tradingbot/ml/improvement/analyzer.py
tradingbot/ml/improvement/experiment_queue.py
tradingbot/ml/improvement/feature_optimizer.py
tradingbot/ml/improvement/model_optimizer.py
tradingbot/ml/improvement/recommendation.py
tradingbot/ml/improvement/regime_optimizer.py
tradingbot/ml/improvement/reports.py
tradingbot/ml/improvement/schema.py
tradingbot/ml/improvement/threshold_optimizer.py
tradingbot/ml/infrastructure/__init__.py
tradingbot/ml/infrastructure/audit/__init__.py
tradingbot/ml/infrastructure/audit/audit_logger.py
tradingbot/ml/infrastructure/config/__init__.py
tradingbot/ml/infrastructure/config/runtime_config.py
tradingbot/ml/infrastructure/diagnostics/__init__.py
tradingbot/ml/infrastructure/diagnostics/diagnostic_report.py
tradingbot/ml/infrastructure/health/__init__.py
tradingbot/ml/infrastructure/health/health_checker.py
tradingbot/ml/infrastructure/health/schema.py
tradingbot/ml/infrastructure/recovery/__init__.py
tradingbot/ml/infrastructure/recovery/recovery_manager.py
tradingbot/ml/infrastructure/versioning/__init__.py
tradingbot/ml/infrastructure/versioning/model_version.py
tradingbot/ml/integration/phase15b_orchestrator.py
tradingbot/ml/integration/replay_validator.py
tradingbot/ml/live_gate/__init__.py
tradingbot/ml/live_gate/gate_engine.py
tradingbot/ml/live_gate/logger.py
tradingbot/ml/live_gate/safety_guard.py
tradingbot/ml/live_gate/schema.py
tradingbot/ml/live_gate/shadow_router.py
tradingbot/ml/live_pilot/__init__.py
tradingbot/ml/live_pilot/config.py
tradingbot/ml/live_pilot/execution_guard.py
tradingbot/ml/live_pilot/health_check.py
tradingbot/ml/live_pilot/kill_switch.py
tradingbot/ml/live_pilot/latency_tracker.py
tradingbot/ml/live_pilot/live_controller.py
tradingbot/ml/live_pilot/live_monitor.py
tradingbot/ml/live_pilot/position_limiter.py
tradingbot/ml/live_pilot/safety_manager.py
tradingbot/ml/live_pilot/slippage_tracker.py
tradingbot/ml/live_pilot/trade_journal.py
tradingbot/ml/live_validation/__init__.py
tradingbot/ml/live_validation/config.py
tradingbot/ml/live_validation/decision_compare.py
tradingbot/ml/live_validation/latency_monitor.py
tradingbot/ml/live_validation/live_health.py
tradingbot/ml/live_validation/orchestrator.py
tradingbot/ml/live_validation/report_generator.py
tradingbot/ml/live_validation/risk_compare.py
tradingbot/ml/live_validation/shadow_equity.py
tradingbot/ml/live_validation/shadow_mode.py
tradingbot/ml/live_validation/shadow_statistics.py
tradingbot/ml/live_validation/shadow_trade.py
tradingbot/ml/live_validation/signal_consistency.py
tradingbot/ml/live_validation/validator.py
tradingbot/ml/monitoring/alerts.py
tradingbot/ml/monitoring/anomaly_detector.py
tradingbot/ml/monitoring/dashboard_data.py
tradingbot/ml/monitoring/dashboard_export.py
tradingbot/ml/monitoring/degradation.py
tradingbot/ml/monitoring/drift.py
tradingbot/ml/monitoring/health.py
tradingbot/ml/monitoring/long_run_manager.py
tradingbot/ml/monitoring/orchestrator.py
tradingbot/ml/monitoring/performance_tracker.py
tradingbot/ml/monitoring/reports.py
tradingbot/ml/monitoring/session_report.py
tradingbot/ml/monitoring/shadow_monitor.py
tradingbot/ml/monitoring/stability_analyzer.py
tradingbot/ml/optimization/__init__.py
tradingbot/ml/optimization/_sim.py
tradingbot/ml/optimization/filters.py
tradingbot/ml/optimization/optimizer.py
tradingbot/ml/optimization/recommendation.py
tradingbot/ml/optimization/reports.py
tradingbot/ml/optimization/schema.py
tradingbot/ml/optimization/threshold.py
tradingbot/ml/optimization/weights.py
tradingbot/ml/orchestrator/__init__.py
tradingbot/ml/orchestrator/confidence_router.py
tradingbot/ml/orchestrator/decision_engine.py
tradingbot/ml/orchestrator/ensemble.py
tradingbot/ml/orchestrator/explain.py
tradingbot/ml/orchestrator/logger.py
tradingbot/ml/orchestrator/regime_gate.py
tradingbot/ml/orchestrator/risk_adjustment.py
tradingbot/ml/orchestrator/schema.py
tradingbot/ml/orchestrator/signals.py
tradingbot/ml/orchestrator/strategy_selector.py
tradingbot/ml/paper/__init__.py
tradingbot/ml/paper/_types.py
tradingbot/ml/paper/broker_sim.py
tradingbot/ml/paper/config.py
tradingbot/ml/paper/daily_report.py
tradingbot/ml/paper/engine.py
tradingbot/ml/paper/latency_model.py
tradingbot/ml/paper/metrics.py
tradingbot/ml/paper/paper_engine.py
tradingbot/ml/paper/paper_execution.py
tradingbot/ml/paper/performance.py
tradingbot/ml/paper/portfolio.py
tradingbot/ml/paper/portfolio_manager.py
tradingbot/ml/paper/session_analyzer.py
tradingbot/ml/paper/slippage_model.py
tradingbot/ml/paper/spread_model.py
tradingbot/ml/paper/trade_executor.py
tradingbot/ml/paper/trade_lifecycle.py
tradingbot/ml/paper/virtual_account.py
tradingbot/ml/paper/walk_forward_runner.py
tradingbot/ml/performance/__init__.py
tradingbot/ml/performance/benchmark.py
tradingbot/ml/performance/memory.py
tradingbot/ml/performance/optimization.py
tradingbot/ml/performance/profiler.py
tradingbot/ml/performance/report.py
tradingbot/ml/performance/schema.py
tradingbot/ml/performance/stress_latency.py
tradingbot/ml/phase15e_debug/__init__.py
tradingbot/ml/phase15e_debug/confidence_analysis.py
tradingbot/ml/phase15e_debug/config.py
tradingbot/ml/phase15e_debug/legacy_diff.py
tradingbot/ml/phase15e_debug/orchestrator.py
tradingbot/ml/phase15e_debug/regime_analysis.py
tradingbot/ml/phase15e_debug/report_generator.py
tradingbot/ml/phase15e_debug/root_cause.py
tradingbot/ml/phase15e_debug/signal_funnel.py
tradingbot/ml/phase15e_debug/stage_probe.py
tradingbot/ml/phase15f/__init__.py
tradingbot/ml/phase15f/bundle_audit.py
tradingbot/ml/phase15f/confidence_trace.py
tradingbot/ml/phase15f/config.py
tradingbot/ml/phase15f/decision_policy_audit.py
tradingbot/ml/phase15f/orchestrator.py
tradingbot/ml/phase15f/pipeline_compare.py
tradingbot/ml/phase15f/recovery_validator.py
tradingbot/ml/phase15f/report_generator.py
tradingbot/ml/phase18b/__init__.py
tradingbot/ml/phase18b/checklist.py
tradingbot/ml/phase18b/config.py
tradingbot/ml/phase18b/failure_injection.py
tradingbot/ml/phase18b/health.py
tradingbot/ml/phase18b/live_safety.py
tradingbot/ml/phase18b/operational.py
tradingbot/ml/phase18b/orchestrator.py
tradingbot/ml/phase18b/production_audit.py
tradingbot/ml/phase18b/rollback.py
tradingbot/ml/phase18b/stability.py
tradingbot/ml/phase18b/verdict.py
tradingbot/ml/phase18c/__init__.py
tradingbot/ml/phase18c/bundles.py
tradingbot/ml/phase18c/checklist.py
tradingbot/ml/phase18c/config.py
tradingbot/ml/phase18c/configuration.py
tradingbot/ml/phase18c/engines.py
tradingbot/ml/phase18c/environment.py
tradingbot/ml/phase18c/mt5_check.py
tradingbot/ml/phase18c/orchestrator.py
tradingbot/ml/phase18c/shutdown.py
tradingbot/ml/phase18c/startup.py
tradingbot/ml/phase18c/verdict.py
tradingbot/ml/phase19a/__init__.py
tradingbot/ml/phase19a/backtest.py
tradingbot/ml/phase19a/capital.py
tradingbot/ml/phase19a/config.py
tradingbot/ml/phase19a/drawdown.py
tradingbot/ml/phase19a/metrics.py
tradingbot/ml/phase19a/orchestrator.py
tradingbot/ml/phase19a/regime_analysis.py
tradingbot/ml/phase19a/robustness.py
tradingbot/ml/phase19a/scoring.py
tradingbot/ml/phase19a/symbol_analysis.py
tradingbot/ml/phase19a/trade_quality.py
tradingbot/ml/phase19a/verdict.py
tradingbot/ml/phase19c/backtest.py
tradingbot/ml/phase19c/montecarlo.py
tradingbot/ml/phase19c/rollback.py
tradingbot/ml/phase19c/verdict.py
tradingbot/ml/phase19c/walkforward.py
tradingbot/ml/phase19d/__init__.py
tradingbot/ml/phase19d/audit.py
tradingbot/ml/phase19d/capital.py
tradingbot/ml/phase19d/certification.py
tradingbot/ml/phase19d/config.py
tradingbot/ml/phase19d/deployment.py
tradingbot/ml/phase19d/live_safety.py
tradingbot/ml/phase19d/montecarlo.py
tradingbot/ml/phase19d/orchestrator.py
tradingbot/ml/phase19d/scoring.py
tradingbot/ml/phase19d/stress_test.py
tradingbot/ml/phase19d/verdict.py
tradingbot/ml/phase19d/walkforward.py
tradingbot/ml/phase20a/__init__.py
tradingbot/ml/phase20a/certification_gate.py
tradingbot/ml/phase20a/config.py
tradingbot/ml/phase20a/deployment_runner.py
tradingbot/ml/phase20a/execution_guard.py
tradingbot/ml/phase20a/kernel_observer.py
tradingbot/ml/phase20a/orchestrator.py
tradingbot/ml/phase20a/reporter.py
tradingbot/ml/phase20a/rollback.py
tradingbot/ml/phase20a/safety_monitor.py
tradingbot/ml/phase20a/strategy_registry.py
tradingbot/ml/phase20b/__init__.py
tradingbot/ml/phase20b/capital.py
tradingbot/ml/phase20b/config.py
tradingbot/ml/phase20b/drawdown.py
tradingbot/ml/phase20b/execution.py
tradingbot/ml/phase20b/filters.py
tradingbot/ml/phase20b/health.py
tradingbot/ml/phase20b/live_data.py
tradingbot/ml/phase20b/orchestrator.py
tradingbot/ml/phase20b/performance.py
tradingbot/ml/phase20b/risk_suggestions.py
tradingbot/ml/phase20b/trade_quality.py
tradingbot/ml/phase20b/verdict.py
tradingbot/ml/phase20c/__init__.py
tradingbot/ml/phase20c/broker_data.py
tradingbot/ml/phase20c/broker_quality.py
tradingbot/ml/phase20c/config.py
tradingbot/ml/phase20c/execution_audit.py
tradingbot/ml/phase20c/latency.py
tradingbot/ml/phase20c/orchestrator.py
tradingbot/ml/phase20c/risk_validation.py
tradingbot/ml/phase20c/scoring.py
tradingbot/ml/phase20c/simulation_compare.py
tradingbot/ml/phase20c/slippage.py
tradingbot/ml/phase20c/spread.py
tradingbot/ml/phase20c/stability.py
tradingbot/ml/phase20c/verdict.py
tradingbot/ml/research/advanced_discovery/__init__.py
tradingbot/ml/research/advanced_discovery/experiment_runner.py
tradingbot/ml/research/advanced_discovery/experimental_features.py
tradingbot/ml/research/advanced_discovery/feature_discovery.py
tradingbot/ml/research/advanced_discovery/label_discovery.py
tradingbot/ml/research/advanced_discovery/model_discovery.py
tradingbot/ml/research/advanced_discovery/signal_mining.py
tradingbot/ml/research/documentation_consistency/__init__.py
tradingbot/ml/research/documentation_consistency/run.py
tradingbot/ml/research/documentation_consistency/scanner.py
tradingbot/ml/research/documentation_freshness/__init__.py
tradingbot/ml/research/documentation_freshness/scanner.py
tradingbot/ml/research/documentation_memory_hardening/__init__.py
tradingbot/ml/research/documentation_memory_hardening/baseline.py
tradingbot/ml/research/documentation_memory_hardening/memory_integrity.py
tradingbot/ml/research/documentation_memory_hardening_v2/__init__.py
tradingbot/ml/research/documentation_memory_hardening_v2/load_path.py
tradingbot/ml/research/documentation_memory_hardening_v2/run.py
tradingbot/ml/research/documentation_operationalization/run.py
tradingbot/ml/research/documentation_system_audit/__init__.py
tradingbot/ml/research/documentation_system_audit/run.py
tradingbot/ml/research/documentation_verification/run.py
tradingbot/ml/research/feature_importance_analysis.py
tradingbot/ml/research/full_repo_audit/run.py
tradingbot/ml/research/model_optimizer.py
tradingbot/ml/research/pa_live_audit/__init__.py
tradingbot/ml/research/pa_live_audit/classify.py
tradingbot/ml/research/pa_live_audit/parity.py
tradingbot/ml/research/pa_live_audit/path.py
tradingbot/ml/research/pa_live_audit/replay.py
tradingbot/ml/research/phase13_10/__init__.py
tradingbot/ml/research/phase13_10/config.py
tradingbot/ml/research/phase13_10/monte_carlo.py
tradingbot/ml/research/phase13_10/orchestrator.py
tradingbot/ml/research/phase13_10/report_generator.py
tradingbot/ml/research/phase13_10/robust_score.py
tradingbot/ml/research/phase13_10/router_policy.py
tradingbot/ml/research/phase13_10/rule_comparator.py
tradingbot/ml/research/phase13_10/threshold_optimizer.py
tradingbot/ml/research/phase13_10/trend_audit/__init__.py
tradingbot/ml/research/phase13_10/trend_audit/funnel_analyzer.py
tradingbot/ml/research/phase13_10/trend_engines.py
tradingbot/ml/research/phase13_10/walk_forward.py
tradingbot/ml/research/phase13_7/__init__.py
tradingbot/ml/research/phase13_7/config.py
tradingbot/ml/research/phase13_7/initial_audit.py
tradingbot/ml/research/phase13_7/monte_carlo_validator.py
tradingbot/ml/research/phase13_7/orchestrator.py
tradingbot/ml/research/phase13_7/range_failure_analyzer.py
tradingbot/ml/research/phase13_7/report_generator.py
tradingbot/ml/research/phase13_7/robust_score.py
tradingbot/ml/research/phase13_7/router_recalibrator.py
tradingbot/ml/research/phase13_7/stability_optimizer.py
tradingbot/ml/research/phase13_7/trade_constraints.py
tradingbot/ml/research/phase13_7/trend_router_debugger.py
tradingbot/ml/research/phase13_7/walk_forward_validator.py
tradingbot/ml/research/phase14_10/__init__.py
tradingbot/ml/research/phase14_10/adaptive_regime_policy.py
tradingbot/ml/research/phase14_10/adaptive_threshold_research.py
tradingbot/ml/research/phase14_10/config.py
tradingbot/ml/research/phase14_10/montecarlo_per_year.py
tradingbot/ml/research/phase14_10/orchestrator.py
tradingbot/ml/research/phase14_10/regime_transition_analysis.py
tradingbot/ml/research/phase14_10/report_generator.py
tradingbot/ml/research/phase14_10/robustness_rebuilder.py
tradingbot/ml/research/phase14_10/yearly_calibration_analysis.py
tradingbot/ml/research/phase14_10/yearly_confidence_distribution.py
tradingbot/ml/research/phase14_10/yearly_feature_drift.py
tradingbot/ml/research/phase14_10/yearly_performance.py
tradingbot/ml/research/phase14_10/yearly_regime_distribution.py
tradingbot/ml/research/phase14_10/yearly_threshold_analysis.py
tradingbot/ml/research/phase14_10/yearly_trade_distribution.py
tradingbot/ml/research/phase14_5/__init__.py
tradingbot/ml/research/phase14_5/adaptive_threshold_optimizer.py
tradingbot/ml/research/phase14_5/confidence_sweep.py
tradingbot/ml/research/phase14_5/config.py
tradingbot/ml/research/phase14_5/monte_carlo_validator.py
tradingbot/ml/research/phase14_5/opportunity_analyzer.py
tradingbot/ml/research/phase14_5/orchestrator.py
tradingbot/ml/research/phase14_5/pipeline_runner.py
tradingbot/ml/research/phase14_5/regime_threshold_optimizer.py
tradingbot/ml/research/phase14_5/report_generator.py
tradingbot/ml/research/phase14_5/walk_forward_validator.py
tradingbot/ml/research/phase14_8/__init__.py
tradingbot/ml/research/phase14_8/confidence_audit.py
tradingbot/ml/research/phase14_8/config.py
tradingbot/ml/research/phase14_8/drawdown_analyzer.py
tradingbot/ml/research/phase14_8/monte_carlo_extended.py
tradingbot/ml/research/phase14_8/multi_period_validator.py
tradingbot/ml/research/phase14_8/orchestrator.py
tradingbot/ml/research/phase14_8/range_engine_audit.py
tradingbot/ml/research/phase14_8/regime_stress_test.py
tradingbot/ml/research/phase14_8/report_generator.py
tradingbot/ml/research/phase14_8/risk_audit.py
tradingbot/ml/research/phase14_8/stress_runner.py
tradingbot/ml/research/phase14_8/trend_engine_audit.py
tradingbot/ml/research/phase14_8/walk_forward_extended.py
tradingbot/ml/research/phase14_9/__init__.py
tradingbot/ml/research/phase14_9/adaptive_router.py
tradingbot/ml/research/phase14_9/config.py
tradingbot/ml/research/phase14_9/dynamic_engine_weight.py
tradingbot/ml/research/phase14_9/orchestrator.py
tradingbot/ml/research/phase14_9/range_engine_analysis.py
tradingbot/ml/research/phase14_9/regime_performance_audit.py
tradingbot/ml/research/phase14_9/report_generator.py
tradingbot/ml/research/phase14_9/robustness_validator.py
tradingbot/ml/research/phase14_9/trend_engine_stability.py
tradingbot/ml/research/phase15g/__init__.py
tradingbot/ml/research/phase15g/bundle_probability_audit.py
tradingbot/ml/research/phase15g/bundle_statistics.py
tradingbot/ml/research/phase15g/confidence_ceiling.py
tradingbot/ml/research/phase15g/confidence_recovery.py
tradingbot/ml/research/phase15g/config.py
tradingbot/ml/research/phase15g/orchestrator.py
tradingbot/ml/research/phase15g/platt_curve_analysis.py
tradingbot/ml/research/phase15g/production_replay.py
tradingbot/ml/research/phase15g/report_generator.py
tradingbot/ml/research/phase15g/research_vs_bundle.py
tradingbot/ml/research/phase15g/risk_gate_simulator.py
tradingbot/ml/research/phase15g/threshold_equivalence.py
tradingbot/ml/research/phase15g/validator.py
tradingbot/ml/research/phase15i/config.py
tradingbot/ml/research/phase15i/orchestrator.py
tradingbot/ml/research/phase15i/phase99_signal_audit.py
tradingbot/ml/research/phase15i/quality_filter_audit.py
tradingbot/ml/research/phase15i/range_feature_validation.py
tradingbot/ml/research/phase15i/range_path_audit.py
tradingbot/ml/research/phase15i/range_router_validation.py
tradingbot/ml/research/phase15i/regime_distribution.py
tradingbot/ml/research/phase15i/replay.py
tradingbot/ml/research/phase15i/report_generator.py
tradingbot/ml/research/phase15i/risk_filter_audit.py
tradingbot/ml/research/phase15i/router_balance.py
tradingbot/ml/research/phase15i/signal_flow.py
tradingbot/ml/research/phase15i/validator.py
tradingbot/ml/research/phase15j/__init__.py
tradingbot/ml/research/phase15j/adapter_validation.py
tradingbot/ml/research/phase15j/bundle_validation.py
tradingbot/ml/research/phase15j/config.py
tradingbot/ml/research/phase15j/engine_probability_distribution.py
tradingbot/ml/research/phase15j/feature_drift.py
tradingbot/ml/research/phase15j/orchestrator.py
tradingbot/ml/research/phase15j/recommendation_engine.py
tradingbot/ml/research/phase15j/report_generator.py
tradingbot/ml/research/phase15j/root_cause_detector.py
tradingbot/ml/research/phase15j/stage_loss_report.py
tradingbot/ml/research/phase15j/trend_pipeline_trace.py
tradingbot/ml/research/phase15j/trend_signal_statistics.py
tradingbot/ml/research/phase15j/validator.py
tradingbot/ml/research/phase15k/__init__.py
tradingbot/ml/research/phase15k/ceiling_analyzer.py
tradingbot/ml/research/phase15k/config.py
tradingbot/ml/research/phase15k/data_access.py
tradingbot/ml/research/phase15k/distribution_drift_ceiling.py
tradingbot/ml/research/phase15k/engine_replay_trace.py
tradingbot/ml/research/phase15k/feature_ceiling_impact.py
tradingbot/ml/research/phase15k/model_behavior_simulator.py
tradingbot/ml/research/phase15k/orchestrator.py
tradingbot/ml/research/phase15k/pipeline_injection_audit.py
tradingbot/ml/research/phase15k/recommendation_ceiling.py
tradingbot/ml/research/phase15k/report_generator.py
tradingbot/ml/research/phase15k/trend_ceiling_root_cause.py
tradingbot/ml/research/phase15k/validator.py
tradingbot/ml/research/phase16b/__init__.py
tradingbot/ml/research/phase16b/alignment_metrics.py
tradingbot/ml/research/phase16b/config.py
tradingbot/ml/research/phase16b/kernel_replay.py
tradingbot/ml/research/phase16b/orchestrator.py
tradingbot/ml/research/phase16b/stress_tests.py
tradingbot/ml/research/phase16b/validator.py
tradingbot/ml/research/phase16c/__init__.py
tradingbot/ml/research/phase16c/config.py
tradingbot/ml/research/phase16c/feature_importance.py
tradingbot/ml/research/phase16c/funnel.py
tradingbot/ml/research/phase16c/orchestrator.py
tradingbot/ml/research/phase16c/pattern_analysis.py
tradingbot/ml/research/phase16c/rejection_clusters.py
tradingbot/ml/research/phase16c/rf_analysis.py
tradingbot/ml/research/phase16c/rule_diagnostics.py
tradingbot/ml/research/phase16c/threshold_simulation.py
tradingbot/ml/research/phase16c/verdict.py
tradingbot/ml/research/phase16d/__init__.py
tradingbot/ml/research/phase16d/candidate_compute.py
tradingbot/ml/research/phase16d/ceiling_analysis.py
tradingbot/ml/research/phase16d/ceiling_simulation.py
tradingbot/ml/research/phase16d/config.py
tradingbot/ml/research/phase16d/data_access.py
tradingbot/ml/research/phase16d/feature_catalog.py
tradingbot/ml/research/phase16d/information_gain.py
tradingbot/ml/research/phase16d/model_limitation.py
tradingbot/ml/research/phase16d/orchestrator.py
tradingbot/ml/research/phase16d/redundancy.py
tradingbot/ml/research/phase16d/verdict.py
tradingbot/ml/research/phase17a/__init__.py
tradingbot/ml/research/phase17a/architecture_matrix.py
tradingbot/ml/research/phase17a/compatibility.py
tradingbot/ml/research/phase17a/config.py
tradingbot/ml/research/phase17a/maintenance.py
tradingbot/ml/research/phase17a/orchestrator.py
tradingbot/ml/research/phase17a/risk_analysis.py
tradingbot/ml/research/phase17a/roadmap.py
tradingbot/ml/research/phase17a/scoring.py
tradingbot/ml/research/phase17a/verdict.py
tradingbot/ml/research/phase17b/acceptance.py
tradingbot/ml/research/phase17b/comparison.py
tradingbot/ml/research/phase17b/compatibility.py
tradingbot/ml/research/phase17b/verdict.py
tradingbot/ml/research/phase17c/__init__.py
tradingbot/ml/research/phase17c/config.py
tradingbot/ml/research/phase17c/dual_shadow.py
tradingbot/ml/research/phase17c/metrics.py
tradingbot/ml/research/phase17c/monte_carlo.py
tradingbot/ml/research/phase17c/orchestrator.py
tradingbot/ml/research/phase17c/range_regression.py
tradingbot/ml/research/phase17c/safety.py
tradingbot/ml/research/phase17c/stability.py
tradingbot/ml/research/phase17c/trend_quality.py
tradingbot/ml/research/phase17c/verdict.py
tradingbot/ml/research/phase17c/walk_forward.py
tradingbot/ml/research/phase18a/__init__.py
tradingbot/ml/research/phase18a/comparator.py
tradingbot/ml/research/phase18a/config.py
tradingbot/ml/research/phase18a/divergence.py
tradingbot/ml/research/phase18a/equity.py
tradingbot/ml/research/phase18a/latency.py
tradingbot/ml/research/phase18a/orchestrator.py
tradingbot/ml/research/phase18a/regime_validation.py
tradingbot/ml/research/phase18a/safety.py
tradingbot/ml/research/phase18a/shadow_runner.py
tradingbot/ml/research/phase18a/statistics.py
tradingbot/ml/research/phase18a/trade_logger.py
tradingbot/ml/research/phase18a/verdict.py
tradingbot/ml/research/phase19b/__init__.py
tradingbot/ml/research/phase19b/config.py
tradingbot/ml/research/phase19b/exit_study.py
tradingbot/ml/research/phase19b/filters.py
tradingbot/ml/research/phase19b/loss_analysis.py
tradingbot/ml/research/phase19b/montecarlo.py
tradingbot/ml/research/phase19b/orchestrator.py
tradingbot/ml/research/phase19b/position_sizing.py
tradingbot/ml/research/phase19b/recommendations.py
tradingbot/ml/research/phase19b/trade_dataset.py
tradingbot/ml/research/phase19b/verdict.py
tradingbot/ml/research/phase19b/walkforward.py
tradingbot/ml/research/phase19b/winner_analysis.py
tradingbot/ml/research/phase22aa/impact_forensics.py
tradingbot/ml/research/phase22ab/freeze_forensics.py
tradingbot/ml/research/phase22ac/registry_investigation.py
tradingbot/ml/research/phase22ad/__init__.py
tradingbot/ml/research/phase22ad/runtime_trace.py
tradingbot/ml/research/phase22ae/freeze_forensics.py
tradingbot/ml/research/phase22af/repair_design.py
tradingbot/ml/research/phase22ag/acceptance_forensics.py
tradingbot/ml/research/phase22ah/numeric_acceptance_validation.py
tradingbot/ml/research/phase22ai/acceptance_regression.py
tradingbot/ml/research/phase22aj/freeze_wiring_validation.py
tradingbot/ml/research/phase22aj0/winner_authority.py
tradingbot/ml/research/phase22ak/__init__.py
tradingbot/ml/research/phase22ak/freeze_execution.py
tradingbot/ml/research/phase22al/live_validation.py
tradingbot/ml/research/phase22e/certification.py
tradingbot/ml/research/phase22e/config.py
tradingbot/ml/research/phase22e/distribution.py
tradingbot/ml/research/phase22e/walkforward.py
tradingbot/ml/research/phase22f/__init__.py
tradingbot/ml/research/phase22f/config.py
tradingbot/ml/research/phase22f/datasets.py
tradingbot/ml/research/phase22f/overfiltering.py
tradingbot/ml/research/phase22f/priority.py
tradingbot/ml/research/phase22f/rapid_runner.py
tradingbot/ml/research/phase22f/trace.py
tradingbot/ml/research/phase22f/workflow.py
tradingbot/ml/research/phase22i/__init__.py
tradingbot/ml/research/phase22i/candidates.py
tradingbot/ml/research/phase22i/selection.py
tradingbot/ml/research/phase22j/engine_candidates.py
tradingbot/ml/research/phase22j/selection.py
tradingbot/ml/research/phase22p/execution_trace.py
tradingbot/ml/research/phase22p/signal_loss.py
tradingbot/ml/research/phase22p/trade_path.py
tradingbot/ml/research/phase22s/parity_cert.py
tradingbot/ml/research/phase22t/__init__.py
tradingbot/ml/research/phase22t/compare.py
tradingbot/ml/research/phase22t/config.py
tradingbot/ml/research/phase22t/feature_source.py
tradingbot/ml/research/phase22t/patch.py
tradingbot/ml/research/phase22t/runner.py
tradingbot/ml/research/phase22u/model_audit.py
tradingbot/ml/research/phase22w/selection_audit.py
tradingbot/ml/research/phase22y/acceptance_forensics.py
tradingbot/ml/research/phase22z/__init__.py
tradingbot/ml/research/phase22z/overfitting_rule_validation.py
tradingbot/ml/research/phase23a/pipeline_trace.py
tradingbot/ml/research/phase23b/repair_validation.py
tradingbot/ml/research/phase23c/__init__.py
tradingbot/ml/research/phase23c/decision_gate_investigation.py
tradingbot/ml/research/phase23c/run_investigation.py
tradingbot/ml/research/phase23d/__init__.py
tradingbot/ml/research/phase23d/filter_validation_research.py
tradingbot/ml/research/phase23d/run_investigation.py
tradingbot/ml/research/phase23e/__init__.py
tradingbot/ml/research/phase23e/range_filter_study.py
tradingbot/ml/research/phase23e/run_study.py
tradingbot/ml/research/phase23f/__init__.py
tradingbot/ml/research/phase23f/run_validation.py
tradingbot/ml/research/phase23f/shadow_validation.py
tradingbot/ml/research/phase23g/integration_validation.py
tradingbot/ml/research/phase24a/__init__.py
tradingbot/ml/research/phase24a/live_shadow_validator.py
tradingbot/ml/research/phase24a/run_validation.py
tradingbot/ml/research/phase24b/__init__.py
tradingbot/ml/research/phase24b/architecture_audit.py
tradingbot/ml/research/phase24b/run_audit.py
tradingbot/ml/research/phase24c/__init__.py
tradingbot/ml/research/phase24c/latency_profiler.py
tradingbot/ml/research/phase24c/run_profiling.py
tradingbot/ml/research/phase24d/__init__.py
tradingbot/ml/research/phase24d/run_investigation.py
tradingbot/ml/research/phase24d/unified_frame_investigation.py
tradingbot/ml/research/phase24e/run_validation.py
tradingbot/ml/research/phase24f/__init__.py
tradingbot/ml/research/phase24f/incremental_frame.py
tradingbot/ml/research/phase24f/run_investigation.py
tradingbot/ml/research/phase24g/run_validation.py
tradingbot/ml/research/phase24h/__init__.py
tradingbot/ml/research/phase24h/pipeline_tracer.py
tradingbot/ml/research/phase24h/run_investigation.py
tradingbot/ml/research/phase24i/run_validation.py
tradingbot/ml/research/phase25b/__init__.py
tradingbot/ml/research/phase25b/parity_replay_adapter.py
tradingbot/ml/research/phase25b/replay_portfolio.py
tradingbot/ml/research/phase25b/replay_position_state.py
tradingbot/ml/research/phase25b/unified_pipeline_replay.py
tradingbot/ml/research/phase27a/__init__.py
tradingbot/ml/research/phase27a/metrics.py
tradingbot/ml/research/phase27l/__init__.py
tradingbot/ml/research/phase27l/exit_simulators.py
tradingbot/ml/research/phase27l/exit_trace.py
tradingbot/ml/research/phase27n/__init__.py
tradingbot/ml/research/phase27n/hybrid_simulators.py
tradingbot/ml/research/phase28c/metrics.py
tradingbot/ml/research/phase28d/__init__.py
tradingbot/ml/research/phase28d/trade_builder.py
tradingbot/ml/research/phase28e/__init__.py
tradingbot/ml/research/phase28e/auditors.py
tradingbot/ml/research/phase28e/run_investigation.py
tradingbot/ml/research/phase28f/__init__.py
tradingbot/ml/research/phase28f/engine_map.py
tradingbot/ml/research/phase28f/run_investigation.py
tradingbot/ml/research/phase29a/__init__.py
tradingbot/ml/research/phase29a/analysis.py
tradingbot/ml/research/phase29a/causality.py
tradingbot/ml/research/phase29a/features.py
tradingbot/ml/research/phase29a/run_investigation.py
tradingbot/ml/research/phase29a/scoring.py
tradingbot/ml/research/phase29a/stress.py
tradingbot/ml/research/phase29b/run_investigation.py
tradingbot/ml/research/phase30a/__init__.py
tradingbot/ml/research/phase30a/breaking_points.py
tradingbot/ml/research/phase30a/pipeline_audit.py
tradingbot/ml/research/phase30a/run_investigation.py
tradingbot/ml/research/phase30a/trade_replay.py
tradingbot/ml/research/phase30d/run_investigation.py
tradingbot/ml/research/phase30e/run_investigation.py
tradingbot/ml/research/phase30f/__init__.py
tradingbot/ml/research/phase30f/collectors/__init__.py
tradingbot/ml/research/phase30f/collectors/base.py
tradingbot/ml/research/phase30f/collectors/execution_logger.py
tradingbot/ml/research/phase30f/collectors/gap_extractor.py
tradingbot/ml/research/phase30f/collectors/history_sync.py
tradingbot/ml/research/phase30f/collectors/news_joiner.py
tradingbot/ml/research/phase30f/collectors/supervisor.py
tradingbot/ml/research/phase30f/collectors/symbol_snapshot.py
tradingbot/ml/research/phase30f/collectors/tick_backfill.py
tradingbot/ml/research/phase30f/collectors/tick_poller.py
tradingbot/ml/research/phase30f/config.py
tradingbot/ml/research/phase30f/mt5_client.py
tradingbot/ml/research/phase30f/run_investigation.py
tradingbot/ml/research/phase30f/storage/__init__.py
tradingbot/ml/research/phase30f/storage/checksums.py
tradingbot/ml/research/phase30f/storage/manifest.py
tradingbot/ml/research/phase30f/storage/parquet_store.py
tradingbot/ml/research/phase30f/storage/sqlite_store.py
tradingbot/ml/research/phase30f/validation/__init__.py
tradingbot/ml/research/phase30f/validation/integrity.py
tradingbot/ml/research/phase30f/validation/schema.py
tradingbot/ml/research/phase31a/__init__.py
tradingbot/ml/research/phase31a/clustering.py
tradingbot/ml/research/phase31a/data_loader.py
tradingbot/ml/research/phase31a/edge_analysis.py
tradingbot/ml/research/phase31a/importance.py
tradingbot/ml/research/phase31a/root_causes.py
tradingbot/ml/research/phase31a/run_investigation.py
tradingbot/ml/research/phase31b/__init__.py
tradingbot/ml/research/phase31b/counterfactuals.py
tradingbot/ml/research/phase31b/metrics.py
tradingbot/ml/research/phase31b/run_investigation.py
tradingbot/ml/research/phase31c/__init__.py
tradingbot/ml/research/phase31c/exit_simulators.py
tradingbot/ml/research/phase31c/ranking.py
tradingbot/ml/research/phase31c/run_investigation.py
tradingbot/ml/research/phase31c/validation.py
tradingbot/ml/research/phase31d/__init__.py
tradingbot/ml/research/phase31d/parity_audit.py
tradingbot/ml/research/phase31d/root_causes.py
tradingbot/ml/research/phase31d/run_investigation.py
tradingbot/ml/research/phase31e/run_investigation.py
tradingbot/ml/research/phase32g/run_validation.py
tradingbot/ml/research/phase33d/__init__.py
tradingbot/ml/research/phase33d/forensic_context.py
tradingbot/ml/research/phase33d/schema.py
tradingbot/ml/research/phase34a/__init__.py
tradingbot/ml/research/phase34a/collector.py
tradingbot/ml/research/phase34a/metrics.py
tradingbot/ml/research/phase34c/run_filter_audit.py
tradingbot/ml/research/phase40/retrain_sweep.py
tradingbot/ml/research/phase41/model_search.py
tradingbot/ml/research/phase42/event_bias_audit.py
tradingbot/ml/research/phase42/feature_parity.py
tradingbot/ml/research/phase43/subset_builder.py
tradingbot/ml/research/phase45/structure_dataset.py
tradingbot/ml/research/phase46/ml_signal_dataset.py
tradingbot/ml/research/phase49/bar_index.py
tradingbot/ml/research/phase49/historical_windows.py
tradingbot/ml/research/phase50/strict_walk_forward.py
tradingbot/ml/research/phase51/profitability_score.py
tradingbot/ml/research/research_orchestrator.py
tradingbot/ml/research/sampling_analysis.py
tradingbot/ml/research/threshold_optimizer.py
tradingbot/ml/research/v41_isolated/__init__.py
tradingbot/ml/research/v41_isolated/cost_robustness.py
tradingbot/ml/research/v41_isolated/decision_audit.py
tradingbot/ml/research/v41_isolated/integrity.py
tradingbot/ml/research/v41_isolated/replay.py
tradingbot/ml/research/v41_isolated/robustness.py
tradingbot/ml/stress/__init__.py
tradingbot/ml/stress/chaos_tests.py
tradingbot/ml/stress/resilience.py
tradingbot/ml/stress/scenarios.py
tradingbot/ml/stress/simulator.py
tradingbot/ml/trade_quality/quality_trace.py
tradingbot/ml/trade_quality/validator.py
tradingbot/research/__init__.py
tradingbot/research/orb_forward_demo.py
tradingbot/research/phase17a_forensic.py
tradingbot/services/meta_false_negative.py
```

### 2.4 UNREACHABLE — DEAD_CODE

_96 files_

| Path | Last commit | Message | Docstring/header (truncated) |
|------|-------------|---------|------------------------------|
| `_audit_dead_research.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | One-off audit: research modules not reachable from live path. |
| `_run_diag_step1.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | 1 terminal64 |
| `scripts/_patch14a2.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New |  |
| `scripts/_rerun14a2.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Re-run 14A-2 with corrected session_ok and NY-day estimate. Writes UTF-8 report. |
| `scripts/_rerun14a2_fast.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | 14A-2 fast cache-only audit. |
| `scripts/_write_14c1_report.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New |  |
| `scripts/analyze_dataset.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Offline dataset quality analysis — Phase 3. |
| `scripts/analyze_features.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Offline feature analysis — quality and correlation reports. |
| `scripts/analyze_shadow_performance.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Analyze shadow ML/hybrid performance — Phase 5.2 (offline only). |
| `scripts/analyze_shap.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | SHAP analysis for trained baseline models — offline research only. |
| `scripts/architecture_implementation_audit.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE ARCHITECTURE-IMPLEMENTATION-AUDIT — READ-ONLY. Output: logs/architecture_implementation_audit. |
| `scripts/audit_ml_dataset.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 8.2 — ML dataset quality and research audit. |
| `scripts/backtest_adaptive_30d.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | 30-day backtest with sub-strategy breakdown. |
| `scripts/backtest_adaptive_regime.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Compare adaptive multi-regime vs VOL_REGIME-only on recent M5 XAUUSD data. |
| `scripts/backtest_adaptive_report.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Run backtest and write JSON report (avoids stdout issues on Windows). |
| `scripts/backtest_compare_strategies.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Compare strategy variants on 14d real MT5 data. |
| `scripts/backtest_vol_regime_24h.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | 24-hour VOL_REGIME backtest — XAUUSD M5, ATR2.5_RR0.8, production TQ path. |
| `scripts/backtest_vol_regime_today.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | VOL_REGIME backtest for a fixed UTC calendar day (default: today). |
| `scripts/build_project_classification.py` | 2026-09-09 05:26:55 +0330 | update project files |  |
| `scripts/build_project_memory.py` | 2026-09-09 05:26:55 +0330 | update project files |  |
| `scripts/check_today_signals.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Summarize today's kernel cycles and scan VOL_REGIME on live M5 bars. |
| `scripts/clear_emergency_stop.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Clear emergency stop flag so the bot can start again after kill switch. |
| `scripts/debug_live_loop_exit.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Run live loop briefly and log why the process exits. |
| `scripts/diagnose_mt5_connection.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | MT5 connection diagnostic — read-only, attach-only (no initialize/shutdown storms). |
| `scripts/diagnose_vol_regime_signals.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Deep VOL_REGIME diagnostic — raw signals vs TQ blocks on live M5 data. |
| `scripts/enable_mt5_autotrading.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Enable MT5 AutoTrading via Win32 WM_COMMAND and optional Options UI. |
| `scripts/evaluate_model.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Evaluate trained baseline ML model — Phase 4.0. |
| `scripts/generate_robot_ready_report.py` | 2026-09-09 05:26:55 +0330 | update project files | Generate logs/robot_ready_for_live_report.json — wiring audit + backtest. |
| `scripts/live_dataset_orchestrator.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22O — pre-live dataset maintenance orchestrator (outside trading loop). |
| `scripts/live_forensic_today.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE LIVE-FORENSIC-TODAY — READ-ONLY forensic report. No production changes, no orders sent. Output |
| `scripts/live_reconcile.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Journal vs MT5 reconciliation for today. |
| `scripts/optimize_shadow_policy.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Optimize shadow ML+rule policy from memory — Phase 5.3 (recommendations only). |
| `scripts/optimize_threshold.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Optimize trading probability threshold — Phase 4.1. |
| `scripts/phase_verify_audit.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE VERIFY — Institutional audit of completed research phases (READ-ONLY). |
| `scripts/production_readiness_check.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Run all production-readiness checks (non-destructive). |
| `scripts/read_mt5_experts_ini.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Print MT5 common.ini Experts section + terminal_info flags. |
| `scripts/refresh_live_account_cache.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Write data/live_account.json from MT5 (safe when bot IPC lock is free). |
| `scripts/refresh_live_candles.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Read-only live candle refresh — attach-only, respects MT5 IPC lock. Safe to run while MT5 GUI is ope |
| `scripts/run_ab_shadow_test.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Run A/B shadow test — rule vs hybrid (no live trading). |
| `scripts/run_deployment_check.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Run deployment readiness check — Phase 6.4 evaluation only. |
| `scripts/run_engine_health_dashboard.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 10A — generate engine health dashboard artifacts. |
| `scripts/run_hybrid_shadow.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Run hybrid ML + rule shadow mode — Phase 5.1 (live trading unchanged). |
| `scripts/run_ml_diagnostics.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Run ML system diagnostics — Phase 7.0. |
| `scripts/run_ml_improvement.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Run ML improvement recommendations — Phase 7.4. |
| `scripts/run_ml_kernel_shadow.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 10.1 — ML kernel shadow integration CLI (kernel pipeline, no real orders). |
| `scripts/run_ml_live_shadow.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 10.2 — ML live shadow validation CLI (MT5 read-only, no orders). |
| `scripts/run_ml_monitoring.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Run ML shadow monitoring — Phase 6.1 (informational only). |
| `scripts/run_ml_paper_trading.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 11 — kernel-integrated ML paper trading CLI (virtual execution only). |
| `scripts/run_ml_performance_profile.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Run ML performance profiling — Phase 7.2 benchmarking only. |
| `scripts/run_ml_research.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Run ML research intelligence pipeline — Phase 7.3. |
| `scripts/run_ml_shadow.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 10 ML shadow integration CLI (observation only — no real orders). |
| `scripts/run_ml_shadow_monitor.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 10.4 — long-duration ML shadow monitoring CLI (read-only, no orders). |
| `scripts/run_ml_stress_test.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Run ML stress tests — Phase 7.1 simulation only. |
| `scripts/run_paper_trading.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 9.10 paper trading & shadow validation CLI (no real orders). |
| `scripts/run_shadow_health_check.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 10.5 — shadow health check and error audit CLI. |
| `scripts/run_walk_forward.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 9.8 walk-forward validation CLI (offline, CPU-only). |
| `scripts/symbol_100pct_audit_scan.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Read-only symbol grep + classification for PHASE SYMBOL-100PCT-AUDIT. |
| `scripts/test_mt5_attach.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Quick test: attach to MT5 without disconnecting the GUI session. |
| `scripts/train_baseline.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Train offline baseline ML models — Phase 4.0 (research only, not live). |
| `scripts/train_model.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 8.6 production ML training CLI (offline, CPU-only). |
| `scripts/validate_model.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Full offline model validation — Phase 4.1 (research only, not live). |
| `scripts/verify_and_go_live.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | One-shot: signal fix + autotrading + smoke trade + start LIVE. |
| `scripts/verify_vol_regime_live_ready.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Verify VOL_REGIME full live stack — kernel path, no ML, no demo-only deps. |
| `scripts/visualize_dataset.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Offline dataset visualization — Phase 3.1 (no live trading impact). |
| `scripts/wait_mt5_login.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Poll until MT5 is running and attached account matches config. |
| `tradingbot/adapters/legacy_signal_helpers.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | محاسبه confidence و SL/TP — re-export از لایه میانی domain. برای importهای قدیمی همین مسیر باقی می‌م |
| `tradingbot/adapters/mt5_attach_test.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Quick MT5 attach test — prints connection status, does NOT shutdown if connected. |
| `tradingbot/backtest/monte_carlo.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Monte Carlo — شبیه‌سازی ترتیب معاملات برای تخمین drawdown و احتمال ورشکستگی. |
| `tradingbot/domain/indicators.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | اندیکاتورهای تکنیکال — توابع خالص (pure functions). این ماژول نسخه‌ی تمیز و بازنویسی‌شده‌ی منطق اندی |
| `tradingbot/ml/feature_store.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 11A — institutional-grade unified ML feature store. |
| `tradingbot/ml/features/context.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Higher timeframe context features — H4 bias, M15 state, M5 entry context. |
| `tradingbot/ml/features/microstructure.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Market microstructure features — spread and tick-derived state. |
| `tradingbot/ml/features/momentum.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Momentum feature family — rate of change and oscillator state. |
| `tradingbot/ml/features/price_action.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Price action feature family — candle morphology and pattern state. |
| `tradingbot/ml/features/session.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Session feature family — time-of-day and kill-zone market state. |
| `tradingbot/ml/features/smc.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | SMC structure feature family — BOS, CHoCH, sweep, FVG, OB, premium/discount. |
| `tradingbot/ml/features/trend.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Trend feature family — market state directional bias. |
| `tradingbot/ml/features/volatility.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Volatility feature family — range expansion and ATR state. |
| `tradingbot/ml/integration/institutional_research_adapter.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 11A research adapter — institutional feature store + regime models (NO LIVE ENABLE). |
| `tradingbot/ml/integration/unified_entry_features.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | ML Kernel entry-feature bridge — delegates to UnifiedFeatureStore (Phase D1). |
| `tradingbot/ml/paper/report.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Paper trading report generation. |
| `tradingbot/ports/events.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Port: رویدادها — جایگزین EventBus. |
| `tradingbot/research/calibration_hardening.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 15C — Institutional Calibration Hardening (research only). Rebuild calibration pipeline on Pha |
| `tradingbot/research/displacement_intelligence.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 16A — Institutional Displacement Intelligence (research only). Normalized displacement feature |
| `tradingbot/research/mfe_mae_intelligence.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 15B — MFE / MAE Intelligence (research only). For each labeled setup: setup_score, MFE_R, MAE_ |
| `tradingbot/research/ob_fvg_confluence.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 16B — OB + FVG Institutional Confluence (research only). Institutional OB validity: 1) Displac |
| `tradingbot/research/pa_meta_retrain.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 18B PA meta retrain helpers (research only). |
| `tradingbot/research/portfolio_router.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 22D research-only portfolio router. Not wired to live routing. |
| `tradingbot/research/regime_ensemble.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 16C — Regime-Aware ML Ensemble (research only). PurgedKFold + embargo, per-regime LightGBM/XGB |
| `tradingbot/research/setup_quality_score.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 15A — Institutional Setup Quality Score (research only). NO live routing / execution / config  |
| `tradingbot/services/engine_health_dashboard.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 10A — permanent engine health dashboard (telemetry only). |
| `tradingbot/services/engine_telemetry_service.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Compatibility alias -- EngineTelemetryService lives in engine_telemetry.py. |
| `tradingbot/services/meta_dynamic_calibration.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 2A — dynamic meta threshold calibration helpers (test/calibration only). |
| `tradingbot/strategies/adaptive_ml_hybrid.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 12C — Adaptive Quality + ML hybrid decision layer (RESEARCH ONLY). Combines rule-based quality |
| `tradingbot/strategies/vol_context_engine.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase B1 — VOL context engine (quality only, no BUY/SELL). |
| `tradingbot/strategies/vol_direction_filter.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 48A — VOL_REGIME as direction/quality filter (no independent trades). |

### 2.5 UNREACHABLE — RESEARCH_ARCHIVE_CANDIDATE

_419 files_

| Path | Last commit | Message | Docstring/header (truncated) |
|------|-------------|---------|------------------------------|
| `_phase33c_forensic.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 33C — rejected signal outcome audit (read-only forensic runner). |
| `scripts/_write_phase23a.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New |  |
| `scripts/phase12a_pa_dataset_builder.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 12A — Full PA Institutional Dataset Builder (READ-ONLY + BUILD). Does NOT modify live trading  |
| `scripts/phase12b_regime_training.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 12B — Regime-Specific ML Institutional Training (RESEARCH ONLY). Input: data/ml/research/phase |
| `scripts/phase12c_hybrid_certification.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 12C — Adaptive Quality + ML Hybrid Certification (RESEARCH ONLY). Does NOT modify PA_PRODUCTIO |
| `scripts/phase13a_cleanup_audit.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 13A — Production Cleanup & Dead-Code Audit (READ-ONLY + smoke checks). Does NOT delete, refact |
| `scripts/phase13b_no_trade_recovery.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 13B — No-Trade Root Cause & Frequency Recovery (READ-ONLY + REPLAY). Does NOT change config, u |
| `scripts/phase13c_adaptive_hybrid_v2.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 13C - Adaptive Quality v2 + ML Hybrid Certification (RESEARCH ONLY). Does NOT modify PA_PRODUC |
| `scripts/phase13d_ml_retraining.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 13D - ML data expansion and regime model retraining (RESEARCH/TRAINING ONLY). No live ML enabl |
| `scripts/phase14a2_pa_no_signal_audit.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 14A-2 PA No-Signal Deep Audit (READ-ONLY). No config changes. |
| `scripts/phase14b2_pa_hold_replay.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 14B-2 — replay last 1000 M5 bars into pa_hold_reasons.jsonl (READ/OBS). |
| `scripts/phase14b2_pa_hold_replay_fast.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New |  |
| `scripts/phase14b3_readiness_report.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New |  |
| `scripts/phase14c1_ny_window_recovery.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 14C-1 NY window research — fast lookback enrich. |
| `scripts/phase14c1_session_window_recovery.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 14C-1 Session Window Recovery — research only (10-17 vs 9-17). |
| `scripts/phase14c2_reclaim_softening.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 14C-2 Asian Reclaim Softening — research only (no live changes). |
| `scripts/phase14c3_bos_sensitivity.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 14C-3 BOS Sensitivity Audit — research only (no live changes). |
| `scripts/phase16a_displacement_intelligence.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 16A runner — Institutional Displacement Intelligence (research only). |
| `scripts/phase16b_ob_fvg_confluence.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 16B — OB+FVG Institutional Confluence comparison (research only). |
| `scripts/phase16c_regime_ensemble.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 16C — Regime-Aware ML Ensemble runner (research only). |
| `scripts/phase17a_pa_session_heatmap.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 17A — PA session heatmap + last-500 live forensic replay (research only). |
| `scripts/phase17b_bos_reclaim_truth.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 17B — BOS/Reclaim Truth Engine (research only, no live changes). |
| `scripts/phase18a_dataset_expansion.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 18A — ML Dataset Expansion Pipeline (RESEARCH ONLY). Collects all NY-session PA sweep setups f |
| `scripts/phase18b_meta_retraining.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 18B ? Regime-aware PA meta-labeler retraining (RESEARCH / SHADOW ONLY). USE_ML_KERNEL stays fa |
| `scripts/phase19a_reclaim_intelligence.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 19A ? Live Reclaim Intelligence (replay + telemetry only). No live trading-logic changes. PATC |
| `scripts/phase19b_label_quality.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 19B ? Institutional ML label quality upgrade (research only). Multi-horizon labels, soft timeo |
| `scripts/phase19c_shadow_meta.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 19C ? Shadow Meta Truth Monitor (research / shadow only). Scores every raw PA setup with the c |
| `scripts/phase20a_bos_live_parity.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 20A — PA BOS Live Parity Audit. Replay-only. Does not change live logic, config, or execution  |
| `scripts/phase20b_meta_shadow_demotion.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 20B — Meta Shadow Demotion Audit. Research/shadow only. Does not change live decisions or conf |
| `scripts/phase20c_mss_fvg_tests.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 20C — Shadow tests of MSS / FVG / CISD / session / HTF / stale-sweep. Research only. No live l |
| `scripts/phase20y2_choch_bridge.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 20Y-2 ? CHoCH continuation bridge 90d replay certification. |
| `scripts/phase20y3_meta_observer.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 20Y-3 — Meta observer vs Meta gate, 30d PA shadow comparison. |
| `scripts/phase21a_setup_formation_lab.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 21A — PA setup formation root-cause lab (READ-ONLY, no live patches). |
| `scripts/phase21b_hour15_realign.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 21B — Hour-15 vs baseline 10-17, 180d PA replay (no Meta/RiskGate changes). |
| `scripts/phase21c_health_snapshot.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 21C — live telemetry health snapshot (read-only). |
| `scripts/phase21d_meta_false_negative_audit.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 21D — join Meta rejects to 24-bar MFE outcomes (research; no live gating change). |
| `scripts/phase22a_strategy_discovery.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 22A — PA strategy discovery lab (research-only, no live patches, no Meta). |
| `scripts/phase22b_strategy_certification.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 22B — robust strategy certification (research-only, no live patches). Certifies only Phase 22A |
| `scripts/phase22c_meta_v2.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 22C model-specific Meta v2. Research only. No live patches. |
| `scripts/phase22d_portfolio_router.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 22D multi-strategy portfolio router backtest. Research only. No live patches. |
| `scripts/phase22e_forward_demo.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 22E 10-day forward demo certification. Research/shadow only. No live patches. Runs only Phase  |
| `scripts/phase23a_multi_strategy_discovery.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 23A - multi-strategy alpha discovery lab (research-only, no live patches). |
| `scripts/phase23b_strategy_certification.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 23B ? Alpha candidate certification (research-only, no live patches). Certifies only explicit  |
| `scripts/phase23c_portfolio_router.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 23C - Portfolio router promotion candidate (research-only, no live enable). Uses only Phase 23 |
| `scripts/phase24a_specialized_certification.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | PHASE 24A - specialized alpha certification (research-only, no live patches). |
| `scripts/phase24b_orb_forward_demo.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 24B ORB forward demo CLI (research-only). |
| `scripts/run_phase11_5_analysis.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 11.5 — research-only optimization & bias audit (no live orders). |
| `scripts/run_phase12_1_audit.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 12.1 — strategy architecture audit CLI (read-only). |
| `scripts/run_phase12_health_check.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 12 — pre-live health check CLI. |
| `scripts/run_phase12_live_pilot.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 12 — controlled live pilot CLI. |
| `scripts/run_phase13_10_router_final.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 13.10 — trend contribution expansion and final router validation CLI. |
| `scripts/run_phase13_2_regime.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 13.2 — market regime detection research CLI. |
| `scripts/run_phase13_3_trend.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 13.3 — trend strategy research CLI. |
| `scripts/run_phase13_4_trend_ml.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 13.4 — trend ML enhancement research CLI. |
| `scripts/run_phase13_5_router.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 13.5 — regime router research CLI. |
| `scripts/run_phase13_6_optimizer.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 13.6 — router optimizer research CLI. |
| `scripts/run_phase13_7_stability.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 13.7 — router stability research CLI. |
| `scripts/run_phase13_8_trend_recovery.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 13.8 — trend recovery research CLI. |
| `scripts/run_phase13_9_unified_router.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 13.9 — unified router research CLI. |
| `scripts/run_phase14_10_stability.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 14.10 — walk-forward stability recovery CLI. |
| `scripts/run_phase14_10_stage1_yearly.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 14.10 Stage 1 — fast yearly statistics CLI. |
| `scripts/run_phase14_10_stage2_drift.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 14.10 Stage 2 — yearly drift analysis CLI. |
| `scripts/run_phase14_10_stage3_threshold.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 14.10 Stage 3 — per-year threshold replay CLI. |
| `scripts/run_phase14_10_stage4_policy.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 14.10 Stage 4 — adaptive threshold policy CLI. |
| `scripts/run_phase14_10_stage5_report.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 14.10 Stage 5 — final report CLI. |
| `scripts/run_phase14_1_decision_test.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 14.1 — decision engine integration test CLI (no execution). |
| `scripts/run_phase14_2a_calibration.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 14.2A — confidence calibration research CLI (no execution). |
| `scripts/run_phase14_2b_risk.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 14.2B — adaptive risk intelligence CLI (no execution). |
| `scripts/run_phase14_3_quality.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 14.3 — trade quality intelligence CLI (no execution). |
| `scripts/run_phase14_4_optimizer.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 14.4 — signal optimization & opportunity recovery CLI. |
| `scripts/run_phase14_5_confidence_optimizer.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 14.5 — confidence operating point optimization CLI. |
| `scripts/run_phase14_6_calibration_recovery.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 14.6 — calibration recovery CLI. |
| `scripts/run_phase14_7_pipeline_validation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 14.7 — end-to-end pipeline validation CLI. |
| `scripts/run_phase14_8_stress_validation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 14.8 — full robustness & stress validation CLI. |
| `scripts/run_phase14_9_stability.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 14.9 — multi-regime stability CLI. |
| `scripts/run_phase15a_preparation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 15A — production integration preparation CLI. |
| `scripts/run_phase15b_kernel_validation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 15B — kernel integration validation CLI. |
| `scripts/run_phase15c_monitoring.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 15C — live monitoring and observability CLI. |
| `scripts/run_phase15d_shadow.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 15D — shadow mode live safety validation CLI. |
| `scripts/run_phase15e_shadow_debug.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 15E — shadow mode signal failure diagnosis CLI. |
| `scripts/run_phase15f_confidence_recovery.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 15F — confidence gate recovery CLI. |
| `scripts/run_phase15g_confidence_analysis.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 15G — frozen bundle confidence analysis CLI. |
| `scripts/run_phase15h_confidence_mapping.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 15H — confidence scale mapping CLI. |
| `scripts/run_phase15i_range_recovery.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 15I — range engine recovery CLI. |
| `scripts/run_phase15j_rootcause.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 15J — trend engine root cause trace CLI (read-only). |
| `scripts/run_phase15k_ceiling_analysis.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 15K — trend RF ceiling analysis CLI (read-only). |
| `scripts/run_phase16a_alignment.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 16A — trend feature distribution aligner validation CLI. |
| `scripts/run_phase16b_kernel_validation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 16B — kernel-level validation and throughput stress test. |
| `scripts/run_phase16c_trend_analysis.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 16C — TREND engine throughput root analysis (read-only). |
| `scripts/run_phase16d_feature_study.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 16D — Trend feature ceiling expansion study (read-only). |
| `scripts/run_phase17a_blueprint.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 17A — integrated TREND recovery blueprint (read-only). |
| `scripts/run_phase17b_retrain_lab.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 17B — offline RF+Top5 chronological retrain lab (research only). |
| `scripts/run_phase17c_shadow_bundle.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 17C — shadow bundle validation (research only). |
| `scripts/run_phase18a_shadow_validation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 18A — live shadow validation (no production impact, zero live orders). |
| `scripts/run_phase18b_go_live.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 18B — controlled live gate (final GO/NO-GO). |
| `scripts/run_phase18c_prelive.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 18C — pre-live verification (market closed, no trading). |
| `scripts/run_phase19a_profitability_audit.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 19A — profitability audit (read-only). |
| `scripts/run_phase19b_profitability_optimization.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 19B — profitability optimization (research only). |
| `scripts/run_phase19c_profitability_upgrade.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 19C — safe profitability upgrade validation. |
| `scripts/run_phase19d_certification.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 19D — final production certification (read-only). |
| `scripts/run_phase20a_live_deployment.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 20A — controlled live capital deployment. |
| `scripts/run_phase20b_stabilization.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 20B — live trading stabilization & performance control (read-only). |
| `scripts/run_phase20c_broker_validation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 20C — real broker execution validation (read-only). |
| `scripts/verify_phase2_live_ready.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 2 readiness — demo guard, Telegram optional, reporting scripts. |
| `scripts/verify_phase4_live_ready.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 4 readiness — prop preset, drift monitor, slippage/spread reporting. |
| `tradingbot/backtest/phase116_source_planning.py` | — |  |  |
| `tradingbot/backtest/phase116_source_research.py` | — |  |  |
| `tradingbot/backtest/phase1b_metrics.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 1B — extended PA+Meta backtest metrics + Monte Carlo on R-multiples. |
| `tradingbot/ml/phase19c/orchestrator.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 19C — safe profitability upgrade orchestrator. |
| `tradingbot/ml/research/documentation_freshness/run.py` | 2026-09-09 05:26:55 +0330 | update project files | Scan documentation freshness. Canonical snapshot writes are opt-in. |
| `tradingbot/ml/research/documentation_operationalization/__init__.py` | 2026-09-09 05:26:55 +0330 | update project files | Verification-only operationalization audit. |
| `tradingbot/ml/research/documentation_verification/__init__.py` | 2026-09-09 05:26:55 +0330 | update project files | Single documentation/memory verification entry. No production trading imports. |
| `tradingbot/ml/research/full_repo_audit/__init__.py` | 2026-09-09 05:26:55 +0330 | update project files | Phase 1.5.61 — full repository knowledge audit (offline, no live I/O). |
| `tradingbot/ml/research/live_bt/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Live backtest gate — strict pre-paper validation (research only). |
| `tradingbot/ml/research/live_bt/backtest_gate.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | BACKTEST_GATE — strict pre-paper backtest validation (research only). |
| `tradingbot/ml/research/live_bt/rr_production_research.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | RR_PRODUCTION_RESEARCH — VOL_REGIME RR sweep + TQ counterfactual (research only). |
| `tradingbot/ml/research/live_l1/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | L1 live data foundation package. |
| `tradingbot/ml/research/live_l1/build_v8_dataset.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | L1 — build v8 enriched dataset from fullest candles + v7 features (research only). |
| `tradingbot/ml/research/live_l1/expand_v8_labels.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | L1b — expand v8 labels on unlabeled rows (production SL/TP + research RR=1.0). |
| `tradingbot/ml/research/live_l2/edge_discovery_l26.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | L2.6 — combined edge test: PULLBACK_VWAP + ATR2.0/RR1.0 + v8 TREND ML filter (research only). |
| `tradingbot/ml/research/live_l2/edge_discovery_l27.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | L2.7 — RR fine-tune + multi-signal sweep at RR~1.0 (research only). |
| `tradingbot/ml/research/live_l4/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | L4 live ML on proven edge package. |
| `tradingbot/ml/research/live_l4/signal_ml_refinement.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | L4 — ML refinement on proven PULLBACK_VWAP signal only (research only). |
| `tradingbot/ml/research/live_l4/v8_regime_ml_test.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | L4-prep — v8 enriched dataset regime ML test vs v7 baseline (research only). |
| `tradingbot/ml/research/pa_live_audit/root_cause.py` | 2026-09-09 05:26:55 +0330 | update project files | Phase 1.5.59 — ranked live-failure / parity findings from repository evidence only. |
| `tradingbot/ml/research/pa_live_audit/run.py` | 2026-09-09 05:26:55 +0330 | update project files | Write Phase 1.5.56–60 research report JSON. Offline only. |
| `tradingbot/ml/research/phase13c/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 13C - Adaptive + ML Hybrid v2 (RESEARCH ONLY). |
| `tradingbot/ml/research/phase13c/adaptive_quality_v2.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 13C - Adaptive Quality v2 + ML confirmation (RESEARCH ONLY). Dynamic weight budgets always sum |
| `tradingbot/ml/research/phase14_10/stage1_yearly_statistics.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 14.10 Stage 1 — fast per-year statistics (no MC / WF / threshold search). |
| `tradingbot/ml/research/phase14_10/stage2_drift_analysis.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 14.10 Stage 2 — yearly drift analysis from Stage 1 JSON only. |
| `tradingbot/ml/research/phase14_10/stage3_threshold_replay.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 14.10 Stage 3 — per-year threshold replay (no retrain / no full rebuild). |
| `tradingbot/ml/research/phase14_10/stage4_adaptive_threshold_policy.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 14.10 Stage 4 — adaptive threshold policy from Stage 1+3 JSON only. |
| `tradingbot/ml/research/phase14_10/stage5_final_report.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 14.10 Stage 5 — final report summarization from prior stage JSON only. |
| `tradingbot/ml/research/phase17b/orchestrator.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 17B — offline RF+Top5 retrain lab orchestrator. |
| `tradingbot/ml/research/phase1b/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 1B package. |
| `tradingbot/ml/research/phase1b/pa_full_cert.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 1B — full PA+Meta backtest certification (cache-only, HTF bypass). |
| `tradingbot/ml/research/phase22aa/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22AA — impact radius forensics. |
| `tradingbot/ml/research/phase22aa/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22AA — overfitting_risk_decreased impact radius forensics. |
| `tradingbot/ml/research/phase22ab/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22AB — freeze path authority forensics. |
| `tradingbot/ml/research/phase22ab/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22AB — freeze path authority forensics. |
| `tradingbot/ml/research/phase22ac/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22AC — freeze integration radius investigation (read-only). |
| `tradingbot/ml/research/phase22ac/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22AC — freeze integration radius investigation (repository only). |
| `tradingbot/ml/research/phase22ad/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22AD — runtime authority trace (repository only). |
| `tradingbot/ml/research/phase22ae/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22AE — freeze decision forensics (read-only). |
| `tradingbot/ml/research/phase22ae/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22AE — freeze decision forensics (repository only). |
| `tradingbot/ml/research/phase22af/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22AF — freeze pipeline repair design (research only). |
| `tradingbot/ml/research/phase22af/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22AF — freeze pipeline repair design (research only). |
| `tradingbot/ml/research/phase22ag/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22AG — acceptance gate calibration forensics. |
| `tradingbot/ml/research/phase22ag/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22AG — acceptance gate calibration forensics (research only). |
| `tradingbot/ml/research/phase22ah/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22AH — numeric acceptance rule validation (research only). |
| `tradingbot/ml/research/phase22ah/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22AH — numeric acceptance rule validation (research only). |
| `tradingbot/ml/research/phase22ai/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22AI — acceptance patch + freeze bridge prototype. |
| `tradingbot/ml/research/phase22ai/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22AI — acceptance patch regression + freeze bridge prototype. |
| `tradingbot/ml/research/phase22aj/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22AJ — production freeze authority wiring. |
| `tradingbot/ml/research/phase22aj/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22AJ — production freeze authority wiring report. |
| `tradingbot/ml/research/phase22aj0/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22AJ0 — winner authority resolution. |
| `tradingbot/ml/research/phase22aj0/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22AJ0 — winner authority resolution (research only). |
| `tradingbot/ml/research/phase22ak/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22AK — controlled end-to-end model freeze execution. |
| `tradingbot/ml/research/phase22al/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22AL — production candidate live validation. |
| `tradingbot/ml/research/phase22al/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22AL — production candidate live validation report. |
| `tradingbot/ml/research/phase22b/run_capability_audit.py` | 2026-09-09 05:26:55 +0330 | update project files | Phase 22B — READ-ONLY capability audit. Does not modify production code. |
| `tradingbot/ml/research/phase22c/run_validation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22C — multi-timeframe validation backtests + hold-chain report. |
| `tradingbot/ml/research/phase22d/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22D — engine root cause investigation. |
| `tradingbot/ml/research/phase22d/run_forensics.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22D — full engine forensic audit (read-only + report generation). |
| `tradingbot/ml/research/phase22e/delta.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22E — delta report vs Phase 19D, 20B, 22B, 22D. |
| `tradingbot/ml/research/phase22e/montecarlo.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22E — Monte Carlo on trade order, spread, slippage, missing trades, latency. |
| `tradingbot/ml/research/phase22e/portfolio.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22E — shared-balance multi-timeframe portfolio backtest (research only). |
| `tradingbot/ml/research/phase22e/run_validation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22E — full production validation and profitability certification. |
| `tradingbot/ml/research/phase22e/runner.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22E — production-path single-timeframe backtest runner. |
| `tradingbot/ml/research/phase22e/stress.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22E — stress scenarios on production backtest path. |
| `tradingbot/ml/research/phase22f/ablation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22F — feature contribution from baseline hold-chain evidence. |
| `tradingbot/ml/research/phase22f/bottleneck.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22F — signal bottleneck funnel map. |
| `tradingbot/ml/research/phase22f/missed_ops.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22F — missed profitable opportunities (blocked but model-correct). |
| `tradingbot/ml/research/phase22f/run_rapid_validation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22F — rapid optimization framework (read-only, evidence-driven). |
| `tradingbot/ml/research/phase22f/trade_quality.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22F — executed trade quality metrics (MAE/MFE/RR). |
| `tradingbot/ml/research/phase22g/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22G — repository-driven root cause investigation. |
| `tradingbot/ml/research/phase22g/bottleneck.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22G — profitability bottleneck from trace + baseline. |
| `tradingbot/ml/research/phase22g/decision_engine_doc.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22G — decision engine documentation from code. |
| `tradingbot/ml/research/phase22g/execution_graph.py` | 2026-09-09 05:26:55 +0330 | update project files | Phase 22G — verified live execution graph from source code. |
| `tradingbot/ml/research/phase22g/execution_tracer.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22G — per-candle execution trace on Dataset A. |
| `tradingbot/ml/research/phase22g/model_inventory.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22G — production model inventory from loaders. |
| `tradingbot/ml/research/phase22g/model_routing.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22G — model routing verification from code. |
| `tradingbot/ml/research/phase22g/rapid_runner.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22G — baseline runner for bottleneck analysis. |
| `tradingbot/ml/research/phase22g/recommended_fix.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22G — single recommended fix (evidence-based, no implementation). |
| `tradingbot/ml/research/phase22g/report_verification.py` | 2026-09-09 05:26:55 +0330 | update project files | Phase 22G — verify prior phase conclusions against current code. |
| `tradingbot/ml/research/phase22g/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22G — repository-driven root cause investigation. |
| `tradingbot/ml/research/phase22h/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22H — active trend engine alignment validation. |
| `tradingbot/ml/research/phase22h/alignment.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22H — verify active engine alignment across production ML path. |
| `tradingbot/ml/research/phase22h/delta.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22H — regression and Phase 22F delta. |
| `tradingbot/ml/research/phase22h/run_validation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22H — implement and validate 22G-001 active engine alignment. |
| `tradingbot/ml/research/phase22i/hold_profiler.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22I — decision engine hold profiling on Dataset A. |
| `tradingbot/ml/research/phase22i/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22I — decision engine deep optimization (research-only). |
| `tradingbot/ml/research/phase22i/runner.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22I — run Dataset A backtest with research orchestrator. |
| `tradingbot/ml/research/phase22i/stack.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22I — inject research orchestrator into ML stack for backtest simulation. |
| `tradingbot/ml/research/phase22j/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22J — engine-level signal investigation (research-only). |
| `tradingbot/ml/research/phase22j/range_forensics.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22J — phase9_9 range engine forensics on Dataset A. |
| `tradingbot/ml/research/phase22j/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22J — engine-level signal investigation (research-only). |
| `tradingbot/ml/research/phase22j/runner.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22J — run Dataset A backtest with engine candidate patch. |
| `tradingbot/ml/research/phase22j/training_alignment.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22J — training vs inference alignment validation (post 22H). |
| `tradingbot/ml/research/phase22j/trend_forensics.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22J — trend_rf_v41 engine forensics on Dataset A. |
| `tradingbot/ml/research/phase22l/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22L — dataset refresh and feature pipeline repair (research only). |
| `tradingbot/ml/research/phase22l/audit_pipeline.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22L — Step 1: dataset_v2 generation pipeline audit. |
| `tradingbot/ml/research/phase22l/comparison.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22L — Step 6: before/after comparison using refreshed dataset only in research. |
| `tradingbot/ml/research/phase22l/coverage.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22L — Step 3: feature coverage before/after refresh on Dataset A. |
| `tradingbot/ml/research/phase22l/range_quality.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22L — Step 5: range model input quality on Dataset A window. |
| `tradingbot/ml/research/phase22l/rebuild.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22L — Step 2: rebuild dataset_v2 to research artifact (no production overwrite). |
| `tradingbot/ml/research/phase22l/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22L — dataset refresh and feature pipeline repair (research only). |
| `tradingbot/ml/research/phase22l/unified_audit.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22L — Step 4: unified frame source audit. |
| `tradingbot/ml/research/phase22m/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22M — live data pipeline & CandleStore forensics (repository only). |
| `tradingbot/ml/research/phase22n/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22N — automated ML data refresh validation and reports. |
| `tradingbot/ml/research/phase22o/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22O — full automatic dataset maintenance validation and reports. |
| `tradingbot/ml/research/phase22p/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22P — end-to-end live execution forensics on Dataset A. |
| `tradingbot/ml/research/phase22q/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22Q — prove or disprove Phase99 architecture (repository truth only). |
| `tradingbot/ml/research/phase22r/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22R — Repository-guided Live FeatureBuilder refactor feasibility (research only). |
| `tradingbot/ml/research/phase22s/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22S — FeatureBuilder numerical parity certification. |
| `tradingbot/ml/research/phase22t/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22T — controlled live FeatureBuilder refactor comparison on Dataset A. |
| `tradingbot/ml/research/phase22u/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22U — model capability verification research. |
| `tradingbot/ml/research/phase22u/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22U — phase9_9 model capability verification. |
| `tradingbot/ml/research/phase22v/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22V — phase9_9 training pipeline forensics. |
| `tradingbot/ml/research/phase22v/model_audit.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22V — phase9_9 training pipeline forensics. |
| `tradingbot/ml/research/phase22v/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22V — phase9_9 training pipeline forensics. |
| `tradingbot/ml/research/phase22w/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22W — training criterion root-cause verification. |
| `tradingbot/ml/research/phase22w/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22W — training criterion root-cause verification. |
| `tradingbot/ml/research/phase22x/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22X — production fix for model selection criteria. |
| `tradingbot/ml/research/phase22x/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22X — validate probability selection gate and Phase 9.9 pipeline. |
| `tradingbot/ml/research/phase22y/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22Y — accepted candidate failure forensics. |
| `tradingbot/ml/research/phase22y/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22Y — accepted candidate failure forensics. |
| `tradingbot/ml/research/phase22z/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 22Z — overfitting_risk_decreased rule validation. |
| `tradingbot/ml/research/phase23a/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 23A — end-to-end ML pipeline trace and root cause investigation. |
| `tradingbot/ml/research/phase23a/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 23A — read-only ML pipeline trace and root cause report. |
| `tradingbot/ml/research/phase23b/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 23B — feature pipeline repair validation. |
| `tradingbot/ml/research/phase23b/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 23B — feature pipeline repair validation report. |
| `tradingbot/ml/research/phase23g/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 23G — production integration of RANGE filter profile. |
| `tradingbot/ml/research/phase23g/run_validation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 23G — integration validation runner. |
| `tradingbot/ml/research/phase24e/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 24E — Strategy B validation (persistent dataset_v2 memory cache). |
| `tradingbot/ml/research/phase24g/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 24G — safe internal unified frame optimization. |
| `tradingbot/ml/research/phase24i/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 24I — unified feature input optimization. |
| `tradingbot/ml/research/phase24j/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 24J — READ ONLY final production audit before paper trading. Generates JSON deliverables from  |
| `tradingbot/ml/research/phase24k/run_validation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 24K — validate production blocker fixes and emit JSON deliverables. |
| `tradingbot/ml/research/phase25a/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 25A — Paper Trading vs Research Replay consistency audit (READ ONLY). |
| `tradingbot/ml/research/phase25b/pipeline_depth.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Stage-by-stage pipeline depth comparison: legacy research vs production paper. |
| `tradingbot/ml/research/phase25b/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 25B — parity comparison, timeout analysis, and deliverable generation. |
| `tradingbot/ml/research/phase26a/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 26A — Paper trading validation infrastructure (observation only). |
| `tradingbot/ml/research/phase26a/exit_simulator.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Research-only trade exit simulation on historical candles. |
| `tradingbot/ml/research/phase26a/journal_reader.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Read-only paper execution records from production TradeJournal SQLite. |
| `tradingbot/ml/research/phase26a/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 26A — paper trading validation infrastructure runner. |
| `tradingbot/ml/research/phase26a/statistics.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Aggregate paper trade statistics (research-only). |
| `tradingbot/ml/research/phase26a/trade_collector.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Collect and enrich completed paper trades (read-only observation). |
| `tradingbot/ml/research/phase26a/trade_schema.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Completed paper trade record schema. |
| `tradingbot/ml/research/phase26a/validation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Verify Phase 26A did not modify protected production modules. |
| `tradingbot/ml/research/phase26c/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 26C paper journal reliability. |
| `tradingbot/ml/research/phase26c/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 26C — Paper journal reliability repair and validation. |
| `tradingbot/ml/research/phase26d/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 26D startup safety. |
| `tradingbot/ml/research/phase26d/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 26D — startup safety and configuration integrity validation. |
| `tradingbot/ml/research/phase27a/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27A — 30-day production validation backtest. |
| `tradingbot/ml/research/phase27a/trade_builder.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Build completed trades from unified pipeline replay records. |
| `tradingbot/ml/research/phase27b/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27B — read-only root cause investigation for zero trades (RSI filter). |
| `tradingbot/ml/research/phase27b/bar_tracer.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27B — per-bar read-only pipeline trace (no prediction cache). |
| `tradingbot/ml/research/phase27b/metrics.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27B — evidence aggregation and deliverable builders. |
| `tradingbot/ml/research/phase27b/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27B — root cause investigation for zero trades (READ ONLY). |
| `tradingbot/ml/research/phase27c/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27C — prediction cache key collision fix validation. |
| `tradingbot/ml/research/phase27d/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27D — post cache-fix 30-day production replay (READ ONLY). |
| `tradingbot/ml/research/phase27d/metrics.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27D metrics — measured production behavior after cache fix. |
| `tradingbot/ml/research/phase27d/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27D — full 30-day production replay after cache fix (READ ONLY). |
| `tradingbot/ml/research/phase27e/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27E — signal-to-execution bottleneck investigation (READ ONLY). |
| `tradingbot/ml/research/phase27e/metrics.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27E — trace 762 ML signals through pipeline stages. |
| `tradingbot/ml/research/phase27e/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27E — signal-to-execution bottleneck investigation (READ ONLY). |
| `tradingbot/ml/research/phase27f/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27F — replay portfolio state repair validation. |
| `tradingbot/ml/research/phase27f/metrics.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27F metrics — portfolio lifecycle and RiskGate before/after comparison. |
| `tradingbot/ml/research/phase27f/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27F — replay portfolio state repair validation. |
| `tradingbot/ml/research/phase27g/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27G — 30-day trade performance validation after replay fix. |
| `tradingbot/ml/research/phase27g/metrics.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27G — 30-day trade performance validation metrics (read-only). |
| `tradingbot/ml/research/phase27g/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27G — 30-day trade performance validation after replay fix. |
| `tradingbot/ml/research/phase27h/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27H — robustness and stress test validation. |
| `tradingbot/ml/research/phase27h/metrics.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27H — robustness and stress test metrics. |
| `tradingbot/ml/research/phase27h/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27H — robustness and stress test validation (read-only). |
| `tradingbot/ml/research/phase27h/stress_engine.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27H stress simulation engine (research-only, read-only). |
| `tradingbot/ml/research/phase27i/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27I — slippage root cause investigation. |
| `tradingbot/ml/research/phase27i/metrics.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27I — slippage root cause investigation metrics. |
| `tradingbot/ml/research/phase27i/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27I — slippage root cause investigation (read-only). |
| `tradingbot/ml/research/phase27i/slippage_decompose.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27I slippage decomposition utilities (research-only). |
| `tradingbot/ml/research/phase27j/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27J — edge decomposition investigation. |
| `tradingbot/ml/research/phase27j/edge_decompose.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27J per-trade edge decomposition (research-only). |
| `tradingbot/ml/research/phase27j/metrics.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27J — edge decomposition investigation metrics. |
| `tradingbot/ml/research/phase27j/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27J — edge decomposition investigation (read-only). |
| `tradingbot/ml/research/phase27k/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27K — losing trade root cause investigation. |
| `tradingbot/ml/research/phase27k/loser_enrich.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27K losing trade enrichment (research-only). |
| `tradingbot/ml/research/phase27k/metrics.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27K — losing trade root cause metrics. |
| `tradingbot/ml/research/phase27k/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27K — losing trade root cause investigation (read-only). |
| `tradingbot/ml/research/phase27l/metrics.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27L — exit engine investigation metrics. |
| `tradingbot/ml/research/phase27l/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27L — exit engine investigation (read-only simulation). |
| `tradingbot/ml/research/phase27m/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27M — exit strategy robustness validation. |
| `tradingbot/ml/research/phase27m/metrics.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27M — cross-window exit robustness metrics. |
| `tradingbot/ml/research/phase27m/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27M — exit strategy robustness across market windows (read-only). |
| `tradingbot/ml/research/phase27m/window_runner.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27M — multi-window replay and exit simulation runner. |
| `tradingbot/ml/research/phase27n/metrics.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27N — hybrid exit metrics, stability, Monte Carlo, ranking. |
| `tradingbot/ml/research/phase27n/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27N — hybrid exit architecture validation (read-only). |
| `tradingbot/ml/research/phase27n/window_runner.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27N — window loader reusing Phase 27M replay cache. |
| `tradingbot/ml/research/phase27o/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27O — out-of-sample hybrid exit validation. |
| `tradingbot/ml/research/phase27o/metrics.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27O — OOS metrics, generalization gap, Monte Carlo, ranking. |
| `tradingbot/ml/research/phase27o/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27O — out-of-sample hybrid exit validation (read-only). |
| `tradingbot/ml/research/phase27o/split.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27O — chronological train/validation split (70/30). |
| `tradingbot/ml/research/phase27o/window_runner.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 27O — window loader with OOS strategy simulation. |
| `tradingbot/ml/research/phase28a/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 28A — paper trading A/B validation (Hybrid B vs Time Exit). |
| `tradingbot/ml/research/phase28a/metrics.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 28A — A/B metrics, head-to-head, Monte Carlo, decision matrix. |
| `tradingbot/ml/research/phase28a/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 28A — paper trading A/B validation runner (read-only). |
| `tradingbot/ml/research/phase28a/window_runner.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 28A — window loader and dual-strategy simulation. |
| `tradingbot/ml/research/phase28b/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 28B — production integration validation for Hybrid B. |
| `tradingbot/ml/research/phase28b/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 28B — integration validation, failure scenarios, performance parity. |
| `tradingbot/ml/research/phase28c/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 28C — paper trading live validation (Hybrid B). |
| `tradingbot/ml/research/phase28c/data_collector.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 28C — collect live paper trade data from production journal. |
| `tradingbot/ml/research/phase28c/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 28C — paper trading live validation runner (read-only observation). |
| `tradingbot/ml/research/phase28c/validators.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 28C — Hybrid B trade validators and journal integrity. |
| `tradingbot/ml/research/phase28d/cache.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 28D — clear stale replay caches before fresh backtest. |
| `tradingbot/ml/research/phase28d/metrics.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 28D — backtest metrics and report builders. |
| `tradingbot/ml/research/phase28d/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 28D — fresh 30-day production backtest ($200, Hybrid B). |
| `tradingbot/ml/research/phase29b/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 29B — WPSQF production integration validation. |
| `tradingbot/ml/research/phase30a/replay_simulation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Replay Phase 29B trades with execution simulation — entries/exits unchanged. |
| `tradingbot/ml/research/phase30b/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 30A research package. |
| `tradingbot/ml/research/phase30b/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 30B — execution layer forensic audit (read-only, no code changes). |
| `tradingbot/ml/research/phase30c/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 30C research package. |
| `tradingbot/ml/research/phase30c/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 30C — Digital Broker Twin research (design only, no code changes). |
| `tradingbot/ml/research/phase30d/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 30D research package. |
| `tradingbot/ml/research/phase30e/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 30E research package. |
| `tradingbot/ml/research/phase31e/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 31E — replay portfolio state machine repair. |
| `tradingbot/ml/research/phase32g/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New |  |
| `tradingbot/ml/research/phase32h/generate_deliverables.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 32H — read-only feature pipeline integrity audit deliverables generator. |
| `tradingbot/ml/research/phase32i/generate_deliverables.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 32I — read-only Phase99 dataset parity audit deliverables. |
| `tradingbot/ml/research/phase33c/run_forensics.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 33C — rejected signal outcome audit (read-only forensic). |
| `tradingbot/ml/research/phase33d/replay.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 33D — production-faithful rejected signal replay (research only). |
| `tradingbot/ml/research/phase33d/run_forensic.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 33D — full rejected signal reconstruction & filter truth audit. |
| `tradingbot/ml/research/phase34a/run_all.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Run all Phase 34 engineering audits in order with tests. |
| `tradingbot/ml/research/phase34a/run_audit.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 34A — RAW ML Truth Audit (read-only forensic). |
| `tradingbot/ml/research/phase34b/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 34B — dataset label truth audit (research only). |
| `tradingbot/ml/research/phase34b/run_label_audit.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 34B — Dataset Label Truth Audit (read-only). |
| `tradingbot/ml/research/phase34c/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 34C — filter marginal value synthesis (research only). |
| `tradingbot/ml/research/phase34d/run_engineering_report.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 34D — Engineering Decision Report (synthesizes 34A-34C + 33D). |
| `tradingbot/ml/research/phase35/run_label_alignment.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 35 — Label Alignment & ML Retrain Readiness Audit (read-only). |
| `tradingbot/ml/research/phase36/retrain_validation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 36 — chronological retrain validation (research only). |
| `tradingbot/ml/research/phase36/run_phase36.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 36 — Aligned Dataset V3 + Chronological Retrain Validation. |
| `tradingbot/ml/research/phase37/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 37 — filter optimization (research only). |
| `tradingbot/ml/research/phase37/run_phase37.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 37 — Filter optimization measurement (read-only, no production changes). |
| `tradingbot/ml/research/phase38/run_phase38.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 38 — Walk-forward retrain on dataset_v3 with threshold sweep (research only). |
| `tradingbot/ml/research/phase39/run_phase39.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 39 — Expand candle coverage and rebuild dataset_v3 on fullest history. |
| `tradingbot/ml/research/phase3a/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 3A VOL edge research. |
| `tradingbot/ml/research/phase3a/vol_edge_research.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 3A — VOL edge reconstruction research (no live enable). |
| `tradingbot/ml/research/phase40/run_phase40.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 40 — Threshold sweep walk-forward retrain on expanded dataset_v3. |
| `tradingbot/ml/research/phase41/run_phase41.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 41 — Advanced model search + label generalization audit. |
| `tradingbot/ml/research/phase42/run_phase42.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 42 — Feature parity audit, spread patch, event bias report. |
| `tradingbot/ml/research/phase43/run_phase43.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 43 — Retrain on balanced event subsets with walk-forward threshold sweep. |
| `tradingbot/ml/research/phase44/run_phase44.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 44 — Integration gate synthesis across phases 42-43. |
| `tradingbot/ml/research/phase45/run_phase45.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 45 — Structure-event dataset v5 + label quality audit. |
| `tradingbot/ml/research/phase46/run_phase46.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 46 — ML signal-aligned dataset v6 (production population). |
| `tradingbot/ml/research/phase47/run_phase47.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 47 — Compare walk-forward retrain: v4 vs v5 vs v6. |
| `tradingbot/ml/research/phase48/run_phase48.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 48 — Final integration gate after structure + ML signal research. |
| `tradingbot/ml/research/phase49/ml_capture.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 49 — expanded ML capture with fixed bar indexing. |
| `tradingbot/ml/research/phase49/run_phase49.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 49 — Fix bar index + expand ML capture 2021-2026. |
| `tradingbot/ml/research/phase4a/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 3A package. |
| `tradingbot/ml/research/phase4a/adaptive_quality_backtest.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 4A — Adaptive quality engine backtest comparison (old AND-gate vs quality score). |
| `tradingbot/ml/research/phase50/run_phase50.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 50 — Strict multi-year walk-forward gate on v7. |
| `tradingbot/ml/research/phase51/run_phase51.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 51 — Profitability proximity assessment. |
| `tradingbot/ml/research/phase52/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 52 — label & dataset diagnosis. |
| `tradingbot/ml/research/phase52/label_audit_v7.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 52 — label & dataset diagnosis on v7 (research only). |
| `tradingbot/ml/research/phase53/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 53 — execution funnel audit. |
| `tradingbot/ml/research/phase53/execution_funnel_audit.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 53 — execution funnel edge-loss audit (research only). |
| `tradingbot/ml/research/phase54/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 54 — model sweep. |
| `tradingbot/ml/research/phase54/model_sweep.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 54 — model sweep on strict walk-forward (research only). |
| `tradingbot/ml/research/phase55/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 55 — feature noise audit. |
| `tradingbot/ml/research/phase55/feature_noise_audit.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 55 — feature importance & noise audit on v7 (research only). |
| `tradingbot/ml/research/phase56/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 56 — treatment synthesis. |
| `tradingbot/ml/research/phase56/treatment_synthesis.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 56 — treatment synthesis & re-gate (research only). |
| `tradingbot/ml/research/phase57/trade_quality_simulation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 57A — TradeQuality funnel counterfactual simulation (research only). |
| `tradingbot/ml/research/phase57/trend_regime_deep_dive.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 57B — TREND regime walk-forward deep dive (research only). |
| `tradingbot/ml/research/phase57/write_phase57_report.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 57 — combined report writer and status updates (research only). |
| `tradingbot/ml/research/phase58/trend_only_model.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 58 — TREND-only RF re-gate on top-5 features (research only). |
| `tradingbot/ml/research/phase59/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 59 — horizon sweep, feature expansion, ensemble (research only). |
| `tradingbot/ml/research/phase59/horizon_feature_expansion.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 59 — label horizon sweep, feature expansion, ensemble (research only). |
| `tradingbot/ml/research/phase60/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 60 — AUC lift, trade-count gate, execution counterfactual (research only). |
| `tradingbot/ml/research/phase60/auc_lift_and_validation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 60 — AUC lift experiments, trade-count floor, execution counterfactual (research only). |
| `tradingbot/ml/research/phase61/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 61 — execution-path shadow validation (research only). |
| `tradingbot/ml/research/phase61/execution_shadow_validation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 61 — execution-path shadow validation for TREND RF-10f (research only). |
| `tradingbot/ml/research/phase62/trade_quality_shadow_analysis.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 62 — TradeQuality shadow analysis (research only). Analyze WHY TradeQuality rejects 93%+ of hi |
| `tradingbot/ml/research/phase63/trade_quality_shadow_calibration.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 63 — TradeQuality shadow recalibration (research only). Shadow-only policy: engine alias, thre |
| `tradingbot/ml/research/phase64/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 64 — AdaptiveRisk shadow review (research only). |
| `tradingbot/ml/research/phase64/adaptive_risk_shadow_review.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 64 — AdaptiveRisk shadow review (research only). Analyze AR-blocked TREND HC signals from phas |
| `tradingbot/ml/research/phase65/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 65 — AUC lift via TREND feature engineering (research only). |
| `tradingbot/ml/research/phase65/auc_feature_lift.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 65 — AUC lift via TREND-specific feature engineering (research only). Engineer interactions/ra |
| `tradingbot/ml/research/phase66/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 66 — Label & horizon experiments (research only). |
| `tradingbot/ml/research/phase66/label_horizon_experiments.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 66 — Label & horizon experiments on TREND subset (research only). Sweep future_window_bars (24 |
| `tradingbot/ml/research/phase67/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 67 — TREND specialization & ensemble (research only). |
| `tradingbot/ml/research/phase67/trend_ensemble_specialization.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 67 — TREND specialization + RF+HGB ensemble (research only). Test configs A–F on TREND subset  |
| `tradingbot/ml/research/phase68/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 68 - Combined shadow revalidation. |
| `tradingbot/ml/research/phase68/combined_shadow_revalidation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 68 — Combined shadow revalidation (research only). Combine phase63 TQ alias @0.40 + AR product |
| `tradingbot/ml/research/phase6a/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 6A package. |
| `tradingbot/ml/research/phase6a/fault_injection_live.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 6A — live-path fault injection (isolated, no production mutation). |
| `tradingbot/ml/research/phase6a/monte_carlo_pa.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 6A — Monte Carlo on PA trade R-multiples. |
| `tradingbot/ml/research/phase6a/vol_v2_expansion.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 6A — VOL v2 EXPANSION-only research profile (no live enable). |
| `tradingbot/ml/research/phase6a/walk_forward_pa.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 6A — PA walk-forward (6×30d rolling windows). |
| `tradingbot/ml/research/phase70/fix_roadmap_final_review.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 70 — FIX Roadmap Final Gate Review (closure, research only). Synthesize phases 62-68 + FIX_ROA |
| `tradingbot/ml/research/phase7a/adaptive_quality_v2.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 7A — Adaptive Quality v2 research (dynamic weights + threshold sweep). |
| `tradingbot/ml/research/phase8a/ml_kernel_rehab.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 8A — ML Kernel rehabilitation research (shadow-only). |
| `tradingbot/ml/research/phase9a/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New |  |
| `tradingbot/ml/research/phase9a/pm_v2_research.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 9A — Position Management v2 research profiles and backtest helpers. |
| `tradingbot/ml/research/phase_final_audit/__init__.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase Final — Pre-paper system integrity audit (READ ONLY). |
| `tradingbot/ml/research/phase_final_audit/run_investigation.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Final pre-paper system integrity audit — READ ONLY investigation. |
| `tradingbot/ml/research/run_engineering_pipeline.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Run Phase 49-51 strict profitability pipeline. |
| `tradingbot/ml/research/run_fix_pipeline.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Run fix pipeline phases 62→70 sequentially (research only). |
| `tradingbot/ml/research/run_live_pipeline.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Run LIVE profitable robot roadmap phases L0-L6 (research orchestrator). |
| `tradingbot/ml/research/run_treatment_pipeline.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Run treatment pipeline phases 52→61 sequentially (research only). |
| `tradingbot/ml/research/v41_isolated/cost_inventory.py` | 2026-09-09 05:26:55 +0330 | update project files | Read-only inventory of possible real cost sources. Research only. |
| `tradingbot/ml/research/v41_isolated/run.py` | 2026-09-09 05:26:55 +0330 | update project files | Phase 1.5.36–1.5.40 orchestrator — offline isolated v41 TREND evidence. |
| `tradingbot/ml/research/v41_isolated/run_cost.py` | 2026-09-09 05:26:55 +0330 | update project files | Offline orchestrator for v41 cost realism & robustness (no live path). |
| `tradingbot/ml/research/v41_isolated/run_followup.py` | 2026-09-09 05:26:55 +0330 | update project files | Phase 1.5.46–1.5.50 orchestrator — offline follow-up, does not rewrite prior JSON. |
| `tradingbot/ml/shadow/phase53a_gate.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 53A — ML kernel live gate (Phase 51 real-trade evidence). |
| `tradingbot/ml/shadow/phase53a_metrics.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 53A — ML kernel validation on Phase 51 forward-demo closed trades. |
| `tradingbot/ml/shadow/phase5a_drift.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 5A — drift analysis (train vs shadow live/replay). |
| `tradingbot/ml/shadow/phase5a_metrics.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 5A — ML Kernel certification metrics (shadow analysis only). |
| `tradingbot/ml/shadow/phase5a_shadow_replay.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 5A — build shadow_trade_record rows from PA replay + ML shadow probe. |
| `tradingbot/services/phase6a_production_cert.py` | 2026-08-19 19:38:20 +0330 | Initial snapshot - TradingBot New | Phase 6A — final production certification orchestrator. |

## 3. Documentation contradiction map

Markdown inventory: `docs/` = **103** files; `docs_v2/` = **140** files.

Full paths:

<details><summary>docs/ file list</summary>

- `docs/ARCHITECTURE_FA.md`
- `docs/CAPABILITIES.md`
- `docs/ONBOARDING_FA.md`
- `docs/OPERATOR_EVIDENCE_REQUEST.md`
- `docs/PHASE100_RETRACE_EXPANSION_FORENSICS.md`
- `docs/PHASE101_ENTRY_VS_EXIT.md`
- `docs/PHASE102_CLUSTER_TIMING_FORENSICS.md`
- `docs/PHASE103_STRUCTURE_AT_RETRACEMENT.md`
- `docs/PHASE104_MINIMAL_DISCRIMINATOR.md`
- `docs/PHASE105_DISCRIMINATOR_GATE.md`
- `docs/PHASE106_NON_OHLC_DATA_INVENTORY.md`
- `docs/PHASE107_TICK_INTRABAR_RESEARCH.md`
- `docs/PHASE108_SPREAD_PATH_RESEARCH.md`
- `docs/PHASE109_HTF_CONTEXT_RESEARCH.md`
- `docs/PHASE110_NEWS_CONTEXT_RESEARCH.md`
- `docs/PHASE111_MULTISOURCE_ALIGNMENT.md`
- `docs/PHASE112_NON_OHLC_DISCRIMINATOR_GATE.md`
- `docs/PHASE113_NON_OHLC_FINAL_GATE.md`
- `docs/PHASE114_NON_OHLC_ACQUISITION_CONTRACT.md`
- `docs/PHASE115_NON_OHLC_DATA_ACQUISITION.md`
- `docs/PHASE116_DATA_SOURCE_RESEARCH.md`
- `docs/PHASE117_OPERATOR_SOURCE_RESOLUTION.md`
- `docs/PHASE2_STEP1_MT5_FA.md`
- `docs/PHASE2_STEP2_STRATEGIES_FA.md`
- `docs/PHASE2_STEP3_RISK_FA.md`
- `docs/PHASE2_STEP4_LIVE_LOOP_FA.md`
- `docs/PHASE2_STEPC_POSITION_FA.md`
- `docs/PHASE3_BACKTEST_FA.md`
- `docs/PHASE54_56_EVIDENCE_CLOSURE.md`
- `docs/PHASE54_ACCOUNT_BROKER_EVIDENCE.md`
- `docs/PHASE55_COST_SCENARIO_ANALYSIS.md`
- `docs/PHASE56_SYMBOL_MAPPING_FINAL_GATE.md`
- `docs/PHASE57_60_EVIDENCE_CLOSURE.md`
- `docs/PHASE57_ACCOUNT_PRODUCT_FORENSICS.md`
- `docs/PHASE58_COMMISSION_ACCOUNTABILITY.md`
- `docs/PHASE59_SYMBOL_EQUIVALENCE_FORENSICS.md`
- `docs/PHASE60_UNIFIED_EVIDENCE_GATE.md`
- `docs/PHASE61_63_EDGE_AND_NEXT_STEP_CLOSURE.md`
- `docs/PHASE61_EDGE_SURVIVAL_FORENSICS.md`
- `docs/PHASE62_OPERATOR_ACTION_ECONOMICS.md`
- `docs/PHASE63_NEXT_STEP_GATE.md`
- `docs/PHASE64_67_STRATEGY_DIAGNOSIS_CLOSURE.md`
- `docs/PHASE64_STRATEGY_EVENT_FORENSICS.md`
- `docs/PHASE65_DIAGNOSTIC_EXPERIMENTS.md`
- `docs/PHASE66_STRATEGY_ROOT_CAUSE.md`
- `docs/PHASE67_NEXT_RESEARCH_GATE.md`
- `docs/PHASE68_EXIT_FORENSICS.md`
- `docs/PHASE69_EXIT_GEOMETRY.md`
- `docs/PHASE70_EXIT_COUNTERFACTUALS.md`
- `docs/PHASE71_EXTREME_WINNER.md`
- `docs/PHASE72_EXIT_ROOT_CAUSE.md`
- `docs/PHASE73_EXIT_RESEARCH_GATE.md`
- `docs/PHASE74_PROFIT_GIVEBACK_FORENSICS.md`
- `docs/PHASE75_EXIT_COUNTERFACTUALS.md`
- `docs/PHASE76_SL_VS_PROFIT_PROTECTION.md`
- `docs/PHASE77_EXIT_GEOMETRY.md`
- `docs/PHASE78_TIME_EXIT_FORENSICS.md`
- `docs/PHASE79_EXIT_SIDE_REGIME.md`
- `docs/PHASE80_EXTREME_WINNER_AUDIT.md`
- `docs/PHASE81_EXIT_RESEARCH_GATE.md`
- `docs/PHASE82_PROFIT_PROTECTION_DESIGN.md`
- `docs/PHASE83_PROFIT_PROTECTION_COUNTERFACTUALS.md`
- `docs/PHASE84_TAIL_PRESERVATION.md`
- `docs/PHASE85_RESCUE_VS_DESTRUCTION.md`
- `docs/PHASE86_PROFIT_PROTECTION_OOS.md`
- `docs/PHASE87_PROFIT_PROTECTION_INTERACTIONS.md`
- `docs/PHASE88_EXIT_DESIGN_SPEC.md`
- `docs/PHASE89_PROFIT_PROTECTION_GATE.md`
- `docs/PHASE90_PROFIT_GIVEBACK_PATH_FORENSICS.md`
- `docs/PHASE91_REVERSAL_TIMING_FORENSICS.md`
- `docs/PHASE92_MFE_MAE_CONDITIONAL_FORENSICS.md`
- `docs/PHASE93_TAIL_PRESERVATION_FORENSICS.md`
- `docs/PHASE94_CLUSTER_FORENSICS.md`
- `docs/PHASE95_PROTECTION_FAMILY_V2.md`
- `docs/PHASE96_PROTECTION_ROBUSTNESS_GATE.md`
- `docs/PHASE97_PROFIT_PROTECTION_FINAL_GATE.md`
- `docs/PHASE98_FIRST_FAVORABLE_STATE.md`
- `docs/PHASE99_PATH_VELOCITY_PERSISTENCE.md`
- `docs/PROCESSING_MAP.md`
- `docs/RESEARCH_LEDGER.md`
- `docs/WHITEBOARD_FA.md`
- `docs/adaptive_regime_live_truth_7d.md`
- `docs/hourly_edge_heatmap.md`
- `docs/phase10_1_architecture_audit.md`
- `docs/phase10_3_trade_integrity_audit.md`
- `docs/phase34a_final_diagnosis.md`
- `docs/phase34b_session_truth_report.md`
- `docs/phase8_1_dataset_build.md`
- `docs/phase8_2_research_audit.md`
- `docs/phase8_data_collection.md`
- `docs/phase9_full_health_audit.md`
- `docs/robot_behavior_audit/configuration_truth.md`
- `docs/robot_behavior_audit/dead_features.md`
- `docs/robot_behavior_audit/decision_map.md`
- `docs/robot_behavior_audit/duplicate_work.md`
- `docs/robot_behavior_audit/execution_flow.md`
- `docs/robot_behavior_audit/executive_summary.md`
- `docs/robot_behavior_audit/position_lifecycle.md`
- `docs/robot_behavior_audit/reliability_scorecard.md`
- `docs/robot_behavior_audit/robot_overview.md`
- `docs/robot_behavior_audit/strategy_inventory.md`
- `docs/runtime_config_diff.md`
- `docs/session_filter_false_negative_analysis.md`

</details>

<details><summary>docs_v2/ file list</summary>

- `docs_v2/01_truth/CHATGPT_BOOTSTRAP.md`
- `docs_v2/01_truth/CHATGPT_MEMORY_INTEGRITY.md`
- `docs_v2/01_truth/CONFIGURATION_TRUTH.md`
- `docs_v2/01_truth/CURRENT_RUNTIME_STATE.md`
- `docs_v2/01_truth/CURRENT_STATE.md`
- `docs_v2/01_truth/DEMO_REAL_SYMBOL_COST_DESIGN.md`
- `docs_v2/01_truth/DOCUMENTATION_COMPLETION_CONTRACT.md`
- `docs_v2/01_truth/DOCUMENTATION_MEMORY_BASELINE.md`
- `docs_v2/01_truth/DOCUMENTATION_MEMORY_HARDENING_V2.md`
- `docs_v2/01_truth/DOCUMENTATION_MEMORY_OPERATIONALIZATION.md`
- `docs_v2/01_truth/DOCUMENTATION_SYSTEM_AUDIT.md`
- `docs_v2/01_truth/DOCUMENTATION_VERIFICATION_REPORT.md`
- `docs_v2/01_truth/DOCUMENTATION_WATCHED_CODE_AUDIT.md`
- `docs_v2/01_truth/DOCUMENT_OWNERSHIP_MATRIX.md`
- `docs_v2/01_truth/FULL_REPOSITORY_SOURCE_OF_TRUTH.md`
- `docs_v2/01_truth/KNOWLEDGE_CONTRACT.md`
- `docs_v2/01_truth/KNOWN_ISSUES.md`
- `docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md`
- `docs_v2/01_truth/OPERATOR_BROKER_EVIDENCE_COLLECTION.md`
- `docs_v2/01_truth/OPERATOR_BROKER_POLICY_DECISION.md`
- `docs_v2/01_truth/PHASE26_CLOSURE.md`
- `docs_v2/01_truth/PHASE27_10_DATASET_SYMBOL_BINDING.md`
- `docs_v2/01_truth/PHASE27_11_HISTORICAL_BIDASK.md`
- `docs_v2/01_truth/PHASE27_12_COMMISSION_EVIDENCE.md`
- `docs_v2/01_truth/PHASE27_13_SWAP_POLICY.md`
- `docs_v2/01_truth/PHASE27_14_SLIPPAGE_MODEL.md`
- `docs_v2/01_truth/PHASE27_15_COST_COMPLETENESS_GATE.md`
- `docs_v2/01_truth/PHASE27_16_FINAL_VALIDATION_GATE.md`
- `docs_v2/01_truth/PHASE27_17_REAL_BROKER_EVIDENCE.md`
- `docs_v2/01_truth/PHASE27_18_HISTORICAL_BIDASK_CLOSURE.md`
- `docs_v2/01_truth/PHASE27_19_COMMISSION_CLOSURE.md`
- `docs_v2/01_truth/PHASE27_20_DATASET_MAPPING_CLOSURE.md`
- `docs_v2/01_truth/PHASE27_21_EVIDENCE_SYNTHESIS.md`
- `docs_v2/01_truth/PHASE27_22_COMMISSION_FORENSIC.md`
- `docs_v2/01_truth/PHASE27_23_BIDASK_EXPANSION.md`
- `docs_v2/01_truth/PHASE27_24_EXECUTION_COST_FORENSICS.md`
- `docs_v2/01_truth/PHASE27_25_CANONICAL_BIDASK_COVERAGE.md`
- `docs_v2/01_truth/PHASE27_26_CANONICAL_BIDASK_COVERAGE.md`
- `docs_v2/01_truth/PHASE27_27_DATASET_SYMBOL_BINDING.md`
- `docs_v2/01_truth/PHASE27_28_COMMISSION_EVIDENCE.md`
- `docs_v2/01_truth/PHASE27_29_SWAP_EVIDENCE.md`
- `docs_v2/01_truth/PHASE27_30_SLIPPAGE_EVIDENCE.md`
- `docs_v2/01_truth/PHASE27_31_EXECUTION_EVIDENCE.md`
- `docs_v2/01_truth/PHASE27_32_FINAL_COST_EVIDENCE_GATE.md`
- `docs_v2/01_truth/PHASE27_33_EV_EQ_RESOLUTION.md`
- `docs_v2/01_truth/PHASE27_5_FINAL_BROKER_COST_GATE.md`
- `docs_v2/01_truth/PHASE27_6_FINAL_EVIDENCE_GATE.md`
- `docs_v2/01_truth/PHASE27_7_FINAL_BLOCKER_CLOSURE.md`
- `docs_v2/01_truth/PHASE27_8_POLICY_LOCK.md`
- `docs_v2/01_truth/PHASE27_9_REAL_BROKER_EVIDENCE.md`
- `docs_v2/01_truth/PHASE27_BROKER_REALITY.md`
- `docs_v2/01_truth/PRODUCTION_READINESS_AUDIT.md`
- `docs_v2/01_truth/PRODUCTION_RESEARCH_BOUNDARY.md`
- `docs_v2/01_truth/PROJECT_DECISION_BASELINE.md`
- `docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md`
- `docs_v2/01_truth/SOURCE_OF_TRUTH.md`
- `docs_v2/02_architecture/ARCHITECTURE.md`
- `docs_v2/02_architecture/COMPONENT_BOUNDARIES.md`
- `docs_v2/02_architecture/DATA_FLOW.md`
- `docs_v2/02_architecture/MODULE_MAP.md`
- `docs_v2/02_architecture/PIPELINE.md`
- `docs_v2/02_architecture/SYSTEM_ARCHITECTURE.md`
- `docs_v2/02_research/PHASE28_0_PERFORMANCE_FOUNDATION.md`
- `docs_v2/02_research/PHASE28_1_FULL_BASELINE.md`
- `docs_v2/02_research/PHASE28_2_WALK_FORWARD.md`
- `docs_v2/02_research/PHASE28_3_MONTE_CARLO.md`
- `docs_v2/02_research/PHASE28_4_STRATEGY_DIAGNOSIS.md`
- `docs_v2/02_research/PHASE29_RESEARCH_TAPE.md`
- `docs_v2/02_research/PHASE30_UNCHANGED_STRATEGY_EVALUATION.md`
- `docs_v2/02_research/PHASE31_EVENT_INDEPENDENCE.md`
- `docs_v2/02_research/PHASE32_WALK_FORWARD.md`
- `docs_v2/02_research/PHASE33_ROBUSTNESS.md`
- `docs_v2/02_research/PHASE34_STATISTICAL_VALIDATION.md`
- `docs_v2/02_research/PHASE35_EXECUTION_REALITY.md`
- `docs_v2/02_research/PHASE36_STRATEGY_VERDICT.md`
- `docs_v2/02_research/PHASE37_LONG_HORIZON_TAPE.md`
- `docs_v2/02_research/PHASE38_INTELLIGENT_EVIDENCE_ACQUISITION.md`
- `docs_v2/02_research/PHASE39_BROKER_ECONOMICS_EXECUTION.md`
- `docs_v2/02_research/PHASE40_FULL_HORIZON_VALIDATION.md`
- `docs_v2/02_research/PHASE40_RECOVERY_STATUS.md`
- `docs_v2/02_research/PHASE41_BLOCKER_MATRIX.md`
- `docs_v2/02_research/PHASE41_FINAL_EVIDENCE_CLOSURE.md`
- `docs_v2/02_research/PHASE42_BROKER_COST_EXECUTION_CLOSURE.md`
- `docs_v2/02_research/PHASE42_EVIDENCE_MATRIX.md`
- `docs_v2/02_research/PHASE42_EXECUTABLE_READINESS.md`
- `docs_v2/02_research/PHASE43_BROKER_COST_EXECUTION_VALIDATION.md`
- `docs_v2/02_research/PHASE43_COST_GATE_STATUS.md`
- `docs_v2/02_research/PHASE43_EXECUTABLE_READINESS.md`
- `docs_v2/02_research/PHASE44_46_BLOCKER_MATRIX.md`
- `docs_v2/02_research/PHASE44_EXECUTABLE_BACKTEST_READINESS.md`
- `docs_v2/02_research/PHASE45_EVENT_OOS_REGIME_ROBUSTNESS.md`
- `docs_v2/02_research/PHASE46_PRODUCTION_LIVE_PARITY_AUDIT.md`
- `docs_v2/02_research/PHASE47_50_BLOCKER_MATRIX.md`
- `docs_v2/02_research/PHASE47_BLOCKER_CLOSURE.md`
- `docs_v2/02_research/PHASE48_EXECUTABLE_BACKTEST.md`
- `docs_v2/02_research/PHASE49_FINAL_EVENT_OOS_VALIDATION.md`
- `docs_v2/02_research/PHASE50_FINAL_PRODUCTION_PARITY.md`
- `docs_v2/02_research/PHASE51_53_BLOCKER_MATRIX.md`
- `docs_v2/02_research/PHASE51_FINAL_EVIDENCE_CLOSURE.md`
- `docs_v2/02_research/PHASE52_OPTIMIZATION_GATE.md`
- `docs_v2/02_research/PHASE53_SHADOW_READINESS.md`
- `docs_v2/03_runtime/CONFIGURATION.md`
- `docs_v2/03_runtime/EXECUTION_FLOW.md`
- `docs_v2/03_runtime/LIVE_LOOP.md`
- `docs_v2/03_runtime/LIVE_RUNTIME_PATH.md`
- `docs_v2/03_runtime/STARTUP.md`
- `docs_v2/03_runtime/STARTUP_AND_SHUTDOWN.md`
- `docs_v2/04_strategy/ACTIVE_STRATEGIES.md`
- `docs_v2/04_strategy/PA_LIVE_EDGE_AUDIT.md`
- `docs_v2/04_strategy/PRICE_ACTION_LIVE_SPEC.md`
- `docs_v2/04_strategy/SIGNAL_FLOW.md`
- `docs_v2/04_strategy/STRATEGY.md`
- `docs_v2/05_risk/POSITION_LIFECYCLE.md`
- `docs_v2/05_risk/RISK.md`
- `docs_v2/05_risk/RISKGATE_SPEC.md`
- `docs_v2/05_risk/RISK_AND_EXECUTION_BOUNDARY.md`
- `docs_v2/06_data/DATA_CONTRACTS.md`
- `docs_v2/06_data/DATA_PIPELINE.md`
- `docs_v2/07_ml/CALIBRATION_STATE.md`
- `docs_v2/07_ml/ML_ARCHITECTURE.md`
- `docs_v2/07_ml/ML_STATUS.md`
- `docs_v2/07_ml/ML_SYSTEM_STATE.md`
- `docs_v2/07_ml/MODEL_REGISTRY.md`
- `docs_v2/07_ml/V41_CALIBRATION_EVIDENCE.md`
- `docs_v2/07_ml/V41_COST_EVIDENCE_AUDIT.md`
- `docs_v2/07_ml/V41_COST_ROBUSTNESS_EVIDENCE.md`
- `docs_v2/07_ml/V41_DECISION_AUDIT.md`
- `docs_v2/07_ml/V41_ROBUSTNESS_EVIDENCE.md`
- `docs_v2/07_ml/V41_TREND_REPLAY_EVIDENCE.md`
- `docs_v2/08_testing/TESTING.md`
- `docs_v2/09_operations/OBSERVABILITY.md`
- `docs_v2/09_operations/RUNBOOK.md`
- `docs_v2/10_history/CHANGELOG.md`
- `docs_v2/99_change_control/CHATGPT_CURSOR_WORKFLOW.md`
- `docs_v2/99_change_control/DOCUMENTATION_IMPACT_MAP.md`
- `docs_v2/99_change_control/DOCUMENTATION_UPDATE_PROTOCOL.md`
- `docs_v2/README.md`
- `docs_v2/_system/AUTO_UPDATE.md`
- `docs_v2/_system/DOCUMENTATION_RULES.md`
- `docs_v2/_system/DOC_SCHEMA.md`

</details>

### Code ground truth (verified this audit)

| Topic | What code actually does | Evidence |
|-------|-------------------------|----------|
| Pipeline stage count | **6 stages**: Data → Indicator → Signal → **SignalFilter** → Risk → Execution | `tradingbot/kernel/trading_kernel.py` lines 84–91 |
| SignalFilter default | Wired; default **OFF** (pass-through) unless `TRADINGBOT_SIGNAL_FILTER=WPSQF` | `tradingbot/services/signal_filter_mode.py` `resolve_signal_filter_mode()` |
| Live TIMEFRAMES | `LIVE_TRADING_CONFIG['TIMEFRAMES']=['5m','15m','4h']` but `get_live_config()` **forces `['5m']`** when `MULTI_ENGINE_ROUTER_ENABLED` / `VOL_REGIME_ENABLED` / `ADAPTIVE_REGIME_ENABLED` | `tradingbot/config/live.py` `get_live_config()` ~228–242; router default **true** |
| TIMEFRAME_CONFIGS | Dict for 1m/5m/15m/1h/4h "ULTRA AGGRESSIVE" thresholds; `get_timeframe_config()` defined | **No live/backtest call sites** found outside `live.py` itself (plus one research audit string) |
| Active live strategy | PA primary under `PA_PRODUCTION_LOCK` default true; VOL/Adaptive not selected for orders when lock holds | `tradingbot/services/pa_production_lock.py`; `docs_v2/04_strategy/ACTIVE_STRATEGIES.md` aligns |
| RiskGate position caps | Defaults from config/`PRICE_ACTION`: total **3**, per-symbol **2**; risk/trade **0.005** | `tradingbot/config/live.py` L42–52; `tradingbot/adapters/risk_gate.py` `__init__` ~862–876 |

### Subsystem contradiction table (docs vs code)

| Doc | Claim (summary) | Verdict vs code | Notes |
|-----|-----------------|-----------------|-------|
| `docs_v2/02_architecture/PIPELINE.md` | Six stages; SignalFilter registered; default OFF | **MATCHES_CODE** | Cites kernel lines |
| `docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md` | Six stages; M5 forced when router on | **MATCHES_CODE** | |
| `docs_v2/01_truth/SOURCE_OF_TRUTH.md` | Six stages; notes legacy 5-stage conflict | **MATCHES_CODE** | Explicitly documents KI area |
| `docs_v2/02_architecture/ARCHITECTURE.md` | Six stages | **MATCHES_CODE** | |
| `docs_v2/02_architecture/SYSTEM_ARCHITECTURE.md` | Includes SignalFilterStage | **MATCHES_CODE** | |
| `docs_v2/02_architecture/DATA_FLOW.md` | SignalFilter WPSQF default OFF | **MATCHES_CODE** | |
| `docs_v2/02_architecture/MODULE_MAP.md` | SignalFilter YES (pass-through when OFF) | **MATCHES_CODE** | |
| `docs_v2/03_runtime/LIVE_LOOP.md` | Six stages; default market XAUUSD_i:M5 | **MATCHES_CODE** | |
| `docs_v2/03_runtime/CONFIGURATION.md` | TIMEFRAMES list 5m/15m/4h overridden to 5m when router on | **MATCHES_CODE** | |
| `docs_v2/04_strategy/ACTIVE_STRATEGIES.md` | Live selected = priceaction; kernel TFs `["5m"]` | **MATCHES_CODE** | |
| `docs_v2/05_risk/RISKGATE_SPEC.md` | Ordered gate list; meta observer never rejects | **MATCHES_CODE** | Spot-checked against `RiskGate.evaluate` structure |
| `docs_v2/05_risk/RISK.md` | Max positions 3/2 | **MATCHES_CODE** | Matches live.py defaults |
| `docs_v2/01_truth/CURRENT_STATE.md` | Six stages; SignalFilter default OFF | **MATCHES_CODE** | |
| `docs_v2/01_truth/KNOWN_ISSUES.md` | Notes 5-stage vs 6-stage; M5-only residual wording | **MATCHES_CODE** (as issue registry) | |
| `docs/CAPABILITIES.md` §1 | Kernel M5-only when router on; also says "pipeline ۵ مرحله" | **CONTRADICTS_CODE** (stage count) / **MATCHES_CODE** (M5 forcing) | Mixed; stage claim stale |
| `docs/ARCHITECTURE_FA.md` | Comment `pipeline 5-stage` | **CONTRADICTS_CODE** | Should be 6 with SignalFilter |
| `docs/WHITEBOARD_FA.md` | Pipeline diagram: داده→اندیکاتور→سیگنال→ریسک→اجرا (5) | **CONTRADICTS_CODE** | Omits SignalFilter |
| `docs/ONBOARDING_FA.md` | Describes M5/M15/H4 as live TFs without M5-only force | **CONTRADICTS_CODE** (live cycle TFs) / **STALE_HISTORICAL** for multi-TF presets | Presets still exist; kernel cycle is M5 when router on |
| `دستورات_اجرایی.md` (repo root) | TF = M5+M15+H4 همزمان; max pos 3/2; risk 0.5% | **CONTRADICTS_CODE** on simultaneous TFs; **MATCHES_CODE** on risk/caps | Entry-doc still teaches multi-TF live loop |
| `docs/robot_behavior_audit/*` | Six-stage flow; TIMEFRAME_CONFIGS unused | **MATCHES_CODE** | Prior audit; still accurate on dead TIMEFRAME_CONFIGS |
| `docs/PHASE*.md` / `docs_v2/02_research/PHASE*.md` / most `docs_v2/01_truth/PHASE27_*.md` | Point-in-time research closures | **STALE_HISTORICAL** | Not current operator runbooks; retain as research archive |
| `docs_v2/_system/*`, `99_change_control/*` | Process/schema | N/A (meta-docs) | Not runtime claims |

### Known examples — explicit verification

1. **Pipeline 5 vs 6 / SignalFilterStage:** Code registers six stages including `SignalFilterStage`. Canonical `docs_v2` architecture/truth docs match. Several Persian onboarding/architecture docs still say five stages → **CONTRADICTS_CODE**.
2. **Live timeframes M5-only vs M5/M15/H4:** With default `MULTI_ENGINE_ROUTER_ENABLED=true`, `get_live_config()` sets `TIMEFRAMES=["5m"]`. Root ops doc and parts of ONBOARDING still imply concurrent M5/M15/H4 → **CONTRADICTS_CODE** for the live kernel cycle. Per-TF presets remain in code for backtest/other modes.
3. **TIMEFRAME_CONFIGS:** Defined in `live.py`; `get_timeframe_config()` has **no** callers in live/backtest paths → **dead configuration** (matches prior `docs/robot_behavior_audit/dead_features.md`).

## 4. Config / flag inventory

### 4.1 `tradingbot/config/live.py` env-driven flags

| Env key | Config key | Default | Status | Phase/doc justification (from nearby comment) | Productionish consumers (sample) |
|---------|------------|---------|--------|-----------------------------------------------|----------------------------------|
| `TRADINGBOT_ACCOUNT_ENV` | `—` | `—` | **PROD_WIRED** |  | `tradingbot/adapters/symbols.py` |
| `TRADINGBOT_REAL_SYMBOL` | `—` | `PRIMARY_SYMBOL` | **DEFINED_ONLY** |  | — |
| `MT5_LOGIN` | `MT5_LOGIN` | `—` | **PROD_WIRED** | MT5 Connection Settings — loaded from environment (see legacy_loader.py) | `tradingbot/adapters/legacy_loader.py`, `tradingbot/adapters/mt5_utils.py`, `tradingbot/config/engine_settings.py` |
| `MT5_PASSWORD` | `MT5_PASSWORD` | `''` | **PROD_WIRED** |  | `tradingbot/adapters/legacy_loader.py`, `tradingbot/adapters/mt5_utils.py`, `tradingbot/config/engine_settings.py` |
| `MT5_SERVER` | `MT5_SERVER` | `''` | **PROD_WIRED** |  | `tradingbot/adapters/legacy_loader.py`, `tradingbot/adapters/mt5_utils.py`, `tradingbot/config/engine_settings.py` |
| `EMAIL_USERNAME` | `EMAIL_USERNAME` | `''` | **DEFINED_ONLY** |  | — |
| `EMAIL_PASSWORD` | `EMAIL_PASSWORD` | `''` | **PROD_WIRED** |  | `tradingbot/config/engine_settings.py` |
| `EMAIL_TO` | `EMAIL_TO` | `''` | **DEFINED_ONLY** |  | — |
| `EMAIL_FROM` | `EMAIL_FROM` | `''` | **DEFINED_ONLY** |  | — |
| `PA_PRODUCTION_LOCK` | `PA_PRODUCTION_LOCK` | `'true'` | **PROD_WIRED** | Phase 50A: lock live bot to PA+Meta only — VOL/Adaptive log-only, never selected. | `tradingbot/adapters/multi_engine_router.py`, `tradingbot/services/pa_production_lock.py`, `tradingbot/services/phase6a_production_cert.py` |
| `DEMO_DISABLE_SESSION_FILTER` | `DEMO_DISABLE_SESSION_FILTER` | `'false'` | **PROD_WIRED** | DEMO TEST ONLY — bypasses London/NY session windows. Re-enable before live/prop. | `tradingbot/domain/filter_policy.py` |
| `VOL_REGIME_ENABLED` | `VOL_REGIME_ENABLED` | `'false'` | **PROD_WIRED** |  | `tradingbot/adapters/risk_gate.py`, `tradingbot/adapters/vol_regime_strategy_registry.py`, `tradingbot/application/live_runner.py`, `tradingbot/ml/integration/factory.py`, `tradingbot/ml/integration/startup_diagnostics.py` |
| `ADAPTIVE_CONFLUENCE_ONLY` | `ADAPTIVE_CONFLUENCE_ONLY` | `'true'` | **PROD_WIRED** | Confluence: VOL_REGIME + MTF must agree — fewer trades, higher quality. | `tradingbot/services/runtime_truth.py`, `tradingbot/strategies/adaptive_regime.py` |
| `ADAPTIVE_CONFLUENCE_MODE` | `ADAPTIVE_CONFLUENCE_MODE` | `'OR'` | **PROD_WIRED** | Phase 44B: OR = MTF or VOL sufficient; AND = both must agree (legacy). | `tradingbot/strategies/adaptive_regime.py` |
| `ADAPTIVE_QUALITY_ENGINE` | `ADAPTIVE_QUALITY_ENGINE` | `'false'` | **PROD_WIRED** | Phase 4A: quality scoring engine (backtest-only default — set true to opt-in live). | `tradingbot/strategies/adaptive_quality_engine.py` |
| `DISABLE_HIGH_VOL_FOR_MICRO` | `DISABLE_HIGH_VOL_FOR_MICRO` | `'true'` | **PROD_WIRED** | Phase 41D: block all HIGH_VOLATILITY signals on MICRO accounts (rollback via env=false). | `tradingbot/strategies/adaptive_regime.py` |
| `MULTI_ENGINE_ROUTER_ENABLED` | `MULTI_ENGINE_ROUTER_ENABLED` | `'true'` | **PROD_WIRED** | Phase 46C/47B: PA → VOL → Adaptive multi-engine router (PA-primary live default). | `tradingbot/application/live_runner.py`, `tradingbot/ml/integration/factory.py`, `tradingbot/ml/integration/startup_diagnostics.py`, `tradingbot/services/live_loop_health.py` |
| `META_LABEL_THRESHOLD` | `META_LABEL_THRESHOLD` | `'0.38'` | **PROD_WIRED** | Phase 47A calibrated M5 meta threshold (preset fallback when unset). | `tradingbot/adapters/risk_gate.py`, `tradingbot/backtest/risk.py`, `tradingbot/config/pa_symbol_tf_presets.py`, `tradingbot/services/phase6a_production_cert.py` |
| `META_OBSERVER_MODE` | `META_OBSERVER_MODE` | `'false'` | **PROD_WIRED** | Phase 20Y-3 observer path is wired. Default OFF: 30d observer book is unprofitable. | `tradingbot/adapters/risk_gate.py` |
| `VOL_DIRECTION_FILTER_ENABLED` | `VOL_DIRECTION_FILTER_ENABLED` | `'false'` | **DEFINED_ONLY** | Phase 48A: VOL as PA direction filter (not trade engine). 60d test → keep OFF. | — |
| `VOL_REGIME_SKIP_TQ` | `VOL_REGIME_SKIP_TQ` | `'true'` | **PROD_WIRED** | overstates XAUUSD spread vs live tick — skip TQ so signals reach RiskGate. | `tradingbot/adapters/vol_regime_strategy_registry.py`, `tradingbot/services/runtime_truth.py` |

Notable **DEFINED_ONLY** findings:

- `VOL_DIRECTION_FILTER_ENABLED` — only assigned in `live.py`; **no other code references** the key (dead flag; Phase 48A comment says keep OFF).
- `TRADINGBOT_REAL_SYMBOL` — read only inside `live.py` to build `SYMBOL_BY_ENVIRONMENT` (wired indirectly via that dict; no other getenv sites).
- `EMAIL_USERNAME` / `EMAIL_TO` / `EMAIL_FROM` — defined into config; no non-live consumers found via key scan (email path may be unused).

### 4.2 Other important env flags (outside live.py)

| Env key | Default | Where read | Role |
|---------|---------|------------|------|
| `TRADINGBOT_SIGNAL_FILTER` | `OFF` | `services/signal_filter_mode.py` | Enables WPSQF SignalFilterStage |
| `TRADINGBOT_WPSQF_THRESHOLD` | (unset → 77.56) | `services/signal_filter_mode.py` | WPSQF score threshold |
| `TRADINGBOT_PROP_PRESET` / `PROP_FIRM_PRESET` | empty | `config/prop_presets.py` | Prop firm overlays via `get_live_config()` |
| `TRADING_BOT_BASE_DIR` | unset | `config/engine_settings.py` | Base directory override |

Repo-wide getenv scan: **298** sites, **102** unique keys (see `tools/audit/out/getenv_inventory.json`).

### 4.3 Dead / unused config objects

| Object | Verdict | Evidence |
|--------|---------|----------|
| `TIMEFRAME_CONFIGS` / `get_timeframe_config()` | **UNUSED** in live & backtest paths | Only definitions in `live.py`; research string mention in `ml/research/phase22b/...` |
| `STRATEGY_CONFIGS` | Empty dict | `live.py` |
| `DEMO_MODE` config key | Printed in validate/print helpers; does **not** block `--execute` | Aligns with CX-005 in known unknowns |
| Hardcoded MT5 defaults in `engine_settings.py` | Security smell (credential-like defaults present in source) | Do not echo secrets; recommend removal in a later hardening phase |

## 5. Recommended next actions (NO EXECUTION)

Each item is a discrete human-approvable unit. **Do not execute in this phase.**

1. **Fix operator docs that contradict live TF/stage truth** — Edit `دستورات_اجرایی.md`, `docs/ONBOARDING_FA.md`, `docs/ARCHITECTURE_FA.md`, `docs/WHITEBOARD_FA.md`, and the stage-count line in `docs/CAPABILITIES.md` so they state: six pipeline stages (incl. SignalFilter pass-through) and M5-only kernel cycle when router default is on.
2. **Archive research Python bulk** — Move the 419 `RESEARCH_ARCHIVE_CANDIDATE` unreachable modules under e.g. `archive/research_py/` (or leave in place but exclude from default tooling). Prefer path-preserving git mv so history remains.
3. **Human-triage the 96 DEAD_CODE files** — Split into (a) keep as manual ops tools (e.g. `scripts/clear_emergency_stop.py`, diagnose helpers), (b) archive one-off `_patch*` / `_write_*` scripts, (c) delete only with explicit approval.
4. **Remove or quarantine dead config** — Delete or clearly `# UNUSED` mark `TIMEFRAME_CONFIGS` / `get_timeframe_config()` and `VOL_DIRECTION_FILTER_ENABLED` after confirming no dynamic getattr consumers.
5. **Credential hygiene** — Remove hardcoded MT5 credential defaults from `tradingbot/config/engine_settings.py` (replace with empty/required-env); rotate any credentials that ever lived in source; do not commit `.env`.
6. **Reduce TEST_ONLY surface carefully** — 894 modules are test-reachable only; many are intentional research harnesses covered by tests. Do not mass-delete; instead tag ownership (research vs production) in a manifest.
7. **Entry-point inventory expansion** — Add intentionally kept ops scripts to `دستورات_اجرایی.md` / `start/*.bat` so future reachability audits do not flag them as dead.
8. **Re-run this audit's pytest baseline after any cleanup phase** — Compare to `docs/AUDIT_1_BASELINE_TEST_RESULTS.md` before merging deletions.
9. **Optional: mark `docs/PHASE*.md` as historical** — Add a banner or move to `docs/archive/phases/` so operators default to `docs_v2/01_truth/*` + `docs_v2/03_runtime/*`.
10. **Collection / import path for `tests/test_accounting.py`** — Ensure package root is always on `sys.path` for isolated runs (full-suite collect from root succeeds).
11. **Investigate the 34 baseline failures before cleanup deletes** — Many are docs/epistemic or Phase 27 evidence-gate tests; treat as a separate fix lane, not as license to delete code.

## 6. Integrity confirmation

- This phase created/updated only: `docs/AUDIT_1_*.md`, `tools/audit/**`, and under `logs/_audit1_*` / `tools/audit/out/**` analysis outputs.
- This audit did not hand-edit production packages for cleanup. Pytest may have refreshed research JSON under `tradingbot/ml/research/phase24*` as a suite side-effect; pre-existing dirty files (e.g. phase115/116/117) were already present per git status at audit start.
- Phase 40 frozen tape was not touched.
- No MT5 connection, `.env` read, or order placement was performed for this audit.

**Totals:** inventory scanned **2079** `.py` files; flagged unreachable **515** (DEAD_CODE **96**, RESEARCH_ARCHIVE_CANDIDATE **419**); TEST_ONLY-via-tests **894**; markdown files listed **243**.


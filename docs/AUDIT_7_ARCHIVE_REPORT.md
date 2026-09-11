# AUDIT_7 — Research Archive Move Report (resumed)

**Phase:** PROJECT_AUDIT_7 (resumed after connection drop)
**Generated:** 2026-09-10
**Source list:** `tools/audit/out/unreachable_RESEARCH_ARCHIVE_CANDIDATE.json` (AUDIT_1, 419 files)

## 0. Step 0 — state at this resume

Assessed **before** any further moves on this resume:

| Check | Result |
|-------|--------|
| First resume (earlier session) | 266 moves were staged/uncommitted at first interrupt; later committed in 4 batches |
| `git log -5` (this resume) | HEAD `38655af` docs report; archive batches `4f0ba36`…`832ad76`; `main` **ahead 5** of `origin/main` |
| Working tree archive renames | **0** pending (`git status` shows no `archive/research` renames) |
| `archive/research/` file count | **267** (266 modules + README) |
| ALREADY_MOVED | **266** (src gone, archive present; matches `logs/_audit7_moves.json`) |
| NOT_YET_MOVED | **153** — all flagged `NO_LONGER_ARCHIVE_CANDIDATE` (**0** unflagged); left in place |
| INCONSISTENT | **0** (no dual-path / no missing-both) |
| `pytest --collect-only` | **6997** tests collected OK |
| Prior full suite junit | `logs/audit7_junit.xml` → 6997 / 6944 passed / 23 failed / 0 err / 30 skip |

**Conclusion:** Archival moves were **already complete and committed** before this resume. No additional `git mv` of candidates was required. Remaining work = suite reconfirm + report finalize.

## 1. Summary counts

| Metric | Count |
|--------|------:|
| AUDIT_1 RESEARCH_ARCHIVE_CANDIDATE | 419 |
| Missing on disk (skipped) | 0 |
| **Moved** (final) | 266 |
| Moved before interrupt (uncommitted → now committed) | 266 |
| Moved post-resume (new git mv) | **0** |
| **NO_LONGER_ARCHIVE_CANDIDATE** | 153 |
| Restored after suite (pre-interrupt) | 16 |
| DEAD_CODE overlap | 0 |
| Commit batches | 4 (`4f0ba36`, `00b5523`, `637aee8`, `832ad76`) |

### NO_LONGER_ARCHIVE_CANDIDATE — why

Re-verification (pre-interrupt) found test imports, active path refs, package cohesion/mixed-package constraints, and Path-based CLI existence checks.

<details><summary>Full NO_LONGER list (153)</summary>

- `scripts/phase12a_pa_dataset_builder.py` — active_path_ref:scripts/phase_verify_audit.py
- `scripts/phase12b_regime_training.py` — active_path_ref:scripts/phase_verify_audit.py
- `scripts/phase12c_hybrid_certification.py` — active_path_ref:tradingbot/strategies/adaptive_ml_hybrid.py,scripts/phase_verify_audit.py
- `scripts/phase21c_health_snapshot.py` — active_path_ref:scripts/symbol_100pct_audit_scan.py
- `scripts/phase24b_orb_forward_demo.py` — restored_after_suite:test_path_exists
- `scripts/run_phase13_6_optimizer.py` — active_path_ref:tradingbot/ml/research/router_optimizer/report_generator.py
- `scripts/run_phase15a_preparation.py` — restored_after_suite:test_path_exists
- `scripts/run_phase15b_kernel_validation.py` — restored_after_suite:test_path_exists
- `scripts/run_phase15c_monitoring.py` — restored_after_suite:test_path_exists
- `scripts/run_phase15g_confidence_analysis.py` — restored_after_suite:test_path_exists
- `scripts/run_phase15h_confidence_mapping.py` — restored_after_suite:test_path_exists
- `scripts/run_phase15i_range_recovery.py` — restored_after_suite:test_path_exists
- `scripts/run_phase15j_rootcause.py` — restored_after_suite:test_path_exists
- `scripts/run_phase15k_ceiling_analysis.py` — restored_after_suite:test_path_exists
- `scripts/run_phase16a_alignment.py` — restored_after_suite:test_path_exists
- `scripts/run_phase16b_kernel_validation.py` — restored_after_suite:test_path_exists
- `scripts/run_phase16c_trend_analysis.py` — restored_after_suite:test_path_exists
- `scripts/run_phase16d_feature_study.py` — restored_after_suite:test_path_exists
- `scripts/run_phase17a_blueprint.py` — restored_after_suite:test_path_exists
- `scripts/run_phase17b_retrain_lab.py` — restored_after_suite:test_path_exists
- `scripts/run_phase17c_shadow_bundle.py` — restored_after_suite:test_path_exists
- `scripts/verify_phase2_live_ready.py` — active_path_ref:scripts/morning_go_live_check.py,scripts/production_readiness_check.py,scripts/weekend_checklist.py
- `scripts/verify_phase4_live_ready.py` — active_path_ref:scripts/production_readiness_check.py,scripts/weekend_checklist.py
- `tradingbot/backtest/phase116_source_planning.py` — mixed_package_dir:tradingbot/backtest
- `tradingbot/backtest/phase116_source_research.py` — mixed_package_dir:tradingbot/backtest
- `tradingbot/backtest/phase1b_metrics.py` — mixed_package_dir:tradingbot/backtest
- `tradingbot/ml/phase19c/orchestrator.py` — mixed_package_dir:tradingbot/ml/phase19c
- `tradingbot/ml/research/documentation_freshness/run.py` — mixed_package_dir:tradingbot/ml/research/documentation_freshness
- `tradingbot/ml/research/documentation_operationalization/__init__.py` — test_import; test_imports_submodule:tradingbot.ml.research.documentation_operationalization.run
- `tradingbot/ml/research/documentation_verification/__init__.py` — active_path_ref:tradingbot/ml/research/documentation_verification/run.py; test_import; test_imports_submodule:tradingbot.ml.research.documentation_verification.run
- `tradingbot/ml/research/full_repo_audit/__init__.py` — test_import; test_imports_submodule:tradingbot.ml.research.full_repo_audit.run
- `tradingbot/ml/research/live_l2/edge_discovery_l26.py` — mixed_package_dir:tradingbot/ml/research/live_l2
- `tradingbot/ml/research/live_l2/edge_discovery_l27.py` — mixed_package_dir:tradingbot/ml/research/live_l2
- `tradingbot/ml/research/pa_live_audit/root_cause.py` — package_cohesion_with:tradingbot/ml/research/pa_live_audit/run.py
- `tradingbot/ml/research/pa_live_audit/run.py` — active_path_ref:tradingbot/ml/research/full_repo_audit/run.py
- `tradingbot/ml/research/phase14_10/stage1_yearly_statistics.py` — mixed_package_dir:tradingbot/ml/research/phase14_10
- `tradingbot/ml/research/phase14_10/stage2_drift_analysis.py` — mixed_package_dir:tradingbot/ml/research/phase14_10
- `tradingbot/ml/research/phase14_10/stage3_threshold_replay.py` — mixed_package_dir:tradingbot/ml/research/phase14_10
- `tradingbot/ml/research/phase14_10/stage4_adaptive_threshold_policy.py` — mixed_package_dir:tradingbot/ml/research/phase14_10
- `tradingbot/ml/research/phase14_10/stage5_final_report.py` — mixed_package_dir:tradingbot/ml/research/phase14_10
- `tradingbot/ml/research/phase17b/orchestrator.py` — mixed_package_dir:tradingbot/ml/research/phase17b
- `tradingbot/ml/research/phase22aa/__init__.py` — test_import; test_imports_submodule:tradingbot.ml.research.phase22aa.impact_forensics
- `tradingbot/ml/research/phase22aa/run_investigation.py` — package_cohesion_with:tradingbot/ml/research/phase22aa/__init__.py
- `tradingbot/ml/research/phase22ab/__init__.py` — test_import; test_imports_submodule:tradingbot.ml.research.phase22ab.freeze_forensics
- `tradingbot/ml/research/phase22ab/run_investigation.py` — package_cohesion_with:tradingbot/ml/research/phase22ab/__init__.py
- `tradingbot/ml/research/phase22ac/__init__.py` — test_import; test_imports_submodule:tradingbot.ml.research.phase22ac.registry_investigation
- `tradingbot/ml/research/phase22ac/run_investigation.py` — package_cohesion_with:tradingbot/ml/research/phase22ac/__init__.py
- `tradingbot/ml/research/phase22ad/run_investigation.py` — mixed_package_dir:tradingbot/ml/research/phase22ad
- `tradingbot/ml/research/phase22ae/__init__.py` — test_import; test_imports_submodule:tradingbot.ml.research.phase22ae.freeze_forensics
- `tradingbot/ml/research/phase22ae/run_investigation.py` — package_cohesion_with:tradingbot/ml/research/phase22ae/__init__.py
- `tradingbot/ml/research/phase22af/__init__.py` — test_import; test_imports_submodule:tradingbot.ml.research.phase22af.repair_design
- `tradingbot/ml/research/phase22af/run_investigation.py` — package_cohesion_with:tradingbot/ml/research/phase22af/__init__.py
- `tradingbot/ml/research/phase22ag/__init__.py` — test_import; test_imports_submodule:tradingbot.ml.research.phase22ag.acceptance_forensics
- `tradingbot/ml/research/phase22ag/run_investigation.py` — package_cohesion_with:tradingbot/ml/research/phase22ag/__init__.py
- `tradingbot/ml/research/phase22ah/__init__.py` — test_import; test_imports_submodule:tradingbot.ml.research.phase22ah.numeric_acceptance_validation
- `tradingbot/ml/research/phase22ah/run_investigation.py` — package_cohesion_with:tradingbot/ml/research/phase22ah/__init__.py
- `tradingbot/ml/research/phase22ai/__init__.py` — test_import; test_imports_submodule:tradingbot.ml.research.phase22ai.acceptance_regression
- `tradingbot/ml/research/phase22ai/run_investigation.py` — package_cohesion_with:tradingbot/ml/research/phase22ai/__init__.py
- `tradingbot/ml/research/phase22aj/__init__.py` — test_import; test_imports_submodule:tradingbot.ml.research.phase22aj.freeze_wiring_validation
- `tradingbot/ml/research/phase22aj/run_investigation.py` — package_cohesion_with:tradingbot/ml/research/phase22aj/__init__.py
- `tradingbot/ml/research/phase22aj0/__init__.py` — test_import; test_imports_submodule:tradingbot.ml.research.phase22aj0.winner_authority
- `tradingbot/ml/research/phase22aj0/run_investigation.py` — package_cohesion_with:tradingbot/ml/research/phase22aj0/__init__.py
- `tradingbot/ml/research/phase22ak/run_investigation.py` — mixed_package_dir:tradingbot/ml/research/phase22ak
- `tradingbot/ml/research/phase22al/__init__.py` — test_import; test_imports_submodule:tradingbot.ml.research.phase22al.live_validation
- `tradingbot/ml/research/phase22al/run_investigation.py` — package_cohesion_with:tradingbot/ml/research/phase22al/__init__.py
- `tradingbot/ml/research/phase22c/run_validation.py` — mixed_package_dir:tradingbot/ml/research/phase22c
- `tradingbot/ml/research/phase22e/delta.py` — mixed_package_dir:tradingbot/ml/research/phase22e
- `tradingbot/ml/research/phase22e/montecarlo.py` — mixed_package_dir:tradingbot/ml/research/phase22e
- `tradingbot/ml/research/phase22e/portfolio.py` — mixed_package_dir:tradingbot/ml/research/phase22e
- `tradingbot/ml/research/phase22e/run_validation.py` — mixed_package_dir:tradingbot/ml/research/phase22e
- `tradingbot/ml/research/phase22e/runner.py` — mixed_package_dir:tradingbot/ml/research/phase22e
- `tradingbot/ml/research/phase22e/stress.py` — mixed_package_dir:tradingbot/ml/research/phase22e
- `tradingbot/ml/research/phase22f/ablation.py` — mixed_package_dir:tradingbot/ml/research/phase22f
- `tradingbot/ml/research/phase22f/bottleneck.py` — mixed_package_dir:tradingbot/ml/research/phase22f
- `tradingbot/ml/research/phase22f/missed_ops.py` — mixed_package_dir:tradingbot/ml/research/phase22f
- `tradingbot/ml/research/phase22f/run_rapid_validation.py` — mixed_package_dir:tradingbot/ml/research/phase22f
- `tradingbot/ml/research/phase22f/trade_quality.py` — mixed_package_dir:tradingbot/ml/research/phase22f
- `tradingbot/ml/research/phase22i/hold_profiler.py` — mixed_package_dir:tradingbot/ml/research/phase22i
- `tradingbot/ml/research/phase22i/run_investigation.py` — mixed_package_dir:tradingbot/ml/research/phase22i
- `tradingbot/ml/research/phase22i/runner.py` — mixed_package_dir:tradingbot/ml/research/phase22i
- `tradingbot/ml/research/phase22i/stack.py` — mixed_package_dir:tradingbot/ml/research/phase22i
- `tradingbot/ml/research/phase22j/__init__.py` — test_import; test_imports_submodule:tradingbot.ml.research.phase22j.selection
- `tradingbot/ml/research/phase22j/range_forensics.py` — package_cohesion_with:tradingbot/ml/research/phase22j/__init__.py
- `tradingbot/ml/research/phase22j/run_investigation.py` — package_cohesion_with:tradingbot/ml/research/phase22j/__init__.py
- `tradingbot/ml/research/phase22j/runner.py` — package_cohesion_with:tradingbot/ml/research/phase22j/__init__.py
- `tradingbot/ml/research/phase22j/training_alignment.py` — package_cohesion_with:tradingbot/ml/research/phase22j/__init__.py
- `tradingbot/ml/research/phase22j/trend_forensics.py` — package_cohesion_with:tradingbot/ml/research/phase22j/__init__.py
- `tradingbot/ml/research/phase22t/run_investigation.py` — mixed_package_dir:tradingbot/ml/research/phase22t
- `tradingbot/ml/research/phase22u/__init__.py` — test_import; test_imports_submodule:tradingbot.ml.research.phase22u.model_audit
- `tradingbot/ml/research/phase22u/run_investigation.py` — package_cohesion_with:tradingbot/ml/research/phase22u/__init__.py
- `tradingbot/ml/research/phase22v/__init__.py` — package_cohesion_with:tradingbot/ml/research/phase22v/model_audit.py
- `tradingbot/ml/research/phase22v/model_audit.py` — active_path_ref:tradingbot/ml/research/phase22ae/freeze_forensics.py
- `tradingbot/ml/research/phase22v/run_investigation.py` — package_cohesion_with:tradingbot/ml/research/phase22v/model_audit.py
- `tradingbot/ml/research/phase22w/__init__.py` — test_import; test_imports_submodule:tradingbot.ml.research.phase22w.selection_audit
- `tradingbot/ml/research/phase22w/run_investigation.py` — package_cohesion_with:tradingbot/ml/research/phase22w/__init__.py
- `tradingbot/ml/research/phase22y/__init__.py` — test_import; test_imports_submodule:tradingbot.ml.research.phase22y.acceptance_forensics
- `tradingbot/ml/research/phase22y/run_investigation.py` — package_cohesion_with:tradingbot/ml/research/phase22y/__init__.py
- `tradingbot/ml/research/phase22z/run_investigation.py` — mixed_package_dir:tradingbot/ml/research/phase22z
- `tradingbot/ml/research/phase23a/__init__.py` — test_import; test_imports_submodule:tradingbot.ml.research.phase23a.pipeline_trace
- `tradingbot/ml/research/phase23a/run_investigation.py` — package_cohesion_with:tradingbot/ml/research/phase23a/__init__.py
- `tradingbot/ml/research/phase23b/__init__.py` — test_import; test_imports_submodule:tradingbot.ml.research.phase23b.repair_validation
- `tradingbot/ml/research/phase23b/run_investigation.py` — package_cohesion_with:tradingbot/ml/research/phase23b/__init__.py
- `tradingbot/ml/research/phase23g/__init__.py` — test_import; test_imports_submodule:tradingbot.ml.research.phase23g.integration_validation
- `tradingbot/ml/research/phase23g/run_validation.py` — package_cohesion_with:tradingbot/ml/research/phase23g/__init__.py
- `tradingbot/ml/research/phase24e/__init__.py` — test_import; test_imports_submodule:tradingbot.ml.research.phase24e.run_validation
- `tradingbot/ml/research/phase24g/__init__.py` — test_import; test_imports_submodule:tradingbot.ml.research.phase24g.run_validation
- `tradingbot/ml/research/phase24i/__init__.py` — test_import; test_imports_submodule:tradingbot.ml.research.phase24i.run_validation
- `tradingbot/ml/research/phase25b/pipeline_depth.py` — mixed_package_dir:tradingbot/ml/research/phase25b
- `tradingbot/ml/research/phase25b/run_investigation.py` — mixed_package_dir:tradingbot/ml/research/phase25b
- `tradingbot/ml/research/phase27a/run_investigation.py` — mixed_package_dir:tradingbot/ml/research/phase27a
- `tradingbot/ml/research/phase27a/trade_builder.py` — mixed_package_dir:tradingbot/ml/research/phase27a
- `tradingbot/ml/research/phase27l/metrics.py` — mixed_package_dir:tradingbot/ml/research/phase27l
- `tradingbot/ml/research/phase27l/run_investigation.py` — mixed_package_dir:tradingbot/ml/research/phase27l
- `tradingbot/ml/research/phase27n/metrics.py` — mixed_package_dir:tradingbot/ml/research/phase27n
- `tradingbot/ml/research/phase27n/run_investigation.py` — mixed_package_dir:tradingbot/ml/research/phase27n
- `tradingbot/ml/research/phase27n/window_runner.py` — mixed_package_dir:tradingbot/ml/research/phase27n
- `tradingbot/ml/research/phase28c/__init__.py` — test_import; test_imports_submodule:tradingbot.ml.research.phase28c.metrics
- `tradingbot/ml/research/phase28c/data_collector.py` — package_cohesion_with:tradingbot/ml/research/phase28c/__init__.py
- `tradingbot/ml/research/phase28c/run_investigation.py` — package_cohesion_with:tradingbot/ml/research/phase28c/__init__.py
- `tradingbot/ml/research/phase28c/validators.py` — package_cohesion_with:tradingbot/ml/research/phase28c/__init__.py
- `tradingbot/ml/research/phase28d/cache.py` — mixed_package_dir:tradingbot/ml/research/phase28d
- `tradingbot/ml/research/phase28d/metrics.py` — mixed_package_dir:tradingbot/ml/research/phase28d
- `tradingbot/ml/research/phase28d/run_investigation.py` — mixed_package_dir:tradingbot/ml/research/phase28d
- `tradingbot/ml/research/phase29b/__init__.py` — test_import; test_imports_submodule:tradingbot.ml.research.phase29b.run_investigation
- `tradingbot/ml/research/phase30a/replay_simulation.py` — mixed_package_dir:tradingbot/ml/research/phase30a
- `tradingbot/ml/research/phase30d/__init__.py` — test_import; test_imports_submodule:tradingbot.ml.research.phase30d.run_investigation
- `tradingbot/ml/research/phase30e/__init__.py` — test_import; test_imports_submodule:tradingbot.ml.research.phase30e.run_investigation
- `tradingbot/ml/research/phase31e/__init__.py` — test_import; test_imports_submodule:tradingbot.ml.research.phase31e.run_investigation
- `tradingbot/ml/research/phase32g/__init__.py` — test_import; test_imports_submodule:tradingbot.ml.research.phase32g.run_validation
- `tradingbot/ml/research/phase33d/replay.py` — mixed_package_dir:tradingbot/ml/research/phase33d
- `tradingbot/ml/research/phase33d/run_forensic.py` — mixed_package_dir:tradingbot/ml/research/phase33d
- `tradingbot/ml/research/phase34a/run_all.py` — mixed_package_dir:tradingbot/ml/research/phase34a
- `tradingbot/ml/research/phase34a/run_audit.py` — mixed_package_dir:tradingbot/ml/research/phase34a
- `tradingbot/ml/research/phase34c/__init__.py` — test_import; test_imports_submodule:tradingbot.ml.research.phase34c.run_filter_audit
- `tradingbot/ml/research/phase35/run_label_alignment.py` — mixed_package_dir:tradingbot/ml/research/phase35
- `tradingbot/ml/research/phase36/retrain_validation.py` — mixed_package_dir:tradingbot/ml/research/phase36
- `tradingbot/ml/research/phase36/run_phase36.py` — mixed_package_dir:tradingbot/ml/research/phase36
- `tradingbot/ml/research/phase41/run_phase41.py` — active_path_ref:tradingbot/backtest/phase41_final_evidence_closure.py
- `tradingbot/ml/research/phase42/run_phase42.py` — active_path_ref:tradingbot/backtest/phase42_broker_cost_execution_closure.py
- `tradingbot/ml/research/run_engineering_pipeline.py` — mixed_package_dir:tradingbot/ml/research
- `tradingbot/ml/research/run_fix_pipeline.py` — mixed_package_dir:tradingbot/ml/research
- `tradingbot/ml/research/run_live_pipeline.py` — mixed_package_dir:tradingbot/ml/research
- `tradingbot/ml/research/run_treatment_pipeline.py` — mixed_package_dir:tradingbot/ml/research
- `tradingbot/ml/research/v41_isolated/cost_inventory.py` — package_cohesion_with:tradingbot/ml/research/v41_isolated/run.py
- `tradingbot/ml/research/v41_isolated/run.py` — active_path_ref:tradingbot/ml/research/full_repo_audit/run.py
- `tradingbot/ml/research/v41_isolated/run_cost.py` — package_cohesion_with:tradingbot/ml/research/v41_isolated/run.py
- `tradingbot/ml/research/v41_isolated/run_followup.py` — package_cohesion_with:tradingbot/ml/research/v41_isolated/run.py
- `tradingbot/ml/shadow/phase53a_gate.py` — mixed_package_dir:tradingbot/ml/shadow
- `tradingbot/ml/shadow/phase53a_metrics.py` — mixed_package_dir:tradingbot/ml/shadow
- `tradingbot/ml/shadow/phase5a_drift.py` — mixed_package_dir:tradingbot/ml/shadow
- `tradingbot/ml/shadow/phase5a_metrics.py` — mixed_package_dir:tradingbot/ml/shadow
- `tradingbot/ml/shadow/phase5a_shadow_replay.py` — mixed_package_dir:tradingbot/ml/shadow
- `tradingbot/services/phase6a_production_cert.py` — mixed_package_dir:tradingbot/services

</details>

### Restored after suite (must stay in tree)

- `scripts/phase24b_orb_forward_demo.py` — tests assert script path exists / read script text
- `scripts/run_phase15a_preparation.py` — tests assert script path exists / read script text
- `scripts/run_phase15b_kernel_validation.py` — tests assert script path exists / read script text
- `scripts/run_phase15c_monitoring.py` — tests assert script path exists / read script text
- `scripts/run_phase15g_confidence_analysis.py` — tests assert script path exists / read script text
- `scripts/run_phase15h_confidence_mapping.py` — tests assert script path exists / read script text
- `scripts/run_phase15i_range_recovery.py` — tests assert script path exists / read script text
- `scripts/run_phase15j_rootcause.py` — tests assert script path exists / read script text
- `scripts/run_phase15k_ceiling_analysis.py` — tests assert script path exists / read script text
- `scripts/run_phase16a_alignment.py` — tests assert script path exists / read script text
- `scripts/run_phase16b_kernel_validation.py` — tests assert script path exists / read script text
- `scripts/run_phase16c_trend_analysis.py` — tests assert script path exists / read script text
- `scripts/run_phase16d_feature_study.py` — tests assert script path exists / read script text
- `scripts/run_phase17a_blueprint.py` — tests assert script path exists / read script text
- `scripts/run_phase17b_retrain_lab.py` — tests assert script path exists / read script text
- `scripts/run_phase17c_shadow_bundle.py` — tests assert script path exists / read script text

## 2. Full move list (old → new)

All 266 moves were performed **before** the interrupt (uncommitted). Resume **rewrote** 4 unpushed commits so each batch is proper `git mv` renames (100% similarity):

| Batch commit | Files |
|--------------|------:|
| `4f0ba36` batch 1/4 | 70 + README |
| `00b5523` batch 2/4 | 70 |
| `637aee8` batch 3/4 | 70 |
| `832ad76` batch 4/4 | 56 |

_Pre-interrupt → post-resume:_ same paths; no new archive candidates moved.

- `_phase33c_forensic.py` → `archive/research/_phase33c_forensic.py` *(pre-interrupt)*
- `scripts/_write_phase23a.py` → `archive/research/scripts/_write_phase23a.py` *(pre-interrupt)*
- `scripts/phase13a_cleanup_audit.py` → `archive/research/scripts/phase13a_cleanup_audit.py` *(pre-interrupt)*
- `scripts/phase13b_no_trade_recovery.py` → `archive/research/scripts/phase13b_no_trade_recovery.py` *(pre-interrupt)*
- `scripts/phase13c_adaptive_hybrid_v2.py` → `archive/research/scripts/phase13c_adaptive_hybrid_v2.py` *(pre-interrupt)*
- `scripts/phase13d_ml_retraining.py` → `archive/research/scripts/phase13d_ml_retraining.py` *(pre-interrupt)*
- `scripts/phase14a2_pa_no_signal_audit.py` → `archive/research/scripts/phase14a2_pa_no_signal_audit.py` *(pre-interrupt)*
- `scripts/phase14b2_pa_hold_replay.py` → `archive/research/scripts/phase14b2_pa_hold_replay.py` *(pre-interrupt)*
- `scripts/phase14b2_pa_hold_replay_fast.py` → `archive/research/scripts/phase14b2_pa_hold_replay_fast.py` *(pre-interrupt)*
- `scripts/phase14b3_readiness_report.py` → `archive/research/scripts/phase14b3_readiness_report.py` *(pre-interrupt)*
- `scripts/phase14c1_ny_window_recovery.py` → `archive/research/scripts/phase14c1_ny_window_recovery.py` *(pre-interrupt)*
- `scripts/phase14c1_session_window_recovery.py` → `archive/research/scripts/phase14c1_session_window_recovery.py` *(pre-interrupt)*
- `scripts/phase14c2_reclaim_softening.py` → `archive/research/scripts/phase14c2_reclaim_softening.py` *(pre-interrupt)*
- `scripts/phase14c3_bos_sensitivity.py` → `archive/research/scripts/phase14c3_bos_sensitivity.py` *(pre-interrupt)*
- `scripts/phase16a_displacement_intelligence.py` → `archive/research/scripts/phase16a_displacement_intelligence.py` *(pre-interrupt)*
- `scripts/phase16b_ob_fvg_confluence.py` → `archive/research/scripts/phase16b_ob_fvg_confluence.py` *(pre-interrupt)*
- `scripts/phase16c_regime_ensemble.py` → `archive/research/scripts/phase16c_regime_ensemble.py` *(pre-interrupt)*
- `scripts/phase17a_pa_session_heatmap.py` → `archive/research/scripts/phase17a_pa_session_heatmap.py` *(pre-interrupt)*
- `scripts/phase17b_bos_reclaim_truth.py` → `archive/research/scripts/phase17b_bos_reclaim_truth.py` *(pre-interrupt)*
- `scripts/phase18a_dataset_expansion.py` → `archive/research/scripts/phase18a_dataset_expansion.py` *(pre-interrupt)*
- `scripts/phase18b_meta_retraining.py` → `archive/research/scripts/phase18b_meta_retraining.py` *(pre-interrupt)*
- `scripts/phase19a_reclaim_intelligence.py` → `archive/research/scripts/phase19a_reclaim_intelligence.py` *(pre-interrupt)*
- `scripts/phase19b_label_quality.py` → `archive/research/scripts/phase19b_label_quality.py` *(pre-interrupt)*
- `scripts/phase19c_shadow_meta.py` → `archive/research/scripts/phase19c_shadow_meta.py` *(pre-interrupt)*
- `scripts/phase20a_bos_live_parity.py` → `archive/research/scripts/phase20a_bos_live_parity.py` *(pre-interrupt)*
- `scripts/phase20b_meta_shadow_demotion.py` → `archive/research/scripts/phase20b_meta_shadow_demotion.py` *(pre-interrupt)*
- `scripts/phase20c_mss_fvg_tests.py` → `archive/research/scripts/phase20c_mss_fvg_tests.py` *(pre-interrupt)*
- `scripts/phase20y2_choch_bridge.py` → `archive/research/scripts/phase20y2_choch_bridge.py` *(pre-interrupt)*
- `scripts/phase20y3_meta_observer.py` → `archive/research/scripts/phase20y3_meta_observer.py` *(pre-interrupt)*
- `scripts/phase21a_setup_formation_lab.py` → `archive/research/scripts/phase21a_setup_formation_lab.py` *(pre-interrupt)*
- `scripts/phase21b_hour15_realign.py` → `archive/research/scripts/phase21b_hour15_realign.py` *(pre-interrupt)*
- `scripts/phase21d_meta_false_negative_audit.py` → `archive/research/scripts/phase21d_meta_false_negative_audit.py` *(pre-interrupt)*
- `scripts/phase22a_strategy_discovery.py` → `archive/research/scripts/phase22a_strategy_discovery.py` *(pre-interrupt)*
- `scripts/phase22b_strategy_certification.py` → `archive/research/scripts/phase22b_strategy_certification.py` *(pre-interrupt)*
- `scripts/phase22c_meta_v2.py` → `archive/research/scripts/phase22c_meta_v2.py` *(pre-interrupt)*
- `scripts/phase22d_portfolio_router.py` → `archive/research/scripts/phase22d_portfolio_router.py` *(pre-interrupt)*
- `scripts/phase22e_forward_demo.py` → `archive/research/scripts/phase22e_forward_demo.py` *(pre-interrupt)*
- `scripts/phase23a_multi_strategy_discovery.py` → `archive/research/scripts/phase23a_multi_strategy_discovery.py` *(pre-interrupt)*
- `scripts/phase23b_strategy_certification.py` → `archive/research/scripts/phase23b_strategy_certification.py` *(pre-interrupt)*
- `scripts/phase23c_portfolio_router.py` → `archive/research/scripts/phase23c_portfolio_router.py` *(pre-interrupt)*
- `scripts/phase24a_specialized_certification.py` → `archive/research/scripts/phase24a_specialized_certification.py` *(pre-interrupt)*
- `scripts/run_phase11_5_analysis.py` → `archive/research/scripts/run_phase11_5_analysis.py` *(pre-interrupt)*
- `scripts/run_phase12_1_audit.py` → `archive/research/scripts/run_phase12_1_audit.py` *(pre-interrupt)*
- `scripts/run_phase12_health_check.py` → `archive/research/scripts/run_phase12_health_check.py` *(pre-interrupt)*
- `scripts/run_phase12_live_pilot.py` → `archive/research/scripts/run_phase12_live_pilot.py` *(pre-interrupt)*
- `scripts/run_phase13_10_router_final.py` → `archive/research/scripts/run_phase13_10_router_final.py` *(pre-interrupt)*
- `scripts/run_phase13_2_regime.py` → `archive/research/scripts/run_phase13_2_regime.py` *(pre-interrupt)*
- `scripts/run_phase13_3_trend.py` → `archive/research/scripts/run_phase13_3_trend.py` *(pre-interrupt)*
- `scripts/run_phase13_4_trend_ml.py` → `archive/research/scripts/run_phase13_4_trend_ml.py` *(pre-interrupt)*
- `scripts/run_phase13_5_router.py` → `archive/research/scripts/run_phase13_5_router.py` *(pre-interrupt)*
- `scripts/run_phase13_7_stability.py` → `archive/research/scripts/run_phase13_7_stability.py` *(pre-interrupt)*
- `scripts/run_phase13_8_trend_recovery.py` → `archive/research/scripts/run_phase13_8_trend_recovery.py` *(pre-interrupt)*
- `scripts/run_phase13_9_unified_router.py` → `archive/research/scripts/run_phase13_9_unified_router.py` *(pre-interrupt)*
- `scripts/run_phase14_10_stability.py` → `archive/research/scripts/run_phase14_10_stability.py` *(pre-interrupt)*
- `scripts/run_phase14_10_stage1_yearly.py` → `archive/research/scripts/run_phase14_10_stage1_yearly.py` *(pre-interrupt)*
- `scripts/run_phase14_10_stage2_drift.py` → `archive/research/scripts/run_phase14_10_stage2_drift.py` *(pre-interrupt)*
- `scripts/run_phase14_10_stage3_threshold.py` → `archive/research/scripts/run_phase14_10_stage3_threshold.py` *(pre-interrupt)*
- `scripts/run_phase14_10_stage4_policy.py` → `archive/research/scripts/run_phase14_10_stage4_policy.py` *(pre-interrupt)*
- `scripts/run_phase14_10_stage5_report.py` → `archive/research/scripts/run_phase14_10_stage5_report.py` *(pre-interrupt)*
- `scripts/run_phase14_1_decision_test.py` → `archive/research/scripts/run_phase14_1_decision_test.py` *(pre-interrupt)*
- `scripts/run_phase14_2a_calibration.py` → `archive/research/scripts/run_phase14_2a_calibration.py` *(pre-interrupt)*
- `scripts/run_phase14_2b_risk.py` → `archive/research/scripts/run_phase14_2b_risk.py` *(pre-interrupt)*
- `scripts/run_phase14_3_quality.py` → `archive/research/scripts/run_phase14_3_quality.py` *(pre-interrupt)*
- `scripts/run_phase14_4_optimizer.py` → `archive/research/scripts/run_phase14_4_optimizer.py` *(pre-interrupt)*
- `scripts/run_phase14_5_confidence_optimizer.py` → `archive/research/scripts/run_phase14_5_confidence_optimizer.py` *(pre-interrupt)*
- `scripts/run_phase14_6_calibration_recovery.py` → `archive/research/scripts/run_phase14_6_calibration_recovery.py` *(pre-interrupt)*
- `scripts/run_phase14_7_pipeline_validation.py` → `archive/research/scripts/run_phase14_7_pipeline_validation.py` *(pre-interrupt)*
- `scripts/run_phase14_8_stress_validation.py` → `archive/research/scripts/run_phase14_8_stress_validation.py` *(pre-interrupt)*
- `scripts/run_phase14_9_stability.py` → `archive/research/scripts/run_phase14_9_stability.py` *(pre-interrupt)*
- `scripts/run_phase15d_shadow.py` → `archive/research/scripts/run_phase15d_shadow.py` *(pre-interrupt)*
- `scripts/run_phase15e_shadow_debug.py` → `archive/research/scripts/run_phase15e_shadow_debug.py` *(pre-interrupt)*
- `scripts/run_phase15f_confidence_recovery.py` → `archive/research/scripts/run_phase15f_confidence_recovery.py` *(pre-interrupt)*
- `scripts/run_phase18a_shadow_validation.py` → `archive/research/scripts/run_phase18a_shadow_validation.py` *(pre-interrupt)*
- `scripts/run_phase18b_go_live.py` → `archive/research/scripts/run_phase18b_go_live.py` *(pre-interrupt)*
- `scripts/run_phase18c_prelive.py` → `archive/research/scripts/run_phase18c_prelive.py` *(pre-interrupt)*
- `scripts/run_phase19a_profitability_audit.py` → `archive/research/scripts/run_phase19a_profitability_audit.py` *(pre-interrupt)*
- `scripts/run_phase19b_profitability_optimization.py` → `archive/research/scripts/run_phase19b_profitability_optimization.py` *(pre-interrupt)*
- `scripts/run_phase19c_profitability_upgrade.py` → `archive/research/scripts/run_phase19c_profitability_upgrade.py` *(pre-interrupt)*
- `scripts/run_phase19d_certification.py` → `archive/research/scripts/run_phase19d_certification.py` *(pre-interrupt)*
- `scripts/run_phase20a_live_deployment.py` → `archive/research/scripts/run_phase20a_live_deployment.py` *(pre-interrupt)*
- `scripts/run_phase20b_stabilization.py` → `archive/research/scripts/run_phase20b_stabilization.py` *(pre-interrupt)*
- `scripts/run_phase20c_broker_validation.py` → `archive/research/scripts/run_phase20c_broker_validation.py` *(pre-interrupt)*
- `tradingbot/ml/research/live_bt/__init__.py` → `archive/research/tradingbot/ml/research/live_bt/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/live_bt/backtest_gate.py` → `archive/research/tradingbot/ml/research/live_bt/backtest_gate.py` *(pre-interrupt)*
- `tradingbot/ml/research/live_bt/rr_production_research.py` → `archive/research/tradingbot/ml/research/live_bt/rr_production_research.py` *(pre-interrupt)*
- `tradingbot/ml/research/live_l1/__init__.py` → `archive/research/tradingbot/ml/research/live_l1/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/live_l1/build_v8_dataset.py` → `archive/research/tradingbot/ml/research/live_l1/build_v8_dataset.py` *(pre-interrupt)*
- `tradingbot/ml/research/live_l1/expand_v8_labels.py` → `archive/research/tradingbot/ml/research/live_l1/expand_v8_labels.py` *(pre-interrupt)*
- `tradingbot/ml/research/live_l4/__init__.py` → `archive/research/tradingbot/ml/research/live_l4/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/live_l4/signal_ml_refinement.py` → `archive/research/tradingbot/ml/research/live_l4/signal_ml_refinement.py` *(pre-interrupt)*
- `tradingbot/ml/research/live_l4/v8_regime_ml_test.py` → `archive/research/tradingbot/ml/research/live_l4/v8_regime_ml_test.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase13c/__init__.py` → `archive/research/tradingbot/ml/research/phase13c/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase13c/adaptive_quality_v2.py` → `archive/research/tradingbot/ml/research/phase13c/adaptive_quality_v2.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase1b/__init__.py` → `archive/research/tradingbot/ml/research/phase1b/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase1b/pa_full_cert.py` → `archive/research/tradingbot/ml/research/phase1b/pa_full_cert.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase22b/run_capability_audit.py` → `archive/research/tradingbot/ml/research/phase22b/run_capability_audit.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase22d/__init__.py` → `archive/research/tradingbot/ml/research/phase22d/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase22d/run_forensics.py` → `archive/research/tradingbot/ml/research/phase22d/run_forensics.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase22g/__init__.py` → `archive/research/tradingbot/ml/research/phase22g/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase22g/bottleneck.py` → `archive/research/tradingbot/ml/research/phase22g/bottleneck.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase22g/decision_engine_doc.py` → `archive/research/tradingbot/ml/research/phase22g/decision_engine_doc.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase22g/execution_graph.py` → `archive/research/tradingbot/ml/research/phase22g/execution_graph.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase22g/execution_tracer.py` → `archive/research/tradingbot/ml/research/phase22g/execution_tracer.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase22g/model_inventory.py` → `archive/research/tradingbot/ml/research/phase22g/model_inventory.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase22g/model_routing.py` → `archive/research/tradingbot/ml/research/phase22g/model_routing.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase22g/rapid_runner.py` → `archive/research/tradingbot/ml/research/phase22g/rapid_runner.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase22g/recommended_fix.py` → `archive/research/tradingbot/ml/research/phase22g/recommended_fix.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase22g/report_verification.py` → `archive/research/tradingbot/ml/research/phase22g/report_verification.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase22g/run_investigation.py` → `archive/research/tradingbot/ml/research/phase22g/run_investigation.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase22h/__init__.py` → `archive/research/tradingbot/ml/research/phase22h/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase22h/alignment.py` → `archive/research/tradingbot/ml/research/phase22h/alignment.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase22h/delta.py` → `archive/research/tradingbot/ml/research/phase22h/delta.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase22h/run_validation.py` → `archive/research/tradingbot/ml/research/phase22h/run_validation.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase22l/__init__.py` → `archive/research/tradingbot/ml/research/phase22l/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase22l/audit_pipeline.py` → `archive/research/tradingbot/ml/research/phase22l/audit_pipeline.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase22l/comparison.py` → `archive/research/tradingbot/ml/research/phase22l/comparison.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase22l/coverage.py` → `archive/research/tradingbot/ml/research/phase22l/coverage.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase22l/range_quality.py` → `archive/research/tradingbot/ml/research/phase22l/range_quality.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase22l/rebuild.py` → `archive/research/tradingbot/ml/research/phase22l/rebuild.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase22l/run_investigation.py` → `archive/research/tradingbot/ml/research/phase22l/run_investigation.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase22l/unified_audit.py` → `archive/research/tradingbot/ml/research/phase22l/unified_audit.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase22m/run_investigation.py` → `archive/research/tradingbot/ml/research/phase22m/run_investigation.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase22n/run_investigation.py` → `archive/research/tradingbot/ml/research/phase22n/run_investigation.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase22o/run_investigation.py` → `archive/research/tradingbot/ml/research/phase22o/run_investigation.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase22p/run_investigation.py` → `archive/research/tradingbot/ml/research/phase22p/run_investigation.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase22q/run_investigation.py` → `archive/research/tradingbot/ml/research/phase22q/run_investigation.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase22r/run_investigation.py` → `archive/research/tradingbot/ml/research/phase22r/run_investigation.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase22s/run_investigation.py` → `archive/research/tradingbot/ml/research/phase22s/run_investigation.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase22x/__init__.py` → `archive/research/tradingbot/ml/research/phase22x/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase22x/run_investigation.py` → `archive/research/tradingbot/ml/research/phase22x/run_investigation.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase24j/run_investigation.py` → `archive/research/tradingbot/ml/research/phase24j/run_investigation.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase24k/run_validation.py` → `archive/research/tradingbot/ml/research/phase24k/run_validation.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase25a/run_investigation.py` → `archive/research/tradingbot/ml/research/phase25a/run_investigation.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase26a/__init__.py` → `archive/research/tradingbot/ml/research/phase26a/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase26a/exit_simulator.py` → `archive/research/tradingbot/ml/research/phase26a/exit_simulator.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase26a/journal_reader.py` → `archive/research/tradingbot/ml/research/phase26a/journal_reader.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase26a/run_investigation.py` → `archive/research/tradingbot/ml/research/phase26a/run_investigation.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase26a/statistics.py` → `archive/research/tradingbot/ml/research/phase26a/statistics.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase26a/trade_collector.py` → `archive/research/tradingbot/ml/research/phase26a/trade_collector.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase26a/trade_schema.py` → `archive/research/tradingbot/ml/research/phase26a/trade_schema.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase26a/validation.py` → `archive/research/tradingbot/ml/research/phase26a/validation.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase26c/__init__.py` → `archive/research/tradingbot/ml/research/phase26c/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase26c/run_investigation.py` → `archive/research/tradingbot/ml/research/phase26c/run_investigation.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase26d/__init__.py` → `archive/research/tradingbot/ml/research/phase26d/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase26d/run_investigation.py` → `archive/research/tradingbot/ml/research/phase26d/run_investigation.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27b/__init__.py` → `archive/research/tradingbot/ml/research/phase27b/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27b/bar_tracer.py` → `archive/research/tradingbot/ml/research/phase27b/bar_tracer.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27b/metrics.py` → `archive/research/tradingbot/ml/research/phase27b/metrics.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27b/run_investigation.py` → `archive/research/tradingbot/ml/research/phase27b/run_investigation.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27c/run_investigation.py` → `archive/research/tradingbot/ml/research/phase27c/run_investigation.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27d/__init__.py` → `archive/research/tradingbot/ml/research/phase27d/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27d/metrics.py` → `archive/research/tradingbot/ml/research/phase27d/metrics.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27d/run_investigation.py` → `archive/research/tradingbot/ml/research/phase27d/run_investigation.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27e/__init__.py` → `archive/research/tradingbot/ml/research/phase27e/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27e/metrics.py` → `archive/research/tradingbot/ml/research/phase27e/metrics.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27e/run_investigation.py` → `archive/research/tradingbot/ml/research/phase27e/run_investigation.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27f/__init__.py` → `archive/research/tradingbot/ml/research/phase27f/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27f/metrics.py` → `archive/research/tradingbot/ml/research/phase27f/metrics.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27f/run_investigation.py` → `archive/research/tradingbot/ml/research/phase27f/run_investigation.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27g/__init__.py` → `archive/research/tradingbot/ml/research/phase27g/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27g/metrics.py` → `archive/research/tradingbot/ml/research/phase27g/metrics.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27g/run_investigation.py` → `archive/research/tradingbot/ml/research/phase27g/run_investigation.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27h/__init__.py` → `archive/research/tradingbot/ml/research/phase27h/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27h/metrics.py` → `archive/research/tradingbot/ml/research/phase27h/metrics.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27h/run_investigation.py` → `archive/research/tradingbot/ml/research/phase27h/run_investigation.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27h/stress_engine.py` → `archive/research/tradingbot/ml/research/phase27h/stress_engine.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27i/__init__.py` → `archive/research/tradingbot/ml/research/phase27i/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27i/metrics.py` → `archive/research/tradingbot/ml/research/phase27i/metrics.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27i/run_investigation.py` → `archive/research/tradingbot/ml/research/phase27i/run_investigation.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27i/slippage_decompose.py` → `archive/research/tradingbot/ml/research/phase27i/slippage_decompose.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27j/__init__.py` → `archive/research/tradingbot/ml/research/phase27j/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27j/edge_decompose.py` → `archive/research/tradingbot/ml/research/phase27j/edge_decompose.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27j/metrics.py` → `archive/research/tradingbot/ml/research/phase27j/metrics.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27j/run_investigation.py` → `archive/research/tradingbot/ml/research/phase27j/run_investigation.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27k/__init__.py` → `archive/research/tradingbot/ml/research/phase27k/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27k/loser_enrich.py` → `archive/research/tradingbot/ml/research/phase27k/loser_enrich.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27k/metrics.py` → `archive/research/tradingbot/ml/research/phase27k/metrics.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27k/run_investigation.py` → `archive/research/tradingbot/ml/research/phase27k/run_investigation.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27m/__init__.py` → `archive/research/tradingbot/ml/research/phase27m/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27m/metrics.py` → `archive/research/tradingbot/ml/research/phase27m/metrics.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27m/run_investigation.py` → `archive/research/tradingbot/ml/research/phase27m/run_investigation.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27m/window_runner.py` → `archive/research/tradingbot/ml/research/phase27m/window_runner.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27o/__init__.py` → `archive/research/tradingbot/ml/research/phase27o/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27o/metrics.py` → `archive/research/tradingbot/ml/research/phase27o/metrics.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27o/run_investigation.py` → `archive/research/tradingbot/ml/research/phase27o/run_investigation.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27o/split.py` → `archive/research/tradingbot/ml/research/phase27o/split.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase27o/window_runner.py` → `archive/research/tradingbot/ml/research/phase27o/window_runner.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase28a/__init__.py` → `archive/research/tradingbot/ml/research/phase28a/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase28a/metrics.py` → `archive/research/tradingbot/ml/research/phase28a/metrics.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase28a/run_investigation.py` → `archive/research/tradingbot/ml/research/phase28a/run_investigation.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase28a/window_runner.py` → `archive/research/tradingbot/ml/research/phase28a/window_runner.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase28b/__init__.py` → `archive/research/tradingbot/ml/research/phase28b/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase28b/run_investigation.py` → `archive/research/tradingbot/ml/research/phase28b/run_investigation.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase30b/__init__.py` → `archive/research/tradingbot/ml/research/phase30b/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase30b/run_investigation.py` → `archive/research/tradingbot/ml/research/phase30b/run_investigation.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase30c/__init__.py` → `archive/research/tradingbot/ml/research/phase30c/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase30c/run_investigation.py` → `archive/research/tradingbot/ml/research/phase30c/run_investigation.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase32h/generate_deliverables.py` → `archive/research/tradingbot/ml/research/phase32h/generate_deliverables.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase32i/generate_deliverables.py` → `archive/research/tradingbot/ml/research/phase32i/generate_deliverables.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase33c/run_forensics.py` → `archive/research/tradingbot/ml/research/phase33c/run_forensics.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase34b/__init__.py` → `archive/research/tradingbot/ml/research/phase34b/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase34b/run_label_audit.py` → `archive/research/tradingbot/ml/research/phase34b/run_label_audit.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase34d/run_engineering_report.py` → `archive/research/tradingbot/ml/research/phase34d/run_engineering_report.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase37/__init__.py` → `archive/research/tradingbot/ml/research/phase37/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase37/run_phase37.py` → `archive/research/tradingbot/ml/research/phase37/run_phase37.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase38/run_phase38.py` → `archive/research/tradingbot/ml/research/phase38/run_phase38.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase39/run_phase39.py` → `archive/research/tradingbot/ml/research/phase39/run_phase39.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase3a/__init__.py` → `archive/research/tradingbot/ml/research/phase3a/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase3a/vol_edge_research.py` → `archive/research/tradingbot/ml/research/phase3a/vol_edge_research.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase40/run_phase40.py` → `archive/research/tradingbot/ml/research/phase40/run_phase40.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase43/run_phase43.py` → `archive/research/tradingbot/ml/research/phase43/run_phase43.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase44/run_phase44.py` → `archive/research/tradingbot/ml/research/phase44/run_phase44.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase45/run_phase45.py` → `archive/research/tradingbot/ml/research/phase45/run_phase45.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase46/run_phase46.py` → `archive/research/tradingbot/ml/research/phase46/run_phase46.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase47/run_phase47.py` → `archive/research/tradingbot/ml/research/phase47/run_phase47.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase48/run_phase48.py` → `archive/research/tradingbot/ml/research/phase48/run_phase48.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase49/ml_capture.py` → `archive/research/tradingbot/ml/research/phase49/ml_capture.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase49/run_phase49.py` → `archive/research/tradingbot/ml/research/phase49/run_phase49.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase4a/__init__.py` → `archive/research/tradingbot/ml/research/phase4a/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase4a/adaptive_quality_backtest.py` → `archive/research/tradingbot/ml/research/phase4a/adaptive_quality_backtest.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase50/run_phase50.py` → `archive/research/tradingbot/ml/research/phase50/run_phase50.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase51/run_phase51.py` → `archive/research/tradingbot/ml/research/phase51/run_phase51.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase52/__init__.py` → `archive/research/tradingbot/ml/research/phase52/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase52/label_audit_v7.py` → `archive/research/tradingbot/ml/research/phase52/label_audit_v7.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase53/__init__.py` → `archive/research/tradingbot/ml/research/phase53/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase53/execution_funnel_audit.py` → `archive/research/tradingbot/ml/research/phase53/execution_funnel_audit.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase54/__init__.py` → `archive/research/tradingbot/ml/research/phase54/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase54/model_sweep.py` → `archive/research/tradingbot/ml/research/phase54/model_sweep.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase55/__init__.py` → `archive/research/tradingbot/ml/research/phase55/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase55/feature_noise_audit.py` → `archive/research/tradingbot/ml/research/phase55/feature_noise_audit.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase56/__init__.py` → `archive/research/tradingbot/ml/research/phase56/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase56/treatment_synthesis.py` → `archive/research/tradingbot/ml/research/phase56/treatment_synthesis.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase57/trade_quality_simulation.py` → `archive/research/tradingbot/ml/research/phase57/trade_quality_simulation.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase57/trend_regime_deep_dive.py` → `archive/research/tradingbot/ml/research/phase57/trend_regime_deep_dive.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase57/write_phase57_report.py` → `archive/research/tradingbot/ml/research/phase57/write_phase57_report.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase58/trend_only_model.py` → `archive/research/tradingbot/ml/research/phase58/trend_only_model.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase59/__init__.py` → `archive/research/tradingbot/ml/research/phase59/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase59/horizon_feature_expansion.py` → `archive/research/tradingbot/ml/research/phase59/horizon_feature_expansion.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase60/__init__.py` → `archive/research/tradingbot/ml/research/phase60/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase60/auc_lift_and_validation.py` → `archive/research/tradingbot/ml/research/phase60/auc_lift_and_validation.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase61/__init__.py` → `archive/research/tradingbot/ml/research/phase61/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase61/execution_shadow_validation.py` → `archive/research/tradingbot/ml/research/phase61/execution_shadow_validation.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase62/trade_quality_shadow_analysis.py` → `archive/research/tradingbot/ml/research/phase62/trade_quality_shadow_analysis.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase63/trade_quality_shadow_calibration.py` → `archive/research/tradingbot/ml/research/phase63/trade_quality_shadow_calibration.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase64/__init__.py` → `archive/research/tradingbot/ml/research/phase64/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase64/adaptive_risk_shadow_review.py` → `archive/research/tradingbot/ml/research/phase64/adaptive_risk_shadow_review.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase65/__init__.py` → `archive/research/tradingbot/ml/research/phase65/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase65/auc_feature_lift.py` → `archive/research/tradingbot/ml/research/phase65/auc_feature_lift.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase66/__init__.py` → `archive/research/tradingbot/ml/research/phase66/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase66/label_horizon_experiments.py` → `archive/research/tradingbot/ml/research/phase66/label_horizon_experiments.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase67/__init__.py` → `archive/research/tradingbot/ml/research/phase67/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase67/trend_ensemble_specialization.py` → `archive/research/tradingbot/ml/research/phase67/trend_ensemble_specialization.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase68/__init__.py` → `archive/research/tradingbot/ml/research/phase68/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase68/combined_shadow_revalidation.py` → `archive/research/tradingbot/ml/research/phase68/combined_shadow_revalidation.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase6a/__init__.py` → `archive/research/tradingbot/ml/research/phase6a/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase6a/fault_injection_live.py` → `archive/research/tradingbot/ml/research/phase6a/fault_injection_live.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase6a/monte_carlo_pa.py` → `archive/research/tradingbot/ml/research/phase6a/monte_carlo_pa.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase6a/vol_v2_expansion.py` → `archive/research/tradingbot/ml/research/phase6a/vol_v2_expansion.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase6a/walk_forward_pa.py` → `archive/research/tradingbot/ml/research/phase6a/walk_forward_pa.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase70/fix_roadmap_final_review.py` → `archive/research/tradingbot/ml/research/phase70/fix_roadmap_final_review.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase7a/adaptive_quality_v2.py` → `archive/research/tradingbot/ml/research/phase7a/adaptive_quality_v2.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase8a/ml_kernel_rehab.py` → `archive/research/tradingbot/ml/research/phase8a/ml_kernel_rehab.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase9a/__init__.py` → `archive/research/tradingbot/ml/research/phase9a/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase9a/pm_v2_research.py` → `archive/research/tradingbot/ml/research/phase9a/pm_v2_research.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase_final_audit/__init__.py` → `archive/research/tradingbot/ml/research/phase_final_audit/__init__.py` *(pre-interrupt)*
- `tradingbot/ml/research/phase_final_audit/run_investigation.py` → `archive/research/tradingbot/ml/research/phase_final_audit/run_investigation.py` *(pre-interrupt)*

Machine-readable: `logs/_audit7_moves.json`, `logs/_audit7_commit_batches.json`.

## 3. Full suite before / after

| Metric | AUDIT_4 | AUDIT_5 | AUDIT_7 prior run | AUDIT_7 resume suite |
|--------|--------:|--------:|------------------:|---------------------:|
| Executed | 6987 | 6987 | 6997 | 6997 |
| Passed | 6932 | 6900 | 6944 | 6944 |
| Failed | 22 | 57 | 23 | 23 |
| Errors | 3 | 0 | 0 | 0 |
| Skipped | 30 | 30 | 30 | 30 |

This resume: collect-only **6997** OK; full suite re-run recorded below (or confirmed from `logs/audit7_junit.xml` if identical).

**Confirmed suite:** **6997** executed / **6944** passed / **23** failed / **0** errors / **30** skipped.

Vs AUDIT_4 (6932/22/3/30): more collected tests (+10), fewer errors (−3), failed count near AUDIT_7 prior (23). Vs AUDIT_5 (6900/57): **+44 passed / −34 failed** — archive moves did not regress the suite; AUDIT_5 ML drift largely cleared or not reintroduced by archive.

AUDIT_5 suite drift (extra `test_ml_*` failures outside `test_ml_phase*` ignore) may still appear; treat as unrelated to archive moves if the shared failure set matches prior AUDIT_7.

Collect-only after resume commits: **6997** collected.

## 4. Integrity confirmation

- `git mv` used for all moves; 4 batch commits on `main` (ahead of `origin/main`, not force-pushed).
- Untouched by this phase: `tradingbot/kernel/`, `adapters/`, `domain/`, `config/`, RiskGate, tests (no test edits), `logs/phase40_raw_setups.jsonl`.
- `archive/research/README.md` present.
- No MT5 / `.env` / orders.
- No DEAD_CODE / TEST_ONLY files moved.


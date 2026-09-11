# Production / Research / Shadow Boundary

**Status:** VERIFIED (import/call-chain; not a complete graph of 2000+ files)  
**Last verified:** 2026-09-01  
**Epistemic-Role:** OWNER of PRODUCTION_BOUNDARY.  
**Operator-effective state:** UNKNOWN  
**JSON:** `data/ml/reports/production_boundary/`

Do **not** treat `tradingbot/` as production. Do **not** treat unused research as deleted.

Classes: **PRODUCTION** · **SHADOW** · **RESEARCH** · **HISTORICAL** · **DEAD/UNUSED** · **UNKNOWN**

---

## Production path (can affect orders if daemon `--execute`)

| Module | Class | Why |
|--------|-------|-----|
| `tradingbot/application/live_runner.py` | PRODUCTION | Owns loop + shutdown |
| `tradingbot/application/bootstrap.py::build_kernel_live` | PRODUCTION | Wires adapters |
| `tradingbot/kernel/trading_kernel.py` | PRODUCTION | Cycle |
| `tradingbot/pipeline/*.py` | PRODUCTION | Six stages |
| `tradingbot/ml/integration/factory.py::build_strategy_registry` | PRODUCTION | Selection (do not change runtime) |
| `tradingbot/adapters/multi_engine_router.py` | PRODUCTION | Selector |
| `tradingbot/services/pa_production_lock.py` | PRODUCTION | PA-only selection |
| `tradingbot/adapters/legacy_strategy_registry.py` | PRODUCTION | PA inner |
| `engine/strategies/price_action_strategy.py` | PRODUCTION | Live signal |
| `tradingbot/domain/gold_strategies/router.py` | PRODUCTION | Mode dispatch |
| `tradingbot/domain/gold_strategies/m5_london_sweep.py` | PRODUCTION | Live evaluator |
| `tradingbot/domain/pa_hardening.py` | PRODUCTION | Filters |
| `tradingbot/domain/ohlcv.py::exclude_forming_bar` | PRODUCTION | Closed bar |
| `tradingbot/adapters/risk_gate.py` | PRODUCTION | Mandatory gate |
| `tradingbot/services/meta_labeler.py` | PRODUCTION (conditional reject) | Wired in RiskGate |
| `tradingbot/adapters/mt5_execution.py` | PRODUCTION | Orders when live execute |
| `tradingbot/adapters/mt5_market_data.py` | PRODUCTION | Bars |
| `tradingbot/adapters/mt5_position_manager.py` | PRODUCTION | Open positions |
| `tradingbot/config/live.py` | PRODUCTION | Live dict |
| `tradingbot/config/pa_symbol_tf_presets.py` | PRODUCTION | M5 rules |
| `tradingbot/config/dotenv_loader.py` | PRODUCTION | Env fill |
| `scripts/start_bot.py`, `start_live_daemon.ps1`, `run_live_watchdog.py` | PRODUCTION | Entry |
| `tradingbot/services/kill_switch.py` | PRODUCTION | Can stop / exit 2 |

## Shadow path

| Module | Class | Why |
|--------|-------|-----|
| Inner VOL + Adaptive `generate_signal` on router | SHADOW | Computed, not selected under lock |
| `tradingbot/adapters/shadow_strategy_registry.py` | SHADOW | Log-only if enabled |
| `META_OBSERVER_MODE` | SHADOW | Never rejects |

## Research paths

`tradingbot/ml/research/**` including `v41_isolated`, `pa_live_audit`, `full_repo_audit`, `documentation_system_audit`, `documentation_consistency`.  
`tradingbot/backtest/phase26b_controlled_validation.py` — **RESEARCH_ONLY** offline logic validation; frozen config; no MT5/orders/credentials.  
`tradingbot/backtest/phase28_0_performance_foundation.py` — **RESEARCH_ONLY** XAUUSD_i performance foundation; does not authorize live trading.  
`tradingbot/backtest/phase28_1_full_baseline.py` — **RESEARCH_ONLY** chronological baseline on the Phase 28.0 approved tape; no optimization; does not authorize live trading.  
`tradingbot/backtest/phase28_2_walk_forward.py` — **RESEARCH_ONLY** 60/20/20 chronological walk-forward; TRAIN/VAL descriptive; no optimization.  
`tradingbot/backtest/phase28_3_monte_carlo.py` — **RESEARCH_ONLY** Monte Carlo on Phase 28.1/28.2 baseline trades; MODELED perturbations; no optimization; does not authorize live trading.  
`tradingbot/backtest/phase28_4_strategy_diagnosis.py` — **RESEARCH_ONLY** diagnosis of stored RAW gold_ny_sweep setups; analytical counterfactuals only; no optimization; does not authorize live trading.  
`tradingbot/backtest/phase29_research_tape.py` — **RESEARCH_ONLY** long-horizon XAUUSD_i tape foundation; attach-only collection; does not overwrite Phase 28 canonical M5; does not authorize live trading.  
`tradingbot/backtest/phase30_unchanged_strategy_evaluation.py` — **RESEARCH_ONLY** unchanged gold_ny_sweep evaluation on the Phase 29 canonical tape; no optimization; does not authorize live trading.  
`tradingbot/backtest/phase31_event_independence.py` — **RESEARCH_ONLY** event independence / concentration audit; mechanical event IDs; no optimization; does not authorize live trading.  
`tradingbot/backtest/phase32_walk_forward.py` — **RESEARCH_ONLY** chronological 60/20/20 walk-forward of unchanged gold_ny_sweep; no optimization; does not authorize live trading.  
`tradingbot/backtest/phase33_robustness.py` — **RESEARCH_ONLY** pre-declared robustness diagnostics on the Phase 30/32 baseline; no optimization; does not authorize live trading.  
`tradingbot/backtest/phase34_statistical_validation.py` — **RESEARCH_ONLY** signal vs event bootstrap/MC; not independent-signal evidence; does not authorize live trading.  
`tradingbot/backtest/phase35_execution_reality.py` — **RESEARCH_ONLY** broker cost/execution AND-gate; no live orders; MODELED is not VERIFIED.  
`tradingbot/backtest/phase36_strategy_verdict.py` — **RESEARCH_ONLY** strategy evidence verdict from Phases 28.0–35; no optimization; does not authorize live trading.  
`tradingbot/backtest/phase37_long_horizon_tape.py` — **RESEARCH_ONLY** attach-only XAUUSD_i long-horizon tape; does not overwrite Phase 28 canonical M5; does not authorize live trading.  
`tradingbot/backtest/phase38_intelligent_evidence_acquisition.py` — **RESEARCH_ONLY** intelligent evidence acquisition; may launch identified MT5; no bot/orders/.env; does not overwrite Phase 28 M5.  
`tradingbot/backtest/phase39_broker_economics_execution.py` — **RESEARCH_ONLY** broker economics/execution evidence; may attach identified MT5 read-only; does not overwrite Phase 28 M5.  
`tradingbot/backtest/phase40_full_horizon_validation.py` — **RESEARCH_ONLY** full-horizon unchanged-strategy validation on the Phase 38 XAUUSD_i M5 tape; does not overwrite Phase 28 M5.  
`tradingbot/backtest/phase41_final_evidence_closure.py` — **RESEARCH_ONLY** final evidence closure / readiness audit; reads Phase 38–40 artifacts; does not rescan or overwrite Phase 28 M5.
`tradingbot/backtest/phase42_broker_cost_execution_closure.py` — **RESEARCH_ONLY** broker cost/execution telemetry; attach-if-running; does not overwrite Phase 28 M5.
`tradingbot/backtest/phase43_broker_cost_execution_validation.py` — **RESEARCH_ONLY** account-specific cost/identity/telemetry; attach-if-running; does not overwrite Phase 28 M5.
`tradingbot/backtest/phase44_executable_backtest_readiness.py` — **RESEARCH_ONLY** fail-closed executable gate.
`tradingbot/backtest/phase45_event_oos_regime_robustness.py` — **RESEARCH_ONLY** frozen-tape robustness.
`tradingbot/backtest/phase46_production_live_parity_audit.py` — **RESEARCH_ONLY** live-parity audit; does not import live.py.
`tradingbot/backtest/phase47_blocker_closure.py` — **RESEARCH_ONLY** blocker closure; no .env.
`tradingbot/backtest/phase48_executable_backtest.py` — **RESEARCH_ONLY** fail-closed executable gate.
`tradingbot/backtest/phase49_final_event_oos_validation.py` — **RESEARCH_ONLY** frozen robustness.
`tradingbot/backtest/phase50_final_production_parity.py` — **RESEARCH_ONLY** final live-parity; does not import live.py.
`tradingbot/backtest/phase51_final_evidence_closure.py` — **RESEARCH_ONLY** final evidence closure; no .env.
`tradingbot/backtest/phase52_optimization_gate.py` — **RESEARCH_ONLY** fail-closed optimization gate; no search.
`tradingbot/backtest/phase53_shadow_readiness.py` — **RESEARCH_ONLY** shadow specification; does not activate.
`tradingbot/backtest/phase54_account_broker_evidence.py` — **RESEARCH_ONLY** attach-if-running account/symbol forensics; no .env.
`tradingbot/backtest/phase55_cost_scenario_analysis.py` — **RESEARCH_ONLY** ECN/CLASSIC/CENT scenarios; not account-verified.
`tradingbot/backtest/phase56_symbol_mapping_final_gate.py` — **RESEARCH_ONLY** information-value ranking; does not optimize.
`tradingbot/backtest/phase57_account_product_forensics.py` — **RESEARCH_ONLY** product discriminators; no .env.
`tradingbot/backtest/phase58_commission_accountability.py` — **RESEARCH_ONLY** cost scenarios/break-even.
`tradingbot/backtest/phase59_symbol_equivalence_forensics.py` — **RESEARCH_ONLY** EV-EQ-01 forensics; no rename.
`tradingbot/backtest/phase60_unified_evidence_gate.py` — **RESEARCH_ONLY** unified G1–G8 gate.
`tradingbot/backtest/phase61_edge_survival_forensics.py` — **RESEARCH_ONLY** frozen-tape edge survival; no MT5.
`tradingbot/backtest/phase62_operator_action_economics.py` — **RESEARCH_ONLY** action ranking; no orders.
`tradingbot/backtest/phase63_next_step_gate.py` — **RESEARCH_ONLY** next-step gate; no optimize/live.
`tradingbot/backtest/phase64_strategy_event_forensics.py` — **RESEARCH_ONLY** event lineage/MFE; no SL change.
`tradingbot/backtest/phase65_diagnostic_experiments.py` — **RESEARCH_ONLY** pre-declared diagnostics.
`tradingbot/backtest/phase66_strategy_root_cause.py` — **RESEARCH_ONLY** cause tree.
`tradingbot/backtest/phase67_next_research_gate.py` — **RESEARCH_ONLY** next research target; no optimize/live.
`tradingbot/backtest/phase68_exit_forensics.py` — **RESEARCH_ONLY** ENTRY-EXIT path walk; no SL change.
`tradingbot/backtest/phase69_exit_geometry.py` — **RESEARCH_ONLY** SL/TP code inspection.
`tradingbot/backtest/phase70_exit_counterfactuals.py` — **RESEARCH_ONLY** predeclared diagnostics.
`tradingbot/backtest/phase71_extreme_winner_forensics.py` — **RESEARCH_ONLY** outlier forensics.
`tradingbot/backtest/phase72_exit_root_cause.py` — **RESEARCH_ONLY** cause matrix.
`tradingbot/backtest/phase73_exit_research_gate.py` — **RESEARCH_ONLY** next-target spec; not implemented.
`tradingbot/backtest/phase74_profit_giveback_forensics.py` — **RESEARCH_ONLY** giveback path; no SL change.
`tradingbot/backtest/phase75_exit_counterfactuals.py` — **RESEARCH_ONLY** theoretical CF; not production.
`tradingbot/backtest/phase76_sl_vs_profit_protection.py` — **RESEARCH_ONLY** SL vs protection.
`tradingbot/backtest/phase77_exit_geometry_forensics.py` — **RESEARCH_ONLY** planned-RR bins.
`tradingbot/backtest/phase78_time_exit_forensics.py` — **RESEARCH_ONLY** time buckets.
`tradingbot/backtest/phase79_exit_side_regime.py` — **RESEARCH_ONLY** side/regime grid.
`tradingbot/backtest/phase80_extreme_winner_audit.py` — **RESEARCH_ONLY** outlier audit.
`tradingbot/backtest/phase81_exit_research_gate.py` — **RESEARCH_ONLY** next-target spec; not implemented.
`tradingbot/backtest/phase82_profit_protection_design.py` — **RESEARCH_ONLY** taxonomy; no walk.
`tradingbot/backtest/phase83_profit_protection_counterfactuals.py` — **RESEARCH_ONLY** theoretical CF.
`tradingbot/backtest/phase84_tail_preservation.py` — **RESEARCH_ONLY** tail diagnostic.
`tradingbot/backtest/phase85_rescue_vs_destruction.py` — **RESEARCH_ONLY** rescue vs destruction.
`tradingbot/backtest/phase86_profit_protection_oos.py` — **RESEARCH_ONLY** fold consistency.
`tradingbot/backtest/phase87_profit_protection_interactions.py` — **RESEARCH_ONLY** side/session diagnosis.
`tradingbot/backtest/phase88_exit_design_spec.py` — **RESEARCH_ONLY** spec; not implemented.
`tradingbot/backtest/phase89_profit_protection_gate.py` — **RESEARCH_ONLY** next-target gate; not implemented.
`tradingbot/backtest/phase90_profit_giveback_path_forensics.py` — **RESEARCH_ONLY** path classes A-G.
`tradingbot/backtest/phase91_reversal_timing_forensics.py` — **RESEARCH_ONLY** timing; no timeout.
`tradingbot/backtest/phase92_mfe_mae_conditional_forensics.py` — **RESEARCH_ONLY** MFE first-cross.
`tradingbot/backtest/phase93_tail_preservation_forensics.py` — **RESEARCH_ONLY** tail discriminator.
`tradingbot/backtest/phase94_cluster_forensics.py` — **RESEARCH_ONLY** event vs signal unit.
`tradingbot/backtest/phase95_protection_family_v2.py` — **RESEARCH_ONLY** four families; not production.
`tradingbot/backtest/phase96_protection_robustness_gate.py` — **RESEARCH_ONLY** qualitative gate.
`tradingbot/backtest/phase97_profit_protection_final_gate.py` — **RESEARCH_ONLY** final gate; spec not implemented.
`tradingbot/backtest/phase98_first_favorable_state.py` — **RESEARCH_ONLY** causal snapshots.
`tradingbot/backtest/phase99_path_velocity_persistence.py` — **RESEARCH_ONLY** persistence kinds.
`tradingbot/backtest/phase100_retrace_expansion_forensics.py` — **RESEARCH_ONLY** retrace vs continuation.
`tradingbot/backtest/phase101_entry_vs_exit.py` — **RESEARCH_ONLY** entry vs exit; signal unchanged.
`tradingbot/backtest/phase102_cluster_timing_forensics.py` — **RESEARCH_ONLY** event-unit cluster timing.
`tradingbot/backtest/phase103_structure_at_retracement.py` — **RESEARCH_ONLY** predeclared structure.
`tradingbot/backtest/phase104_minimal_discriminator.py` — **RESEARCH_ONLY** counterfactual families.
`tradingbot/backtest/phase105_discriminator_gate.py` — **RESEARCH_ONLY** discriminator gate; spec not implemented.
`tradingbot/backtest/phase106_non_ohlc_data_inventory.py` — **RESEARCH_ONLY** local inventory.
`tradingbot/backtest/phase107_tick_intrabar_research.py` — **RESEARCH_ONLY** tick; no MT5.
`tradingbot/backtest/phase108_spread_path_research.py` — **RESEARCH_ONLY** spread; no broker inference.
`tradingbot/backtest/phase109_htf_context_research.py` — **RESEARCH_ONLY** M15 context; strategy unchanged.
`tradingbot/backtest/phase110_news_context_research.py` — **RESEARCH_ONLY** news; no API.
`tradingbot/backtest/phase111_multisource_alignment.py` — **RESEARCH_ONLY** declared combinations only.
`tradingbot/backtest/phase112_non_ohlc_discriminator_gate.py` — **RESEARCH_ONLY** candidate gate.
`tradingbot/backtest/phase113_non_ohlc_final_gate.py` — **RESEARCH_ONLY** final gate; spec not implemented.
`tradingbot/backtest/phase114_non_ohlc_acquisition_contract.py` — **RESEARCH_ONLY** acquisition contract; data not acquired.
`tradingbot/backtest/phase115_non_ohlc_data_acquisition.py` — **RESEARCH_ONLY** local non-OHLC ingest; no MT5; no exit spec.
`tradingbot/backtest/phase116_data_source_research.py` -- **RESEARCH_ONLY** source planning; no download; no MT5.
`tradingbot/backtest/phase117_operator_source_resolution.py` -- **RESEARCH_ONLY** operator source resolution; no MT5; no .env; no Phase 118.
`tradingbot/backtest/phase118_tick_forensic_validation.py` -- **RESEARCH_ONLY** operator tick ingest + forensic validation; no MT5; no .env.
`tradingbot/backtest/phase119_historical_tick_recovery.py` -- **RESEARCH_ONLY** historical tick source resolution; no MT5; no download; no .env.
`tradingbot/backtest/phase120_tick_export_verification.py` -- **RESEARCH_ONLY** new operator tick export verification + union coverage; no MT5; raw untouched.
`tradingbot/backtest/phase121_tick_export_verification.py` -- **RESEARCH_ONLY** new operator tick export verification + outlier coverage; no MT5; raw untouched.
`tradingbot/backtest/phase122_tick_export_verification.py` -- **RESEARCH_ONLY** new operator tick export verification + outlier coverage; no MT5; raw untouched.
`tradingbot/backtest/phase123_engineering_decision_review.py` -- **RESEARCH_ONLY** engineering decision review; no MT5; no production changes; no new tick export.
`tradingbot/backtest/request_fill_telemetry.py` — **RESEARCH_ONLY** passive request/fill schema; not wired to live.
`tradingbot/backtest/shadow_observation.py` — **RESEARCH_ONLY** inert shadow spec; cannot place orders.
`scripts/run_phase*.py`. Isolated replays. Frozen bundles loaded only if ML kernel path is used.

## Historical artifacts

`docs/`, `data/ml/live/` (historical ML-kernel logs — **not** current PA owner), old phase JSON under `data/ml/reports/phase*`.

## Dead / unused on default live

ML kernel adapter + `PIPELINE_TIMEOUT_MS`; `evaluate_m5_scalp` / `evaluate_h4_swing` / `evaluate_m15_intraday` **not looped**; 14 disabled `ACTIVE_STRATEGIES`; UnconfiguredEngineRegistry unless misconfigured.

## Ambiguous / UNKNOWN

| Item | Why |
|------|-----|
| Meta-labeler | PRODUCTION wiring; enforcement today UNKNOWN |
| `engine_settings.py` | PRODUCTION fallback hazard |
| Adaptive registry default True | Dead if factory never constructs it as selected engine; SHADOW if router probes it (it does construct Adaptive inside router) |
| M15/H4 presets | Implemented PRODUCTION code, DEAD on default loop |

Router **always constructs** VOL and Adaptive registries (`MultiEngineRouterRegistry.__init__`). Classification: **SHADOW probe**, not selected.

## Tests of critical classifications

`tests/test_documentation_consistency.py` asserts factory still selects router when ML off + router on; PA lock default true; `ACTIVE_STRATEGIES` only priceaction; research packages not imported by `build_kernel_live` source text.

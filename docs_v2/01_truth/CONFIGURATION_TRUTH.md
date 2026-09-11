# Configuration Truth

**Status:** VERIFIED (code defaults; operator values UNKNOWN)  
**Last verified:** 2026-09-03  
**Epistemic-Role:** OWNER of CONFIGURATION facts (code / daemon-if-unset).  
**Operator-effective state:** PARTIAL — Phase 25A symbol map in code; operator broker policy LOCKED (Phase 27.8, POLICY ≠ EVIDENCE); operator `.env` for `TRADINGBOT_ACCOUNT_ENV` / `TRADINGBOT_REAL_SYMBOL` UNKNOWN  
**Do not read `.env`.** Machine-readable: `data/ml/reports/configuration_truth/`.

Classes: **A** hardcoded · **B** config dict · **C** environment · **D** CLI · **E** runtime overlay · **F** fallback · **G** research-only · **H** dead/unused on default live path · **I** ambiguous.

**CODE DEFAULT ≠ DAEMON IF UNSET ≠ OPERATOR EFFECTIVE VALUE ≠ CURRENT PROCESS.** Operator and process columns are UNKNOWN unless a sanitized dump / probe exists. This file does not read `.env`.

Precedence (overlapping keys, highest first):

1. CLI-implied env (`LiveRunner` `--execute` / `--paper`) — **D/E**
2. Process environment (including `start/_load_env.bat` if used) — **C**
3. `load_dotenv`: fill only if **key not already in `os.environ`** — **C** (`dotenv_loader.py`)
4. `get_live_config()` / `apply_prop_preset` — **B/E**
5. `load_legacy_config()` merge — **B/E**
6. Python defaults — **A**
7. `engine_settings.py` hardcoded MT5 credential fallbacks — **F** (hazard; values not documented)

---

## Important settings

| Name | Class | Default | Effective if daemon unset | Consumer | Prod/shadow/research | Unknowns |
|------|-------|---------|---------------------------|----------|----------------------|----------|
| `PRIMARY_SYMBOL` | A | `XAUUSD_i` | same | kernel, MT5 | PRODUCTION | unchanged; not renamed Phase 25A; operator policy Decision 1 also locks `XAUUSD_i` (POLICY, not EV-EQ-01 proof) |
| `ACCOUNT_ENVIRONMENT` | C | unset → `DEMO` | UNKNOWN | `symbols.get_environment_trading_symbol` | PRODUCTION | `TRADINGBOT_ACCOUNT_ENV` or `TRADINGBOT_ACCOUNT_ENVIRONMENT` |
| `SYMBOL_BY_ENVIRONMENT` | B | `DEMO→XAUUSD_i`, `REAL→XAUUSD_i` (default) | same | symbol resolution | PRODUCTION | `TRADINGBOT_REAL_SYMBOL` overrides REAL slot only |
| `SYMBOL_RESOLUTION_STRICT` | B | `True` | same | `resolve_broker_symbol` | PRODUCTION | fail-closed; no ±`_i` hunt |
| `RISK_PER_TRADE` | B | `0.005` (0.5%) | same | RiskGate sizing | PRODUCTION | Phase 25A broker tick sizing; unchanged target |
| `USE_ML_KERNEL` | C | unset → false | `"false"` | `is_ml_kernel_enabled` | PRODUCTION flag; ML path RESEARCH unless gate open | operator env |
| `ENABLE_ML_SHADOW` | C | false | true | `_maybe_wrap_shadow` | SHADOW | operator env |
| `PA_PRODUCTION_LOCK` | C | true | true (daemon does not set) | `is_pa_production_lock` | PRODUCTION | operator env; lock also requires Adaptive/VOL off |
| `MULTI_ENGINE_ROUTER_ENABLED` | C | true | true | factory | PRODUCTION | operator env |
| `VOL_REGIME_ENABLED` | C | false | false | factory / router | SHADOW probe | |
| `ADAPTIVE_REGIME_ENABLED` | I | **not in `LIVE_TRADING_CONFIG`**; factory False; Adaptive class True if missing | daemon false | factory / Adaptive registry | SHADOW probe | contradiction I |
| `META_LABEL_THRESHOLD` | C | 0.38 | 0.38 | RiskGate meta | PRODUCTION (can reject) | |
| `META_OBSERVER_MODE` | C | false | false | `apply_pa_meta_decision` | SHADOW if true | |
| `DEMO_DISABLE_SESSION_FILTER` | C | false | UNKNOWN | PA session | PRODUCTION if true | operator |
| `PIPELINE_TIMEOUT_MS` | A | 500.0 | unused on PA | ML `kernel_adapter` | H on default path | |
| `TREND_MODEL_ID` | A | `trend_rf_v40` | unused on PA | calibrator | H on default path | |
| `TREND_ENGINE_ID` | A | `trend_rf_v40` | unused | phase15a | H | |
| `TREND_ENGINE_V41_ID` | A | `trend_rf_v41` | unused | versioning | H | |
| `TREND_MODEL_VERSION` | C | default active v41 | unused on PA | `resolve_active_trend_engine_id` | H | |
| `LOOP_INTERVAL` | B | 30 | 30 | kernel | PRODUCTION | |
| `RISK_PER_TRADE` | B | 0.005 | 0.005 | RiskGate | PRODUCTION | prop/tier overlay |
| CLI `--symbol` | D | `XAUUSD` | not used by daemon | `__main__.py` | H for daemon | |
| CLI `--tf` | D | `M15` | not used | `__main__.py` | H for daemon | |
| `BacktestConfig.timeframe` | A | `M5` | n/a | backtest engine | RESEARCH/BACKTEST | aligned Phase 25B with live PA M5 |
| `BacktestConfig.risk_per_trade` | A | `0.005` | n/a | backtest RiskGate | RESEARCH/BACKTEST | aligned Phase 25B with live |
| `BacktestConfig.symbols` | A | `[PRIMARY_SYMBOL]` (`XAUUSD_i`) | n/a | backtest engine | RESEARCH/BACKTEST | not bare `XAUUSD` default |
| `BacktestConfig.require_htf_alignment_m5` | A | `False` | n/a | backtest RiskGate | RESEARCH/BACKTEST | matches PA M5 preset |
| `BacktestConfig.spread_mode` | A | `AUTO` | n/a | backtest broker | RESEARCH/BACKTEST | DATASET if bid/ask columns; else PROXY |
| `BacktestConfig.commission_status` | A | `UNKNOWN` | n/a | backtest broker | RESEARCH/BACKTEST | ZERO only with explicit evidence; Phase 27.8 Decision 3 = `VERIFIED_SCHEDULE` (gate). Phase 27.28: account_product_type UNKNOWN; gold zeros remain `OBSERVED_ZERO_NOT_PROVEN`; no account-applicable schedule; default remains UNKNOWN |
| `BacktestConfig.swap_status` | A | `UNKNOWN` | n/a | backtest cost model | RESEARCH/BACKTEST | Phase 27.13/27.29: `BROKER_RATE_ONLY` is current-rate evidence only; historical series UNKNOWN; realized zero ≠ historical zero; does not make cost COMPLETE |
| `BacktestConfig.slippage_status` | A | `MODELED_PROXY` | n/a | backtest cost model | RESEARCH/BACKTEST | Phase 27.14/27.30: Decision 5 MODELED implemented as MODELED_PROXY; ≠ REALIZED; `slippage_pips=0.8` is an assumption; 0 genuine requested-vs-fill pairs; does not make cost COMPLETE |
| `BacktestConfig.dataset_symbol_map` | B | `{}` | n/a | dataset contract | RESEARCH/BACKTEST | required when parquet label ≠ configured instrument; Phase 27.8 Decision 2 = ONLY_WITH_EXPLICIT_DATASET_MAP. Phase 27.27: default remains `{}`; 30 logical XAUUSD `MISSING_EXPLICIT_MAP`; 0 maps inserted |
| Dataset metadata sidecar | — | `{parquet}.metadata.json` | n/a | dataset provenance | RESEARCH/BACKTEST | **32 deployed** (Phase 25E); auto-loaded on cache hit |
| Phase 25H read-only MT5 | `run_phase25h_collection()` | n/a | attach-only; no symbol_select | evidence only | **DEFERRED** 2026-09-04 — operator session required |
| Phase 25L MT5 execution | `run_phase25l_collection()` | n/a | attach-only + closure | **PASS_WITH_DEFERRAL** if MT5 offline |
| Phase 25M MT5 final gate | `run_phase25m_collection()` | n/a | single bounded attach; **FINAL** broker-evidence loop | **PASS_WITH_DEFERRAL** if MT5 offline; `operator_blocked=true` |
| Phase 26 validation readiness | `run_phase26_validation_audit()` | n/a | offline audit only; no backtest execution | **PASS_WITH_DEFERRAL** — logic-only backtests valid under PROXY; cost-adjusted BLOCKED |
| Phase 26B controlled validation | `run_phase26b_collection()` / `recover_phase26b()` | n/a | offline `BacktestEngine`; frozen config; **RESEARCH_ONLY** | **PASS_WITH_DEFERRAL** (recovered 2026-09-05) — 0 trades; **D — LOGICALLY WEAK**; see Phase 26C zero-signal audit |
| Phase 26C zero-signal audit | `run_phase26c_collection()` | n/a | lightweight gate trace; no backtest rerun | **PASS_WITH_DEFERRAL** — **F — MULTIPLE BOTTLENECKS** (reclaim filter + engine journal disconnect) |
| Phase 26D kernel signal trace | `run_phase26d_collection()` | n/a | single-bar + 19-candidate pipeline trace; no backtest rerun | **PASS_WITH_DEFERRAL** — **H — MULTIPLE BOTTLENECKS** (RiskGate: meta-labeler + ATR + lot sizing; journal metric gap) |
| Phase 26E RiskGate rejection audit | `run_phase26e_collection()` | n/a | 19-candidate RiskGate gate trace; read-only | **PASS_WITH_DEFERRAL** — **F — MULTIPLE INDEPENDENT CAUSES** (symbol economics mismatch + configured meta/ATR gates; journal metric gap) |
| Phase 26F RiskGate alias fix | `run_phase26f_collection()` | n/a | `resolve_broker_symbol` before economics lookup; 19-candidate replay | **PASS_WITH_DEFERRAL** — alias fix correctness only; 0/19 allowed unchanged |
| Phase 26G RiskGate counterfactual | `run_phase26g_collection()` | n/a | audit-only gate attribution on 19 candidates; NOT performance evidence | **PASS_WITH_DEFERRAL** — sequential stack; 0/19 baseline |
| Phase 26H counterfactual consistency | `run_phase26h_collection()` | n/a | validates 26G artifact; sequential not conjunction; 19-candidate scope | **PASS_WITH_DEFERRAL** — Phase 26G accounting consistent |
| Phase 26I full-tail attribution | `run_phase26i_collection()` | n/a | artifact-only funnel 2500→19→0; no backtest rerun | **PASS_WITH_DEFERRAL** — upstream session/sweep/reclaim dominant; 0/19 RiskGate sequential stack |
| Phase 26J decision-path reconciliation | `run_phase26j_collection()` | n/a | artifact cross-check + signal-only scan; no full engine walk | **PASS_WITH_DEFERRAL** — **B — STRONGLY SUPPORTED**; 19-candidate chain reconciled; not A-level proven |
| Phase 26K full-engine reconciliation | `run_phase26k_collection()` | n/a | runtime-guarded; kernel walk ~45 min estimated; NOT executed | **DEFERRED — TOO EXPENSIVE** — Phase 26J B-level remains valid; ~1.2s/evaluable-bar |
| Phase 26L RiskGate policy audit | `run_phase26l_collection()` | n/a | static lot/META/ATR policy coherence; no backtest | **PASS_WITH_DEFERRAL** — **B — COHERENT BUT EXTREMELY RESTRICTIVE**; SMALL-tier lot floor ($1000 balance) + layered gates |
| Phase 26M operator risk-budget policy review | `run_phase26m_collection()` | n/a | document/policy audit only; no backtest/engine/MT5 | **PASS_WITH_DEFERRAL** — **CASE_2**; 0.5% risk documented (A); $1000 balance intent UNKNOWN (B); full combo alignment UNKNOWN |
| Phase 26N documentation contradiction cleanup | `run_phase26n_collection()` | n/a | doc-only stale-claim cleanup; no production changes | **PASS_WITH_DEFERRAL** — Phase 25B parity claims corrected; MICRO/SMALL terminology clarified |
| Phase 26O legacy docs truth sweep | `run_phase26o_collection()` | n/a | legacy docs/ md-only stale-claim sweep | **PASS** — no current-state 1%/M1 in docs/; clarifications added |
| Phase 26P closure audit | `run_phase26p_collection()` | n/a | consolidates 26A–26O; decision-memory only | **PASS_WITH_DEFERRAL** — B-level zero-trade; production BLOCKED; EV-EQ-01 NOT_PROVEN |
| Phase 27 broker reality | `run_phase27_collection()` | n/a | EV-EQ-01 evidence + cost foundation; attach-only operator probe | **PASS_WITH_DEFERRAL** — EV-EQ-01 NOT_PROVEN; cost-adjusted BLOCKED; MT5 operator DEFERRED if offline |
| Phase 27.5 final broker cost gate | `run_phase27_5_collection()` | n/a | fresh Real evidence attempt + cost grades + validation gate | **PASS_WITH_DEFERRAL** — COST_READY_FOR_VALIDATION=false unless all evidence complete |
| Phase 27.6 final evidence gate | `run_phase27_6_collection()` | n/a | final blocker closure; Real attach; dataset reconciliation; operator policy pack | **PASS_WITH_DEFERRAL** — NOT READY unless validation gate passes |
| Phase 27.7 final blocker closure | `run_phase27_7_collection()` | n/a | blocker matrix + validation gate re-eval; no production changes | **PASS_WITH_DEFERRAL** — COST_READY=false unless all mandatory gates PASS |
| Phase 27.8 operator policy lock | `run_phase27_8_collection()` | n/a | lock six operator broker-policy decisions; POLICY ≠ EVIDENCE; no MT5 | **LOCKED** — policy pack closed; cost-adjusted validation still BLOCKED |
| Phase 27.10 dataset symbol binding | `run_phase27_10_collection()` | n/a | fail-closed dataset→broker bind; no silent XAUUSD→XAUUSD_i; no parquet rewrite | **PASS** — missing/invalid maps BLOCKED; EV-EQ-01 still NOT_PROVEN |
| Phase 27.13 swap policy | `run_phase27_13_collection()` | n/a | implement BROKER_RATE_ONLY; no historical series synthesis | **PASS** — rates retained as evidence; historical swap UNKNOWN; cost-adjusted BLOCKED |
| Phase 27.14 slippage model | `run_phase27_14_collection()` | n/a | document MODELED as MODELED_PROXY; deviation ≠ realized | **PASS** — proxy documented; realized UNKNOWN; cost-adjusted BLOCKED |
| Phase 27.12 commission evidence | `run_phase27_12_collection()` | n/a | implement VERIFIED_SCHEDULE gate; observed zero ≠ schedule | **PASS** — 50 gold zeros = OBSERVED_ZERO_NOT_PROVEN; schedule UNKNOWN/BLOCKED; cost-adjusted BLOCKED |
| Phase 27.9 Real broker evidence | `run_phase27_9_collection()` | n/a | bounded Real attach-only; no MT5 start | **PASS** — MT5_NOT_ATTACHED; EV-EQ-01 NOT_PROVEN |
| Phase 27.11 historical bid/ask | `run_phase27_11_collection()` | n/a | inventory + optional attach; no parquet rewrite | **PASS** — 0 historical bid/ask tapes; BLOCKED_PENDING_DATA |
| Phase 27.15 cost completeness gate | `run_phase27_15_collection()` | n/a | AND of 8 required components; no profitability run | **PASS** — COST_READY_FOR_VALIDATION=false; complete datasets=0; cost-adjusted BLOCKED |
| Phase 27.16 final validation gate | `run_phase27_16_collection()` | n/a | single FINAL_GATE; not strategy/profitability/real-money approval | **PASS** — FINAL_GATE=BLOCKED; no Phase 28 |
| Phase 27.17 Real broker evidence | `run_phase27_17_collection()` | n/a | one bounded Real attach-only; no MT5 start; Demo ≠ Real | **PASS** — REAL_COLLECTED on LiteFinance-MT5-Live; XAUUSD_i YES / XAUUSD NO; EV-EQ-01 NOT_PROVEN; FINAL_GATE remains BLOCKED |
| Phase 27.18 historical bid/ask closure | `run_phase27_18_collection()` | n/a | re-audit + optional bounded copy_ticks_range; no parquet rewrite; live tick ≠ historical | **PASS** — DATASET only if genuine historical Bid/Ask; otherwise BLOCKED_PENDING_DATA; production datasets remain PROXY; FINAL_GATE remains BLOCKED |
| Phase 27.19 commission closure | `run_phase27_19_collection()` | n/a | account-applicable VERIFIED_SCHEDULE gate; public docs supporting only | **PASS** — 50 gold zeros remain OBSERVED_ZERO_NOT_PROVEN; account/product type UNKNOWN; commission UNKNOWN/BLOCKED; FINAL_GATE remains BLOCKED |
| Phase 27.20 dataset mapping closure | `run_phase27_20_collection()` | n/a | classify logical XAUUSD; no silent map; existing dataset_symbol_map only | **PASS** — 30 logical XAUUSD BLOCKED (INSUFFICIENT_PROVENANCE); 0 maps inserted; XAUUSD_i MATCH unchanged; FINAL_GATE remains BLOCKED |
| Phase 27.21 evidence synthesis | `run_phase27_21_collection()` | n/a | read-only matrix; no MT5; gates not weakened | **PASS** — 27.18 existence PROVEN; dataset/validation spread BLOCKED; 30 maps BLOCKED; commission UNKNOWN/BLOCKED; FINAL_GATE remains BLOCKED |
| Phase 27.22 commission forensic | `run_phase27_22_collection()` | n/a | Real account/product identifiers + deal tape; no inference from zeros/broker/balance | **PASS** — classification `OBSERVED_ZERO_NOT_PROVEN`; account_product_type UNKNOWN; public pages supporting only; FINAL_GATE remains BLOCKED |
| Phase 27.23 bid/ask expansion | `run_phase27_23_collection()` | n/a | bounded 7-day chunked copy_ticks_range; logs only; no production overwrite | **PASS** — expand 27.18 window if Real terminal available; production parquet remains PROXY; full dataset coverage not claimed; FINAL_GATE remains BLOCKED |
| Phase 27.24 execution/cost forensics | `run_phase27_24_collection()` | n/a | read-only deal/order history; no entry-as-requested; no SimulatedBroker inference | **PASS** — swap stays BROKER_RATE_ONLY; realized slippage not manufactured; execution gate unchanged; FINAL_GATE remains BLOCKED |
| Phase 27.25 canonical bid/ask coverage | `run_phase27_25_collection()` | n/a | targeted copy_ticks_range for actual XAUUSD_i_5m range; logs only | **PASS** — coverage classified without rewriting production parquet; FINAL_GATE remains BLOCKED |
| Phase 27.26 complete canonical bid/ask | `run_phase27_26_collection()` | n/a | merge 27.25 tape + missing-interval ticks; no production overwrite | **PASS** — `PARTIAL_CANONICAL_COVERAGE` 2820/3000 (94.0%); historical_spread `PARTIAL`; 27.25 tape preserved; production parquet unchanged; FINAL_GATE remains BLOCKED |
| Phase 27.27 dataset symbol binding | `run_phase27_27_collection()` | n/a | recompute inventory; fail-closed explicit map only; no silent XAUUSD→XAUUSD_i; no map insert | **PASS** — 2 DIRECT_CANONICAL_MATCH / 30 MISSING_EXPLICIT_MAP / 0 EXPLICIT_MAPPED / 1 UNKNOWN; 0 maps inserted; EV-EQ-01 NOT_PROVEN; FINAL_GATE remains BLOCKED |
| Phase 27.28 commission evidence | `run_phase27_28_collection()` | n/a | Real-account commission forensic; zeros ≠ schedule; public pages supporting only | **PASS** — grade `OBSERVED_ZERO_NOT_PROVEN`; account_product_type UNKNOWN; VERIFIED_SCHEDULE not satisfied; FINAL_GATE remains BLOCKED |
| Phase 27.29 swap evidence | `run_phase27_29_collection()` | n/a | current Real swap rates vs historical series; zeros ≠ historical zero | **PASS** — grade `CURRENT_BROKER_RATE_ONLY`; swap_long `-89.136` / swap_short `3.45` / Wednesday; historical series UNKNOWN; FINAL_GATE remains BLOCKED |
| Phase 27.30 slippage evidence | `run_phase27_30_collection()` | n/a | genuine requested-vs-fill only; price_open ≠ requested; MODELED_PROXY ≠ REALIZED | **PASS** — grade `REALIZED_UNKNOWN_NOT_IDENTIFIABLE`; genuine pairs `0`; MODELED_PROXY preserved; FINAL_GATE remains BLOCKED |
| Phase 27.30 slippage evidence | `run_phase27_30_collection()` | n/a | genuine requested-vs-fill only; price_open ≠ requested; MODELED_PROXY ≠ REALIZED | **PASS_WITH_DEFERRAL** — grade `REALIZED_UNKNOWN_NOT_IDENTIFIABLE`; genuine pairs `0`; MODELED_PROXY preserved; FINAL_GATE remains BLOCKED |
| Phase 27.31 execution evidence | `run_phase27_31_collection()` | n/a | order lifecycle vs fill tape; no state inference; SimulatedBroker ≠ realized | **PASS** — grade `DEAL_FILL_TAPE_ONLY`; full fills `NOT_PROVEN`; linkage `INCOMPLETE`; FINAL_GATE remains BLOCKED |
| Phase 27.31 execution evidence | `run_phase27_31_collection()` | n/a | order lifecycle vs fill tape; no state inference; SimulatedBroker ≠ realized | **PASS_WITH_DEFERRAL** — grade `DEAL_FILL_TAPE_ONLY`; full fills `NOT_PROVEN`; linkage `INCOMPLETE`; FINAL_GATE remains BLOCKED |
| Phase 27.32 final cost evidence gate | `run_phase27_32_collection()` | n/a | offline synthesis 27.8–27.31; no grade upgrades; no new MT5 | **PASS** — COMPLETE_COSTS_REQUIRED `BLOCKED`; AND `0`/8; FINAL_GATE remains BLOCKED |
| Phase 27.33 EV-EQ resolution | `run_phase27_33_collection()` | n/a | same-terminal catalog; absence=NOT_PROVEN; no silent map | **FAILED** — `NOT_PROVEN`; state `B_POLICY_AUTHORIZED_XAUUSD_i_ONLY`; missing maps `30`; FINAL_GATE remains BLOCKED |
| Phase 27.33 EV-EQ resolution | `run_phase27_33_collection()` | n/a | same-terminal catalog; absence=NOT_PROVEN; no silent map | **PASS_WITH_DEFERRAL** — `NOT_PROVEN`; state `B_POLICY_AUTHORIZED_XAUUSD_i_ONLY`; missing maps `30`; FINAL_GATE remains BLOCKED |
| Phase 28.0 performance foundation | `run_phase28_0_collection()` | n/a | RESEARCH ONLY XAUUSD_i M5 signal vs RiskGate baseline; no optimization; no live auth | **PASS_WITH_DEFERRAL** — DATA_INSUFFICIENT canonical tape; 0 executable trades ≠ no edge; EV-EQ-01 NOT_PROVEN; FINAL_GATE remains BLOCKED |
| Phase 28.1 chronological full baseline | `run_phase28_1_collection()` | n/a | RESEARCH ONLY; same approved XAUUSD_i M5 fingerprint; chronological RAW vs RiskGate; no optimization/MC | **PASS_WITH_DEFERRAL** — DATA_INSUFFICIENT; 0 executable ≠ no edge |
| Phase 28.2 chronological walk-forward | `run_phase28_2_collection()` | n/a | RESEARCH ONLY; 60/20/20 bar split; TRAIN/VAL descriptive; no optimization | **PASS_WITH_DEFERRAL** — INSUFFICIENT_SAMPLE |
| Phase 28.3 Monte Carlo robustness | `run_phase28_3_collection()` | n/a | RESEARCH ONLY; baseline trades only; MODELED spread/slippage; no optimization | **PASS_WITH_DEFERRAL** — INSUFFICIENT_SAMPLE |
| Phase 28.4 strategy diagnosis | `run_phase28_4_collection()` | n/a | RESEARCH ONLY; reconstruct 24 RAW setups; analytical counterfactuals; no optimization | **PASS_WITH_DEFERRAL** — official answer J; Phase 28.5 not started |
| Phase 29 research tape | `run_phase29_collection()` | n/a | RESEARCH/data-engineering; longest defensible XAUUSD_i tape; no silent XAUUSD merge; no overwrite of Phase 28 M5 | **PASS_WITH_DEFERRAL** — M5 14.9d; 180d NOT_OBSERVED |
| Phase 30 unchanged strategy evaluation | `run_phase30_collection()` | n/a | RESEARCH ONLY; frozen gold_ny_sweep on Phase 29 canonical XAUUSD_i M5; no optimization | **PASS_WITH_DEFERRAL** — INDETERMINATE / DATA_INSUFFICIENT |
| Phase 31 event independence | `run_phase31_collection()` | n/a | RESEARCH ONLY; mechanical event IDs from Asian range + side; no optimization | **PASS** — HIGH_DEPENDENCE; not a strategy failure |
| Phase 32 chronological walk-forward | `run_phase32_collection()` | n/a | RESEARCH ONLY; frozen 60/20/20; no optimization; no fold dropping | **PASS_WITH_DEFERRAL** — INSUFFICIENT_SAMPLE |
| Phase 33 robustness | `run_phase33_collection()` | n/a | RESEARCH ONLY; pre-declared SL/RR/cost diagnostics; no optimization | **PASS_WITH_DEFERRAL** — INSUFFICIENT_SAMPLE |
| Phase 34 statistical validation | `run_phase34_collection()` | n/a | RESEARCH ONLY; signal vs event bootstrap/MC; no optimization | **PASS_WITH_DEFERRAL** — INSUFFICIENT_SAMPLE |
| Phase 35 execution reality | `run_phase35_collection()` | n/a | RESEARCH ONLY; broker cost/execution AND-gate; no live orders | **PASS** — INCOMPLETE; MODELED not VERIFIED |
| Phase 36 strategy verdict | `run_phase36_collection()` | n/a | RESEARCH ONLY; synthesize 28.0–35; no optimization; no production change | **PASS** — INSUFFICIENT_EVIDENCE; FINAL_GATE BLOCKED |
| Phase 37 long-horizon tape | `run_phase37_collection()` | n/a | RESEARCH/data-acquisition; attach-only XAUUSD_i M5; never overwrite frozen Phase 28 snapshot | **PASS** — terminal ATTACHED; Phase 38 not started |
| Phase 38 intelligent evidence | `run_phase38_collection()` | n/a | RESEARCH; may launch identified MT5; no bot/orders/.env | **PASS**; Phase 39 not started |
| Phase 39 broker economics | `run_phase39_collection()` | n/a | RESEARCH; cost/execution evidence + labeled sensitivity; no bot/orders/.env | **PASS**; Phase 40 not started |
| Phase 40 full-horizon validation | `run_phase40_collection()` | n/a | RESEARCH; full 1291-day unchanged gold_ny_sweep on phase38 XAUUSD_i M5; no bot/orders/.env | **PASS** |
| Phase 41 final evidence closure | `run_phase41_collection()` | n/a | RESEARCH/AUDIT; no rescan; no bot/orders/.env | **PASS**; Phase 42 started |
| Phase 42 broker cost/execution closure | `run_phase42_collection()` | n/a | RESEARCH/AUDIT; attach-if-running only; no bot/orders/.env | **PASS**; Phase 43 started |
| Phase 43 broker cost/execution validation | `run_phase43_collection()` | n/a | RESEARCH/AUDIT; attach-if-running only; no bot/orders/.env | **PASS**; Phase 44 not started |
| Phase 44 executable readiness | `run_phase44_collection()` | n/a | RESEARCH; fail-closed; no bot/orders/.env | **PASS**; executable BLOCKED |
| Phase 45 event/OOS robustness | `run_phase45_collection()` | n/a | RESEARCH; frozen Phase 40 only | **PASS**; no optimization |
| Phase 46 live-parity audit | `run_phase46_collection()` | n/a | RESEARCH/AUDIT; no .env | **PASS**; NOT_READY |
| Phase 47 blocker closure | `run_phase47_collection()` | n/a | RESEARCH; no .env/MT5/bot | **PASS**; no blocker closed |
| Phase 48 executable backtest | `run_phase48_collection()` | n/a | RESEARCH; fail-closed | **PASS**; BLOCKED |
| Phase 49 event/OOS validation | `run_phase49_collection()` | n/a | RESEARCH; frozen tape | **PASS**; FRAGILE |
| Phase 50 final parity | `run_phase50_collection()` | n/a | RESEARCH/AUDIT; no .env | **PASS**; NOT_READY |
| Phase 51 final evidence closure | `run_phase51_collection()` | n/a | RESEARCH; no .env/MT5/bot | **PASS**; no blocker closed |
| Phase 52 optimization gate | `run_phase52_collection()` | n/a | RESEARCH; fail-closed; no search | **PASS**; BLOCKED |
| Phase 53 shadow readiness | `run_phase53_collection()` | n/a | RESEARCH; spec only; no orders | **PASS**; NOT_ACTIVATED |
| Phase 54 account/broker evidence | `run_phase54_collection()` | n/a | RESEARCH; attach-if-running | **PASS**; product not verified |
| Phase 55 cost scenarios | `run_phase55_collection()` | n/a | RESEARCH; SCENARIO only | **PASS**; CLASSIC/CENT UNKNOWN |
| Phase 56 information-value gate | `run_phase56_collection()` | n/a | RESEARCH; no optimize | **PASS**; FINAL_GATE BLOCKED |
| Phase 57 account product forensics | `run_phase57_collection()` | n/a | RESEARCH; attach-if-running | **PASS**; G1 PARTIAL |
| Phase 58 commission accountability | `run_phase58_collection()` | n/a | RESEARCH; scenarios + break-even | **PASS**; G2 not VERIFIED |
| Phase 59 symbol equivalence | `run_phase59_collection()` | n/a | RESEARCH; no rename | **PASS**; G3 NOT_PROVEN |
| Phase 60 unified evidence gate | `run_phase60_collection()` | n/a | RESEARCH; no optimize/live | **PASS**; TARGETED_EVIDENCE_COLLECTION |
| Phase 61 edge survival forensics | `run_phase61_collection()` | n/a | RESEARCH; frozen jsonl only | **PASS**; EDGE_QUALITY scored |
| Phase 62 operator action economics | `run_phase62_collection()` | n/a | RESEARCH; qualitative ranking | **PASS**; no fake probabilities |
| Phase 63 next-step gate | `run_phase63_collection()` | n/a | RESEARCH; no optimize/live | **PASS**; STRATEGY_RESEARCH_BEFORE_BROKER_WORK |
| Phase 64 strategy event forensics | `run_phase64_collection()` | n/a | RESEARCH; frozen jsonl | **PASS**; diagnosis only |
| Phase 65 diagnostic experiments | `run_phase65_collection()` | n/a | RESEARCH; pre-declared only | **PASS**; no threshold search |
| Phase 66 strategy root cause | `run_phase66_collection()` | n/a | RESEARCH; cause tree | **PASS**; no optimize |
| Phase 67 next research gate | `run_phase67_collection()` | n/a | RESEARCH; one target | **PASS**; EXIT_RESEARCH |
| Phase 68 exit forensics | `run_phase68_collection()` | n/a | RESEARCH; frozen path walk | **PASS**; diagnosis only |
| Phase 69 exit geometry | `run_phase69_collection()` | n/a | RESEARCH; code inspection | **PASS**; no SL/TP change |
| Phase 70 exit counterfactuals | `run_phase70_collection()` | n/a | RESEARCH; predeclared only | **PASS**; no search |
| Phase 71 extreme winner | `run_phase71_collection()` | n/a | RESEARCH; outlier kept | **PASS**; baseline unchanged |
| Phase 72 exit root cause | `run_phase72_collection()` | n/a | RESEARCH; re-ranked causes | **PASS**; no optimize |
| Phase 73 exit research gate | `run_phase73_collection()` | n/a | RESEARCH; one target spec | **PASS**; not implemented |
| Phase 74 profit giveback | `run_phase74_collection()` | n/a | RESEARCH; frozen path | **PASS**; diagnosis only |
| Phase 75 exit counterfactuals | `run_phase75_collection()` | n/a | RESEARCH; predeclared CF | **PASS**; not optimal |
| Phase 76 SL vs protection | `run_phase76_collection()` | n/a | RESEARCH; no SL search | **PASS** |
| Phase 77 exit geometry RR | `run_phase77_collection()` | n/a | RESEARCH; no RR search | **PASS** |
| Phase 78 time exit | `run_phase78_collection()` | n/a | RESEARCH; predeclared buckets | **PASS** |
| Phase 79 side/regime exit | `run_phase79_collection()` | n/a | RESEARCH; grid descriptive | **PASS** |
| Phase 80 extreme winner audit | `run_phase80_collection()` | n/a | RESEARCH; baseline kept | **PASS** |
| Phase 81 exit research gate | `run_phase81_collection()` | n/a | RESEARCH; one target | **PASS**; not implemented |
| Phase 82 protection taxonomy | `run_phase82_collection()` | n/a | RESEARCH; no walk | **PASS**; no search |
| Phase 83 protection CF | `run_phase83_collection()` | n/a | RESEARCH; predeclared | **PASS**; not optimal |
| Phase 84 tail preservation | `run_phase84_collection()` | n/a | RESEARCH; outlier kept | **PASS** |
| Phase 85 rescue vs destruction | `run_phase85_collection()` | n/a | RESEARCH; not expectancy-only | **PASS** |
| Phase 86 protection OOS | `run_phase86_collection()` | n/a | RESEARCH; OOS not selector | **PASS** |
| Phase 87 protection interactions | `run_phase87_collection()` | n/a | RESEARCH; diagnosis only | **PASS** |
| Phase 88 exit design spec | `run_phase88_collection()` | n/a | RESEARCH; not implemented | **PASS** |
| Phase 89 protection gate | `run_phase89_collection()` | n/a | RESEARCH; one target | **PASS**; not implemented |
| Phase 90 path forensics | `run_phase90_collection()` | n/a | RESEARCH; A-G classes | **PASS**; no search |
| Phase 91 reversal timing | `run_phase91_collection()` | n/a | RESEARCH; no timeout | **PASS** |
| Phase 92 MFE conditional | `run_phase92_collection()` | n/a | RESEARCH; CROSS_LEVELS | **PASS** |
| Phase 93 tail discriminator | `run_phase93_collection()` | n/a | RESEARCH; outlier kept | **PASS** |
| Phase 94 cluster forensics | `run_phase94_collection()` | n/a | RESEARCH; event unit | **PASS** |
| Phase 95 protection v2 | `run_phase95_collection()` | n/a | RESEARCH; 4 families | **PASS**; not optimal |
| Phase 96 robustness gate | `run_phase96_collection()` | n/a | RESEARCH; qualitative | **PASS** |
| Phase 97 protection final gate | `run_phase97_collection()` | n/a | RESEARCH; one target | **PASS**; not implemented |
| Phase 98 first-favorable state | `run_phase98_collection()` | n/a | RESEARCH; causal snapshots | **PASS**; no search |
| Phase 99 persistence | `run_phase99_collection()` | n/a | RESEARCH; not a rule | **PASS** |
| Phase 100 retrace expansion | `run_phase100_collection()` | n/a | RESEARCH; outlier kept | **PASS** |
| Phase 101 entry vs exit | `run_phase101_collection()` | n/a | RESEARCH; signal unchanged | **PASS** |
| Phase 102 cluster timing | `run_phase102_collection()` | n/a | RESEARCH; event unit | **PASS** |
| Phase 103 structure at retrace | `run_phase103_collection()` | n/a | RESEARCH; predeclared | **PASS** |
| Phase 104 minimal discriminator | `run_phase104_collection()` | n/a | RESEARCH; not exit rules | **PASS** |
| Phase 105 discriminator gate | `run_phase105_collection()` | n/a | RESEARCH; spec not implemented | **PASS** |
| PA M5 `MIN_CONFIDENCE` | B | 0.52 | 0.52 | signal | PRODUCTION | |
| PA M5 `MIN_QUALITY_SCORE` | B | 55 | 55 | hardening | PRODUCTION | |
| PA M5 `COOLDOWN_BARS` | B | 18 | 18 | RiskGate | PRODUCTION | |
| PA M5 `MAX_TRADES_PER_DAY` | B | 3 | 3 | RiskGate | PRODUCTION | |
| PA M5 NY hours | B | 15–16 | 15–16 | `_in_entry_window` | PRODUCTION | `DEMO_DISABLE_SESSION_FILTER` |
| `MAX_SPREAD_PIPS` | B | 5.0 in base PA | live tick vs 5 | `check_spread_gate` | PRODUCTION | missing tick → 999 |
| `ACTIVE_STRATEGIES` | A | only priceaction True | same | StrategyManager | PRODUCTION | |
| v41 calibration factor | A | 1.0 fallback | n/a (kernel off) | `engine_calibration_factor` | RESEARCH / inactive | do not copy v40 |

## Dead / unused on default live (H)

`PIPELINE_TIMEOUT_MS`, ML engine IDs, Adaptive/VOL *selection* (probe still runs), M15/H4 presets in the kernel loop, CLI backtest defaults.

## Research-only (G)

Phase scripts forcing `USE_ML_KERNEL=1`, `tradingbot/ml/research/*` configs, isolated replay parameters.

## Contradiction notes

- Shadow: code default false vs daemon true (**C** mismatch, documented).
- Adaptive key missing vs Adaptive class default True (**I**).
- `engine_settings` credential fallbacks (**F**) — do not print values.
- `DEMO_MODE=true` vs `--execute` (**C**).

JSON writer: `tradingbot/ml/research/documentation_system_audit` does not dump secrets. Configuration snapshot: `data/ml/reports/configuration_truth/config_map.json`.

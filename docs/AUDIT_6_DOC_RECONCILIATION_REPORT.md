# AUDIT_6 — Stale Documentation Reconciliation

**Phase:** PROJECT_AUDIT_6  
**Generated:** 2026-09-10  
**Scope:** Documentation-only reconciliation of stale pipeline-stage, live-timeframe, and dead-config claims. No `.py` / test / Phase 40 tape changes in this phase.

## Code ground truth (verified before edits)

| Topic | Actual code | Evidence |
|-------|-------------|----------|
| Pipeline stages | **6**: Data → Indicator → Signal → **SignalFilter** → Risk → Execution | `tradingbot/kernel/trading_kernel.py` `_pipeline` construction |
| SignalFilter default | Wired always; behavior **OFF** (pass-through) unless `TRADINGBOT_SIGNAL_FILTER=WPSQF` | `tradingbot/services/signal_filter_mode.py` `resolve_signal_filter_mode()`; `signal_filter_stage.py` |
| Live TIMEFRAMES | Dict may list `5m/15m/4h`, but `get_live_config()` **forces `["5m"]`** when `MULTI_ENGINE_ROUTER_ENABLED` (default **true**) or adaptive/vol flags | `tradingbot/config/live.py` `get_live_config()` |
| `TIMEFRAME_CONFIGS` / `get_timeframe_config()` | Defined; **no live/backtest call sites** | AUDIT_1 + `docs/robot_behavior_audit/dead_features.md` |

---

## 1. Claim table

| File | Claim found | Stale? | What was changed |
|------|-------------|--------|------------------|
| `docs/CAPABILITIES.md` | «pipeline ۵ مرحله» | **Yes** | Updated to ۶ stages + SignalFilter default OFF note |
| `docs/CAPABILITIES.md` | §2 «XAUUSD + PA + M5/M15/H4 فعال» | **Ambiguous → clarified** | Live default M5-only; presets still exist |
| `docs/CAPABILITIES.md` | Concurrent M5/M15/H4 | Already marked historical | Left (already correct) |
| `docs/ARCHITECTURE_FA.md` | Diagram + «۵ مرحله» / `pipeline 5-stage` | **Yes** | Six-stage diagram/table; SignalFilter flag-gated; live TF note |
| `docs/ONBOARDING_FA.md` | Multiple «۵ مرحله» + M5/M15/H4 as live TFs | **Yes** | All stage counts → ۶; mermaid/tree/table; live default M5 |
| `docs/WHITEBOARD_FA.md` | ۵ کارگر / ۵مرحله‌ای; «هر بازار نماد×TF»; `XAUUSD × M5/M15/H4` | **Yes** | Six workers + SignalFilter; live M5 loop note; current status line |
| `دستورات_اجرایی.md` | `TF = M5 + M15 + H4 (همزمان)` | **Yes** | Live TF = M5 only; presets distinguished; dead `TIMEFRAME_CONFIGS` note |
| `docs/PHASE2_STEP4_LIVE_LOOP_FA.md` | «۴ نماد × ۴ تایم‌فریم» as current | **Yes (historical result misread as current)** | Labeled historical; pointed to current M5-only live |
| `docs/PHASE3_BACKTEST_FA.md` | Pipeline diagram بدون SignalFilter | **Yes** | Inserted SignalFilter (default OFF) in diagram + candle step |
| `docs/phase8_data_collection.md` | Architecture TFs as if live topology | **Ambiguous** | Clarified collection/ML roles vs live M5; dead TIMEFRAME_CONFIGS note |
| `docs/PHASE2_STEP1_MT5_FA.md` | «هسته جدید: M5, M15, H4» | **Yes** | Presets vs live-default M5 |
| `docs/PHASE2_STEP2_STRATEGIES_FA.md` | «تایم‌فریم‌ها: M5, M15, H4» as وضعیت فعلی | **Ambiguous** | Clarified presets vs live M5-only |
| `tradingbot/ml/research/phase22a/system_architecture.md` | «5-stage cycle» | **Yes (dated audit)** | Corrected to 6-stage + reconciliation note |
| `docs/robot_behavior_audit/*` | Six-stage; TIMEFRAME_CONFIGS unused | **No** | Unchanged (already MATCHES_CODE) |
| `docs_v2/**` architecture/truth | Six stages; M5 force | **No** | Unchanged (already MATCHES_CODE) |

---

## 2. Files actually edited

1. `docs/CAPABILITIES.md`
2. `docs/ARCHITECTURE_FA.md`
3. `docs/ONBOARDING_FA.md`
4. `docs/WHITEBOARD_FA.md`
5. `دستورات_اجرایی.md`
6. `docs/PHASE2_STEP4_LIVE_LOOP_FA.md`
7. `docs/PHASE3_BACKTEST_FA.md`
8. `docs/phase8_data_collection.md`
9. `docs/PHASE2_STEP1_MT5_FA.md`
10. `docs/PHASE2_STEP2_STRATEGIES_FA.md`
11. `tradingbot/ml/research/phase22a/system_architecture.md`
12. `docs/AUDIT_6_DOC_RECONCILIATION_REPORT.md` *(this report)*

**Not edited (already accurate or out of stale-claim scope):**  
`docs/robot_behavior_audit/*.md`, canonical `docs_v2/02_architecture/*` / `docs_v2/01_truth/*` pipeline docs.

**No files deleted.**

---

## 3. Integrity confirmation

- **No `.py` files edited in this phase** (only the research markdown under `phase22a/`).
- **No test files** touched.
- **No** `kernel/`, `adapters/`, `domain/`, `execution/`, RiskGate, or `config/` code changes.
- **Phase 40 frozen tape** not touched.
- **No MT5 / `.env` / orders.**
- Full pytest suite **not** run (documentation-only phase, per brief).

Pre-existing dirty `.py` / test files from AUDIT_3–5 remain in the working tree from earlier phases; they were **not** modified by AUDIT_6.

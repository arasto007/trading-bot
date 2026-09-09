# ML Status

> **Canonical ML memory (2026-09-01):** `docs_v2/07_ml/ML_SYSTEM_STATE.md`, `MODEL_REGISTRY.md`, `CALIBRATION_STATE.md`. This file remains supporting. v41 stays **C / 1.0 / inactive**.

## Status

- **Status:** PARTIAL (source-code VERIFIED; runtime-artifact evidence incorporated 2026-08-22)
- **Last Verified:** 2026-08-31
- **Verification Method:** Factory flags, shadow config, meta-labeler wiring, read-only runtime artifact inspection
- **Source-code baseline commit:** `57bf778c23cefffe508bb49079688b177796f67e`

## Scope

**Current operational status** of ML/AI components relative to live trading decisions.

## Evidence Classification

| Class | Applies to |
|-------|------------|
| **VERIFIED FROM SOURCE CODE** | Default engine flags, wiring, DISABLED ML kernel |
| **VERIFIED FROM FILES** | Artifact presence, historical logs, meta decision records |
| **NOT PROVEN** | Current ML-kernel production dominance; continuous meta enforcement today |

## Summary Table

| Component | Implementation | Live decision impact | Status |
|-----------|----------------|---------------------|--------|
| ML Kernel (`USE_ML_KERNEL`) | `MLKernelRegistry` + stack | Would replace signal source | **DISABLED** (source code) |
| ML Shadow (`ENABLE_ML_SHADOW`) | `ShadowStrategyRegistry` | Log-only comparison | **SHADOW** (daemon default ON) |
| ML Live Gate | `shadow_gate.evaluate_ml_live_gate` | Blocks ML kernel only | **N/A** (ML off) |
| Meta-labeler | `MetaLabeler` in RiskGate | Can reject PA entries when gating active | **PARTIAL** |
| Meta observer mode | `META_OBSERVER_MODE` | Never rejects | **DISABLED** (default false) |
| TradeQualityEngine | VOL registry | Filters VOL signals | **N/A** (PA path) |
| XGBoost / LightGBM training | `ml/training/` | Offline research | **UNUSED** live |
| Phase research scripts | `ml/research/phase*` | None on default path | **DEAD** live |
| DQN / PPO / TFT / FinBERT | — | — | **NOT PRESENT** |
| `data/ml/live/` logs | Historical ML-kernel monitoring | Not default PA router path | **VERIFIED FROM FILES** (historical) |

## ML Kernel

| Field | Value |
|-------|-------|
| **Enable** | `USE_ML_KERNEL=true` AND env must be explicitly set |
| **Default daemon** | `USE_ML_KERNEL=false` |
| **Gate when enabling** | `evaluate_ml_live_gate()` may downgrade to inner engine |
| **Fallback** | `ALLOW_LEGACY_FALLBACK` env (default false) |

**Active trend identifier (ML path only):** `resolve_active_trend_engine_id()` defaults to `trend_rf_v41`. `trend_rf_v40` is the frozen rollback / historical label. v40-validated calibration factors stay bound to v40. Isolated TREND replay (1.5.36–40) then cost sensitivity (1.5.41–45) classed v41 **C**. Phase 1.5.46–1.5.50 confirmed **C**. Phase 1.5.51–1.5.55 rechecked every cost candidate and XAUUSD vs XAUUSD_i identity: still **C — insufficient evidence, remain neutral**. No class-A round-trip tape; dataset `spread_pips` is an OHLC bar-range proxy; live/research `order_value` formulas disagree; no defensible cost model. v41 remains **neutral 1.0** (`docs_v2/07_ml/V41_DECISION_AUDIT.md`). Phase 1.5.56–60 audited the **live PA path** separately (`docs_v2/04_strategy/PA_LIVE_EDGE_AUDIT.md`): PA class **B** (uncosted rule-replay only); v41 was **not** activated. These ids are **not** live PA selectors.

**Verdict:** IMPLEMENTED but **DISABLED** on default production path. **Do not** infer from `data/ml/live/` that ML kernel is the current production decision engine.

## ML Shadow

| Field | Value |
|-------|-------|
| **Enable** | `ENABLE_ML_SHADOW=true` |
| **Daemon default** | true (if unset) |
| **Behavior** | Inner signal unchanged; observer logs ML comparison |
| **Order impact** | None |

**Verdict:** IMPLEMENTED AND WIRED as **SHADOW**.

## Meta-Labeler

| Field | Value |
|-------|-------|
| **Training metadata** | `models/meta_labeler_info.json` — **VERIFIED FROM FILES** |
| **Model files** | `models/meta_labeler_m5.pkl`, `m15`, `h4`, legacy `meta_labeler.pkl` — **VERIFIED FROM FILES** (E025–E027) |
| **Loadability** | Read-only audit 2026-08-22: M5/M15/H4 loaded; `is_ready_m5=True`; `is_ready=True` |
| **Historical decisions** | `data/meta_decisions.jsonl`: 4 records (2026-08-07 → 2026-08-12); 3 approved, 1 rejected — **VERIFIED FROM FILES** (E028) |
| **Gating condition** | `should_gate()` — model loaded + live win rate ≥ 35% + regime not CRISIS/VOLATILE |
| **Default M5 threshold** | 0.38 from preset / env |
| **Reject path** | `apply_pa_meta_decision` when gating and score < threshold |
| **Continuous live enforcement** | **NOT PROVEN** (historical sample only) |

**Verdict:** IMPLEMENTED AND WIRED (source code). Artifacts **VERIFIED FROM FILES**. Current-day rejection behavior **NOT PROVEN**.

## Meta Observer Mode

`META_OBSERVER_MODE=true`: logs counterfactual rejections; **never blocks**.

Default: **false** (`live.py`).

## VOL / Adaptive ML-Adjacent Engines

Computed inside router but **not selected** under PA production lock — their ML-adjacent frames do **not** drive live entries on default path.

## Historical ML-Kernel Artifacts (`data/ml/live/`)

**VERIFIED FROM FILES** — large logs exist (e.g. `decisions.jsonl`, `kernel_decisions.jsonl`, `engine_health.json`, `fallback_events.jsonl`).

| Important distinction |
|-----------------------|
| These are **historical** evidence of ML-kernel-related activity. |
| Default production path (source code): `USE_ML_KERNEL=false`, `MULTI_ENGINE_ROUTER_ENABLED=true`, `PA_PRODUCTION_LOCK=true`. |
| **Do not** claim ML kernel is the current production decision engine based on these files alone. |

## Research ML Artifacts (`data/ml/models/`)

**VERIFIED FROM FILES** — examples include `model_v1.pkl`, `best_model.pkl`, scalers, metadata.

Separate from meta-labeler path under `models/`. Research/offline; not the documented default PA-only router production path.

## Training / Refresh Scripts (Offline)

| Script | Purpose | Live impact |
|--------|---------|-------------|
| `scripts/scheduled_ml_refresh.py` | Batch ML refresh | Scheduled job — **NOT wired to live loop** |
| `start/10_retrain_meta.bat` | Meta retrain launcher | Manual/offline |
| `start/14_rebuild_ml_models.bat` | Model rebuild | Manual/offline |

**Status:** AVAILABLE offline tools; **NOT CONNECTED** to runtime loop.

## Saved Artifacts

| Path | Status (2026-08-22) |
|------|---------------------|
| `models/meta_labeler_info.json` | **VERIFIED FROM FILES** |
| `models/meta_labeler_m5.pkl` | **VERIFIED FROM FILES** |
| `models/meta_labeler_m15.pkl` | **VERIFIED FROM FILES** |
| `models/meta_labeler_h4.pkl` | **VERIFIED FROM FILES** |
| `models/meta_labeler.pkl` (legacy) | **VERIFIED FROM FILES** |
| `data/ml/models/*.pkl` | **VERIFIED FROM FILES** (research) |
| `data/ml/live/*` | **VERIFIED FROM FILES** (historical ML-kernel logs) |

## Profitability Claims

No ML profitability claim marked VERIFIED. Legacy docs and `data/ml/live/` reports are **historical/unverified** for current production behavior.

## Unknowns

- Shadow observer output volume and ML agreement metrics on operator machine
- Current-day meta rejection rate (**NOT PROVEN**)
- `ENABLE_ML_SHADOW` override in operator `.env`

## Change Impact

Env flags in `ml/integration/config.py`, `factory.py`, `meta_labeler.py`, `start_live_daemon.ps1`, runtime artifacts under `models/` and `data/ml/`

## Verification

```text
grep USE_ML_KERNEL ENABLE_ML_SHADOW in scripts/start_live_daemon.ps1
read is_ml_kernel_enabled(), is_ml_shadow_enabled()
read RiskGate meta block (~L1007+)
list models/ directory
inspect data/meta_decisions.jsonl (counts only)
```

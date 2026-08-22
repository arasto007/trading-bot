# ML Status

## Status

- **Status:** VERIFIED (code paths); runtime behavior **PARTIAL**
- **Last Verified:** 2026-08-22
- **Verification Method:** Factory flags, shadow config, meta-labeler wiring, artifact inspection
- **Verified against commit:** `57bf778c23cefffe508bb49079688b177796f67e`

## Scope

**Current operational status** of ML/AI components relative to live trading decisions.

## Summary Table

| Component | Implementation | Live decision impact | Status |
|-----------|----------------|---------------------|--------|
| ML Kernel (`USE_ML_KERNEL`) | `MLKernelRegistry` + stack | Would replace signal source | **DISABLED** |
| ML Shadow (`ENABLE_ML_SHADOW`) | `ShadowStrategyRegistry` | Log-only comparison | **SHADOW** (daemon default ON) |
| ML Live Gate | `shadow_gate.evaluate_ml_live_gate` | Blocks ML kernel only | **N/A** (ML off) |
| Meta-labeler | `MetaLabeler` in RiskGate | Can reject PA entries | **PARTIAL** |
| Meta observer mode | `META_OBSERVER_MODE` | Never rejects | **DISABLED** (default false) |
| TradeQualityEngine | VOL registry | Filters VOL signals | **N/A** (PA path) |
| XGBoost / LightGBM training | `ml/training/` | Offline research | **UNUSED** live |
| Phase research scripts | `ml/research/phase*` | None on default path | **DEAD** live |
| DQN / PPO / TFT / FinBERT | — | — | **NOT PRESENT** |

## ML Kernel

| Field | Value |
|-------|-------|
| **Enable** | `USE_ML_KERNEL=true` AND env must be explicitly set |
| **Default daemon** | `USE_ML_KERNEL=false` |
| **Gate when enabling** | `evaluate_ml_live_gate()` may downgrade to inner engine |
| **Fallback** | `ALLOW_LEGACY_FALLBACK` env (default false) |

**Verdict:** IMPLEMENTED but **DISABLED** on default production path.

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
| **Training metadata** | `models/meta_labeler_info.json` (M5/M15/H4 specs) |
| **Model files** | `models/meta_labeler_m5.pkl`, etc. — **not in workspace snapshot** |
| **Gating condition** | `should_gate()` — model loaded + live win rate ≥ 35% + regime not CRISIS/VOLATILE |
| **Default M5 threshold** | 0.38 from preset / env |
| **Reject path** | `apply_pa_meta_decision` when gating and score < threshold |

**Verdict:** IMPLEMENTED AND WIRED; enforcement **UNKNOWN** without local `.pkl` and live stats.

## Meta Observer Mode

`META_OBSERVER_MODE=true`: logs counterfactual rejections; **never blocks**.

Default: **false** (`live.py`).

## VOL / Adaptive ML-Adjacent Engines

Computed inside router but **not selected** under PA production lock — their ML-adjacent frames (atr_pct, etc.) do **not** drive live entries on default path.

## Training / Refresh Scripts (Offline)

| Script | Purpose | Live impact |
|--------|---------|-------------|
| `scripts/scheduled_ml_refresh.py` | Batch ML refresh | Scheduled job — **NOT wired to live loop** |
| `start/10_retrain_meta.bat` | Meta retrain launcher | Manual/offline |
| `start/14_rebuild_ml_models.bat` | Model rebuild | Manual/offline |

**Status:** AVAILABLE offline tools; **NOT CONNECTED** to runtime loop.

## Saved Artifacts

| Path | In repo snapshot |
|------|------------------|
| `models/meta_labeler_info.json` | YES |
| `models/*.pkl` | NO |
| `saved_models/` | Not audited file-by-file |

## Profitability Claims

No ML profitability claim marked VERIFIED. Legacy docs reference backtest JSON — treat as **historical/unverified** unless reproduced.

## Unknowns

- Shadow observer output volume and ML agreement metrics on operator machine
- Whether meta models exist locally and reject trades in practice
- `ENABLE_ML_SHADOW` override in operator `.env`

## Change Impact

Env flags in `ml/integration/config.py`, `factory.py`, `meta_labeler.py`, `start_live_daemon.ps1`

## Verification

```text
grep USE_ML_KERNEL ENABLE_ML_SHADOW in scripts/start_live_daemon.ps1
read is_ml_kernel_enabled(), is_ml_shadow_enabled()
read RiskGate meta block (~L1007+)
list models/ directory
```

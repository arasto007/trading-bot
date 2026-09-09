# ML Architecture

## Status

- **Status:** VERIFIED (structure); live wiring **PARTIAL**
- **Last Verified:** 2026-08-22
- **Verification Method:** Package inspection and factory/integration tracing
- **Verified against commit:** `57bf778c23cefffe508bb49079688b177796f67e`

## Scope

Architecture of ML/AI components **as implemented** in `tradingbot/ml/`.

## Package Layout (High Level)

| Area | Path | Purpose |
|------|------|---------|
| Integration | `ml/integration/` | Kernel bridge, factory, config |
| Decision engine | `ml/decision_engine/` | Orchestrator, policies, VOL branch |
| Phase15a engines | `ml/phase15a/` | Engine registry for ML kernel |
| Trade quality | `ml/trade_quality/` | Quality scoring (VOL path) |
| Risk intelligence | `ml/risk_intelligence/` | AdaptiveRiskEngine (ML stack) |
| Confidence mapping | `ml/confidence_mapping/` | Production calibration adapters |
| Shadow | `ml/shadow/` | Live gate, observer, metrics |
| Training | `ml/training/`, `ml/models/` | XGBoost, LightGBM, logistic factories |
| Research | `ml/research/phase*` | Offline experiments (~600+ files) |
| Features | `ml/features/` | Unified feature store, SMC features |

## ML Kernel Stack (When Enabled)

Built by `build_ml_kernel_stack()` in `factory.py`:

```text
PipelineCache (datasets)
  → EngineRegistry (phase15a)
  → DecisionOrchestrator (+ optional range recovery)
  → Production calibration adapter
  → AdaptiveRiskEngine + mapped production risk
  → TradeQualityAdapter
  → KernelAdapter → MLKernelRegistry
```

**Evidence:** `tradingbot/ml/integration/factory.py:67–125`

TradingKernel calls **`build_strategy_registry()`**, not `build_ml_kernel_stack()` directly.

## Default Live Architecture (Verified)

```text
build_strategy_registry()
  → MultiEngineRouterRegistry (PA selected)
  → wrapped by ShadowStrategyRegistry (if ENABLE_ML_SHADOW)
       → ShadowObserver.observe_cycle() [log only]
```

ML kernel path **not constructed** when `USE_ML_KERNEL=false`.

## Meta-Labeler (Separate from ML Kernel)

| Field | Value |
|-------|-------|
| **Location** | `tradingbot/services/meta_labeler.py` |
| **Consumer** | `RiskGate.evaluate()` for PA signals |
| **Models** | Per-TF pickle files under `models/` |
| **Features** | `UnifiedFeatureStore` |
| **Live impact** | Conditional gate — not full ML kernel |

**Status:** IMPLEMENTED AND WIRED to RiskGate; meta-labeler artifacts **VERIFIED FROM FILES** (see `ML_STATUS.md`); continuous live enforcement **NOT PROVEN**.

## Model Frameworks Found

| Framework | Location | Live decision path |
|-----------|----------|-------------------|
| XGBoost | `ml/models/xgboost_model.py`, training factory | **NOT on default live** |
| LightGBM | `ml/models/lightgbm_model.py` | **NOT on default live** |
| Logistic / RF | `ml/training/model_factory.py` | Research |
| Pickle meta models | `services/meta_labeler.py` | Artifacts **VERIFIED FROM FILES**; continuous enforcement **NOT PROVEN** |

## Not Found in Repository

No implementation files found for: **DQN, PPO, TFT, FinBERT, generic transformers** as live trading components.

(Grep across `tradingbot/ml` — research comments only.)

## Shadow / Gate Architecture

| Component | Role |
|-----------|------|
| `ShadowStrategyRegistry` | Wraps inner registry; observer logs cycles |
| `ShadowObserver` | Compares ML vs live signal |
| `evaluate_ml_live_gate()` | Blocks ML **kernel** activation unless metrics pass |
| Phase49a / PhaseD gates | Shadow trade statistics |

**Evidence:** `ml/shadow/shadow_gate.py`, `adapters/shadow_strategy_registry.py`

## Research Subtree

`tradingbot/ml/research/phase*` — batch scripts and analysis. **Not imported** on default live startup path. Status: **DEAD / OFFLINE** for production runtime (individual files not exhaustively proven dead).

## Root `ml/` Directory

Parallel tree to `tradingbot/ml/`. Import reachability from live path: **UNKNOWN** without full dependency scan.

## Active on Default Live

- Factory selection logic
- ML shadow observer (logging)
- Meta-labeler code path (conditional)

## Disabled on Default Live

- Full ML kernel stack
- TradeQualityEngine on entries (PA path)
- AdaptiveRiskEngine on entries
- PipelineCache warm at signal time

## Change Impact

`tradingbot/ml/integration/`, `factory.py`, `services/meta_labeler.py`, `ml/shadow/`

## Verification

Read `build_strategy_registry`, `build_ml_kernel_stack`, `ShadowStrategyRegistry`, `MetaLabeler` imports in `risk_gate.py`.

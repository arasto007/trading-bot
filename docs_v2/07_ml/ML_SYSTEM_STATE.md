# ML System State

**Status:** VERIFIED (wiring); live ML **DISABLED** on default daemon  
**Last verified:** 2026-09-01  
**Epistemic-Role:** OWNER of ML live/shadow/v41 status.  
**Operator-effective state:** UNKNOWN  
**Do not activate ML.**

| Component | Class | State |
|-----------|-------|--------|
| ML kernel (`USE_ML_KERNEL`) | INACTIVE / DEAD on default | `is_ml_kernel_enabled` false unless explicit env |
| ML live gate | N/A while kernel off | `evaluate_ml_live_gate` |
| ML shadow | SHADOW | daemon-if-unset ON; code default OFF |
| v40 | HISTORICAL / rollback | `TREND_MODEL_ID` / `TREND_ENGINE_ID` |
| v41 | RESEARCH / INACTIVE | class **C**, factor **1.0**, research-watch |
| Meta-labeler | PRODUCTION wiring | can reject; today **NOT PROVEN** |
| Training / WF / datasets | RESEARCH | `ml/training`, `ml/data` |
| `data/ml/live/` | HISTORICAL | not current PA owner |

v41 metrics stay in `V41_*.md`. **Do not copy v40 PF/factors onto v41.**

Factory still contains ML branches. They are not the default live owner.

Related: `MODEL_REGISTRY.md`, `CALIBRATION_STATE.md`, `ML_STATUS.md` (supporting).

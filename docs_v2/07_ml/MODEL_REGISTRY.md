# Model Registry

**Status:** VERIFIED (ids + checksums on disk)  
**Last verified:** 2026-09-01  
**Epistemic-Role:** OWNER of model id / checksum rows. Live activation remains ML_SYSTEM_STATE.  
**Operator-effective state:** UNKNOWN  

Do not transfer metrics between rows.

| MODEL ID | Artifact | Checksum (bundle_sha256) | Feature contract | Live | Research | Calibration |
|----------|----------|--------------------------|------------------|------|----------|-------------|
| `trend_rf_v40` | `data/ml/research/trend_rf_bundle` | `a38968041f28c20b34331bc8a037244b052ba7e19e1e783373907991fc7d0552` | that bundle `feature_order` / metadata columns | INACTIVE | rollback | v40-owned factors in `engine_calibration_factor` when engine == this id |
| `trend_rf_v41` | `data/ml/research/trend_rf_bundle_v41` | `a433fa410604b17ad195ec80469c86bca47b3df718f4072b2c5d1dc2b153eb6b` | v41 bundle only | INACTIVE | C / watch | **1.0** (not `TREND_MODEL_ID`, so calibrator returns neutral) |
| `phase9_9` | RANGE engine | n/a here | ML path | INACTIVE | historical | RANGE factors if engine matches |
| Meta `meta_labeler_m5.pkl` (+ m15/h4) | `models/` | n/a in this table | meta features | CONDITIONAL PRODUCTION | — | threshold 0.38 M5 preset |

`resolve_active_trend_engine_id()` → `trend_rf_v41` unless `TREND_MODEL_VERSION=v40`. That resolver is **unused** while the ML kernel is off.

Frozen v41 bundle must not be modified.

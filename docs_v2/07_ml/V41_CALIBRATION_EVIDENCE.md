# V41 Calibration Evidence (Phases 1.5.31–1.5.35)

**Status:** RESEARCH / EVIDENCE ONLY  
**Last verified:** 2026-08-31  
**Live impact:** none — this document does not authorize transferring v40 factors onto v41  
**Classification:** **C — insufficient evidence for calibration**

This study is offline. It does not start MT5, open the ML live gate, or change production calibrators.

---

## 1. Executive Summary

`trend_rf_v41` is a frozen Random Forest + Top5 bundle promoted in Phase 17D (2026-07-04). The artifact exists on disk and is the default **ML-path** resolver id. It is **not** the live signal owner (PA router + closed ML gate).

What exists:

- Model bundle with checksum, feature order, 3-year TREND-labeled training window.
- Train / validation / test row counts on that small window.
- AUC-only walk-forward numbers (weak; two inconsistent runs).
- Combined-stack Phase 19A simulation (v41 + phase9_9 + risk/quality). **v41 contributed 2 trades.**
- Phase 17C “PF=2.0 / WR=100% / DD=0 / MC robust” numbers. These are **invalid for calibration**: returns are `prob − 0.40`, always positive when a trade fires.

What does **not** exist:

- Isolated v41 profit-factor / win-rate / expectancy / drawdown / Sharpe on a usable trade sample.
- Isolated v41 walk-forward of **trading** metrics.
- Isolated v41 Monte Carlo of real (or even simulated R-multiple) returns.
- v41-specific validated PF / WF robustness / MC% comparable to Phase 13.10’s v40 figures (PF 1.21, WF 0.83, MC 100%).

**Decision:** do not write v41 factors into `engine_calibrator.py`, `calibration_policy.py`, or `HistoricalMetrics.engine_quality_factor`. Keep v41 **neutral (1.0)** where current code already treats non-v40 engine ids as neutral. **No v40 calibration factors were transferred.**

---

## 2. Exact v41 model source

| Item | Value | File |
|------|-------|------|
| Engine id | `trend_rf_v41` | `data/ml/research/trend_rf_bundle_v41/metadata.json` |
| Bundle dir | `data/ml/research/trend_rf_bundle_v41/` | `tradingbot/ml/phase15a/config.py` `TREND_BUNDLE_DIRS["v41"]` |
| Model class | `RandomForestClassifier` | `training_manifest.json`, `phase17b/training_lab.py` |
| Hyperparameters | `n_estimators=120`, `max_depth=6`, `min_samples_leaf=10` | same as frozen v40 (conservative copy) |
| Features | 11 base TREND ML + 5 Top5 | `feature_order.json` (16 columns) |
| Threshold | 0.4 | `config.json` |
| Rule | `evaluate_variant_a` | `config.json` |
| Seed | 42 | metadata |
| Frozen at | 2026-07-04T01:14:34Z | metadata |
| Promoted from | `phase17c_research_rf_top5` | metadata |
| Freeze code | `freeze_trend_rf_v41()` | `tradingbot/ml/phase17d/bundle_freeze.py` |
| Runtime engine | `TrendRfV41Engine` | `tradingbot/ml/phase17d/v41_engine.py` |
| Active resolver | `resolve_active_trend_engine_id()` → v41 by default | `tradingbot/ml/phase17d/versioning.py` |
| Bundle SHA256 | `a433fa410604b17ad195ec80469c86bca47b3df718f4072b2c5d1dc2b153eb6b` | `checksum.sha256` (matches Phase 18A report) |
| Model pickle | `model.pkl` (512,457 bytes) | bundle dir |
| Scaler | `scaler.pkl` | bundle dir |

On-disk artifacts (all present): `bundle.pkl`, `model.pkl`, `scaler.pkl`, `feature_order.json`, `feature_statistics.json`, `metadata.json`, `training_manifest.json`, `checksum.json`, `checksum.sha256`, `version.json`, `config.json`.

**A model file is not a calibrated engine.** Existence + promotion ≠ Phase 13.10-grade validated factors.

---

## 3. Exact datasets used

| Dataset | Path / builder | Role |
|---------|----------------|------|
| Shared ML dataset fingerprint | `70b38325ee1c7e1e` (`EXPECTED_DATASET_FINGERPRINT`) | Same fingerprint as v40 |
| v41 freeze window | last **1095 days** of candles (`DEFAULT_TRAIN_DAYS`) | `phase17b/config.py`, `bundle_freeze.py` |
| v41 labeled samples | TREND-labeled via `build_trend_dataset()` + `label_a_tp_before_sl` | `phase17b/dataset.py` |
| v41 freeze split | train 796 / val 171 / test 171 / total labeled 1138 | `metadata.json`, `training_manifest.json` |
| Phase 17B lab report (different run) | 672,614 total; 470,829 / 100,892 / 100,893 | `data/ml/reports/phase17b/dataset_report.json` |
| v40 bundle (comparison only) | `data/ml/research/trend_rf_bundle/` | 672,614 train rows, 11 features, no Top5 |
| Candle store | `data/ml` raw/processed candles (XAUUSD M5) | used by freeze / replay scripts |

**Identity mismatch:** the promoted v41 bundle was trained on **1,138 TREND-labeled rows** over ~3 years. The Phase 17B *report* describes a **672k-row** chronological split. Those are not the same trained object. Calibration must use the **bundle metadata**, not the large 17B report, as the source of truth for the frozen model.

---

## 4. Data coverage

| Field | Promoted v41 bundle | Phase 17B lab report | Phase 19A stack sim |
|-------|---------------------|----------------------|---------------------|
| Symbol | XAUUSD (research label; live symbol is `XAUUSD_i`) | XAUUSD | XAUUSD |
| Timeframe | M5 | M5 | M5 |
| Training period | 2023-09-19 → 2025-08-18 | full labeled history in dataset | n/a (replay) |
| Train window days | 1095 | not the freeze window | 365 / 730 / 1095 replay |
| Train rows | **796** | 470,829 | — |
| Sample for trading metrics | — | — | 177 combined trades; **2 TREND** |
| Stride | — | — | 5 (sparse; ~500 bars / window) |

Confidence in coverage: **medium for identity, low for trading performance.**

---

## 5. Training / validation / test separation

**Promoted bundle (`training_manifest.json`):**

- Chronological: `true`
- Scaler fit: `train_only`
- `shuffled`: `false` (bundle claim)
- Split: 796 / 171 / 171
- Time-series CV: 2 splits, mean AUC **0.5035** (≈ chance)
- Walk-forward AUC mean: **0.5563**

**Phase 17B lab report (not the freeze object):**

- Chronological split claimed; 5-fold TS CV mean AUC **0.5166**
- Acceptance hard-failed: `"dataset was shuffled"` (`acceptance_report.json`)
- `dataset_report.json` simultaneously claims `shuffled: false`

That contradiction is a **contamination / process risk**. It is not proof the freeze was shuffled, and it is not proof it was clean. It is a reason not to treat 17B/17C gates as calibration-grade.

---

## 6. Walk-forward evidence

### AUC walk-forward (exists, weak)

SOURCE: `data/ml/research/trend_rf_bundle_v41/training_manifest.json`  
CALCULATION: yearly expanding AUC on the **1,138-row** TREND-labeled freeze set  
SAMPLE SIZE: three windows (2024 test 348, 2025 test 455, 2026 test 191)  
DATE RANGE: implied by freeze window (2023-09 → 2025-08 plus 2026 test rows)  
LIMITATION: classification AUC only. No PF, WR, expectancy, or DD.

| Year | Train rows | Test rows | AUC |
|------|------------|-----------|-----|
| 2024 | 144 | 348 | 0.5140 |
| 2025 | 492 | 455 | 0.5988 |
| 2026 | 947 | 191 | 0.5562 |
| Mean | | | **0.5563** |

A second, larger AUC walk-forward lives in `data/ml/reports/phase17b/training_report.json` (years 2021–2026, mean AUC **0.5061**). That report does **not** match the freeze row counts. Do not merge the two.

### Trading-metric walk-forward

**V41_WALK_FORWARD_EVIDENCE (trading metrics) = MISSING**

Phase 17C `walk_forward.json` reports research PF=2.0, WR=1.0, DD=0.0 for every year. Those “returns” are `max(prob − 0.40, …)` in `phase17c/walk_forward.py` (`returns.append(prob - RF_THRESHOLD)`). Every accepted trade is a guaranteed positive proxy. `pf_from_returns` then returns **2.0** whenever there are only gains (`phase17c/metrics.py`).

That is **not** walk-forward validation of economic performance.

Phase 19A yearly PF (2024 1.57 / 2025 0.57 / 2026 1.71) is the **combined** PA-adjacent stack (175 RANGE + 2 TREND). It is not v41 walk-forward.

Phase 19B `walkforward_validation.json` tests **filters** on the 19A trade list, not a v41-isolated engine.

---

## 7. Monte Carlo / robustness

**V41_ISOLATED_MONTE_CARLO = MISSING**

| Artifact | What it actually is | Usable as v41 calibration? |
|----------|---------------------|----------------------------|
| `data/ml/reports/phase17c/monte_carlo.json` | 5000 bootstraps of 68 **probability-margin** proxies; PF locked at 2.0; DD 0; failure 0 | **NO** — all-positive synthetic returns |
| `data/ml/reports/phase19a/robustness.json` | 2000 sims on **combined** 177-trade R-multiple path (175 RANGE) | **NO** — not v41-isolated |
| Phase 13.10 MC 100% | Router / v40-era TREND RF | **NO** — must not be reused as v41 |

Missing for isolated v41:

- drawdown distribution of v41 trades
- losing-streak distribution
- probability of ruin on v41-only returns
- profit distribution
- trade-order randomization on a v41-only book
- dedicated v41 confidence intervals

Do **not** reuse v40 Monte Carlo (Phase 13.10 `monte_carlo_profitable_pct = 1.0`) as v41 evidence.

---

## 8. Performance metrics

### Isolated v41 trading metrics

Almost none. The only isolated economic slice is Phase 19A TREND regime:

| Metric | Value | SOURCE | CALCULATION | SAMPLE SIZE | DATE RANGE | LIMITATION |
|--------|-------|--------|-------------|-------------|------------|------------|
| Trades | 2 | `phase19a/regime_analysis.json` | regime==TREND in 3y stack replay | 2 | ~3y, stride 5 | Unusable n |
| PF | 2.0 | same | 4R profit / 0 loss | 2 | same | Two wins; no losses |
| WR | 1.0 | same | 2/2 | 2 | same | No information |
| Expectancy | 2.0 R | same | mean R | 2 | same | Fixed 2R TP sim |
| Net P/L | +4 R | same | sum R | 2 | same | Not engine-scale |
| Max DD | 0 | same | | 2 | same | No losing trade |
| Sharpe | 0.0 | same | n too small | 2 | same | Undefined |
| Sortino | 2.0 | same | | 2 | same | Not meaningful |

### Combined stack (NOT v41 calibration)

SOURCE: `data/ml/reports/phase19a/performance_summary.json`  
System: `trend_rf_v41` + `phase9_9` + calibration + risk + quality, simulation only, `order_send=false`.

| Window | Trades | PF | WR | Expectancy R | Net R | Max DD R | Sharpe | Sortino |
|--------|--------|----|----|--------------|-------|----------|--------|---------|
| 365d | 203 | 1.658 | 45.3% | 0.360 | +73 | −13 | 0.241 | 0.0 |
| 730d | 181 | 1.204 | 37.6% | 0.127 | +23 | −24 | 0.087 | 0.0 |
| 1095d | 177 | 1.161 | 36.7% | 0.102 | +18 | −29 | 0.070 | 0.0 |

LIMITATION: **175/177 of the 3y trades are RANGE (`phase9_9`)**. Wins/losses are fixed +2R / −1R from `simulate_outcome`. Sortino 0.0 is a metric defect, not a robustness finding. Capital-at-$1000 path in the same report ruins (−98%) — that is a sizing artifact, not a v41 factor.

### Invalid 17C “performance”

SOURCE: `phase17c/phase17c_final_report.json` / `walk_forward.json`  
CALCULATION: `prob − 0.40`  
SAMPLE: thousands of TREND bars / year  
LIMITATION: **Do not use.** PF=2, WR=100%, DD=0 is guaranteed by construction.

---

## 9. v40 vs v41 research comparison

| | v40 (Phase 13.10 / 15A bundle) | v41 (17D freeze + 19A) |
|--|-------------------------------|-------------------------|
| Train rows | 672,614 | 796 |
| Features | 11 | 16 (11 + Top5) |
| Validated PF | **1.2143** (router_a, 2,811 trades; 1,205 trend trades) | isolated: **n=2** |
| WF robustness | **0.8251** | AUC 0.56 only; trading WF missing |
| MC profitable | **100%** (13.10 router path) | isolated MC missing |
| Expectancy | 0.1387 (router_a) | isolated n=2 |
| Threshold | 0.4 / variant_a | 0.4 / variant_a (copied) |
| Role today | rollback / historical label `TREND_MODEL_ID` | default ML resolver id; **not live owner** |

Phase 18A shadow (501 bars): agreement 86.2%; TREND divergence 32.4%; trades 204 (v40) vs 271 (v41); `pf_delta=0.0`. That is **decision-overlap**, not a license to copy v40’s 1.21 factor onto v41.

**Do not conclude that v41 should inherit any v40 calibration factor.** Different sample size, feature set, and no isolated validated PF.

---

## 10. Leakage / contamination audit

| Risk | Evidence | Severity |
|------|----------|----------|
| 17B “shuffled” hard-fail vs later `shuffled: false` | `acceptance_report.json` vs `dataset_report.json` / bundle metadata | High process inconsistency |
| Freeze object ≠ 17B report object | 796 vs 470,829 train rows | High — wrong report can be cited |
| 17C PF/MC tautology | `prob − threshold` always > 0 | Critical if used as calibration |
| 19A attributed to v41 | 2/177 TREND trades | High mis-attribution |
| Same dataset fingerprint as v40 | `70b38325ee1c7e1e` | Medium — shared labels/features; not proof of independence |
| Hyperparameters copied from v40 | `phase17b/config.py` comment: frozen v40 HP | Medium — not leakage, but not a new fit study |
| Sparse stride-5 replay | ~500 bars / multi-year window | Medium under-sampling |
| Fixed 2:1 R simulation | `simulate_outcome` / `_duration_bars` | Medium — not live fill |
| 17B rejected, 17C/17D promoted | `REJECT_NEW_RF` then `READY_FOR_PRODUCTION_BUNDLE` | High governance inconsistency |

No evidence that this study started MT5 or wrote live orders.

---

## 11. Missing evidence

1. Isolated v41 backtest with n ≫ 2 TREND trades and real (or consistent R) P/L.
2. Isolated v41 walk-forward of PF / WR / expectancy / DD (not AUC, not `prob−θ`).
3. Isolated v41 Monte Carlo on those returns (order shuffle, DD distribution, ruin).
4. Reconciliation of the 796-row freeze vs the 470k-row 17B lab report.
5. Resolution of the 17B shuffle hard-fail.
6. Sortino / Sharpe computed on a defined bar-frequency for v41-only.
7. Regime-stable isolated v41 performance (19A TREND n=2).
8. Out-of-sample period after 2026-07-04 freeze that is not mixed with RANGE.

---

## 12. Calibration readiness

| Question | Answer |
|----------|--------|
| Is v41 a real frozen model? | YES |
| Is it the default ML resolver? | YES (`DEFAULT_ACTIVE_VERSION = v41`) |
| Does it own live signals today? | NO (gate closed, PA lock, `USE_ML_KERNEL=false`) |
| Can we set `engine_calibration_factor` for v41? | **NO** |
| Can we copy v40 PF 1.21 / WF 0.83 / MC 1.0? | **NO** |
| Current code behavior for engine=`trend_rf_v41` | **neutral 1.0** (`engine_calibrator` and `engine_quality_factor` match v40 id only) |

**Classification: C — insufficient evidence**

Not A (no calibration-grade isolated metrics).  
Not B as the primary label: AUC + 2 trades is not “partial calibration evidence,” it is identity + a stub. Residual research artifacts are recorded above so a later phase can grow them.  
Not D: the model and training metadata are real.

---

## 13. Recommended next action

A **dedicated offline v41 isolation study** (future phase), if wanted:

1. Replay TREND-only bars through `TrendRfV41Engine` (no RANGE, no live gate).
2. Record simulated R or labeled outcomes with chronological expanding windows.
3. Publish isolated PF / WR / expectancy / DD / n / date range.
4. Monte Carlo that book only.
5. Only then decide dual-key factors vs remain-neutral.

Until that exists: **leave calibrators unchanged.** v41 stays neutral. v40 factors stay v40-only.

---

## 14. Explicit non-transfer statement

**No v40 calibration factors were transferred to v41.**

Unchanged on purpose:

- `tradingbot/ml/confidence_engine/engine_calibrator.py` — `TREND_MODEL_ID = "trend_rf_v40"`
- `tradingbot/ml/confidence_engine/calibration_policy.py` — `TREND_RF_VALIDATED_PF = 1.21`, `TREND_RF_WF_ROBUSTNESS = 0.83`, `TREND_RF_MONTE_CARLO = 1.0`
- `tradingbot/ml/risk_intelligence/risk_types.py` — `engine_quality_factor` keys `trend_rf_v40` only
- `TREND_MODEL_ID` / `TREND_ENGINE_ID` remain v40 rollback / historical labels

Those v40 numbers remain Phase 13.10 empirically validated **v40** parameters (`data/ml/reports/phase13_10/final_phase13_10_report.json`). They are calibration debt relative to v41, not stale typos.

---

## Appendix A — v40 methodology (reference only)

| Piece | File |
|-------|------|
| Validated PF / WF / MC | `data/ml/reports/phase13_10/final_phase13_10_report.json` |
| WF implementation | `tradingbot/ml/research/phase13_10/walk_forward.py` |
| MC implementation | `tradingbot/ml/research/phase13_10/monte_carlo.py` |
| Factor math | `engine_calibrator.py` + `calibration_policy.py` |
| Quality factor | `HistoricalMetrics.engine_quality_factor` |

## Appendix B — confidence level

| Claim | Confidence |
|-------|------------|
| v41 bundle exists and checksum matches 18A | High |
| Freeze trained on 796/1138 TREND rows, 1095d | High |
| 17C PF/MC are not economic | High |
| 19A combined PF is RANGE-dominated | High |
| Isolated v41 is uncalibrated | High |
| v41 should remain factor-neutral | High |

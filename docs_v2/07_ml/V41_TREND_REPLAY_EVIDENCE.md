# V41 Isolated TREND Replay Evidence (Phases 1.5.36–1.5.40)

**Status:** RESEARCH / EVIDENCE ONLY  
**Last verified:** 2026-08-31  
**Live impact:** none  
**Classification:** **B — promising but requires more evidence**  
**Production factor:** v41 remains **neutral 1.0** (not written into calibrators)

This study is offline. It does not start MT5, open the ML live gate, change `PA_PRODUCTION_LOCK`, alter router defaults, RiskGate, execution, `.env`, or copy v40 calibration factors onto v41.

Machine-readable book: `data/ml/reports/phase15_36/v41_trend_performance_book.json`  
Full replay payload: `data/ml/reports/phase15_36/v41_isolated_trend_replay.json`

---

## 1. Executive conclusion

An isolated TREND-only replay of the **frozen** `trend_rf_v41` bundle now exists. It uses causal XAUUSD M5 bars, official 16-feature contract, `rule_classify_row == TREND` only, Variant A direction, threshold 0.4, ATR×1.0 SL and **1:2 RR**, and **real R-multiples** from a forward SL/TP walk.

The book is large enough to compute trading metrics (10,734 non-overlapping trades; 3,409 OOS after freeze end). The raw edge is thin:

- Combined PF **1.036**, expectancy **+0.024 R**
- OOS PF **1.050**, expectancy **+0.033 R**
- OOS max DD **−33 R**; combined max DD **−84.6 R**
- Per-trade Sharpe ≈ **0.02** (not annualized)
- Spread / slippage / commission: **not applied** (this research path has no cost model)
- Monte Carlo on real OOS R: PF p50 **1.05**, P(loss) **8.15%**, P(equity path ≤ −20 R) **100%** at the −20 R ruin threshold

That is a genuine isolated TREND book. It is **not** Phase 13.10-grade evidence (v40 validated PF 1.21 / WF 0.83 / MC 100%). Costs would likely erase a 0.03 R expectancy. **Do not** activate or write v41 factors.

**v41 remains neutral 1.0.**

---

## 2. Phase 1.5.36 — bundle / label / model integrity

Frozen object: `data/ml/research/trend_rf_bundle_v41/`  
Loader: `load_trend_bundle(version="v41")`  
Audit: `tradingbot/ml/research/v41_isolated/integrity.py`  
**Bundle files were not modified.**

| Item | Value | Proven? |
|------|-------|---------|
| Engine id | `trend_rf_v41` | `config.json`, `metadata.json` |
| Model | `RandomForestClassifier` 120 / 6 / 10, seed 42 | metadata |
| Scaler | `scaler.pkl` SHA256 `8be7a0e8…c26fdaf` | `checksum.json` |
| Model SHA256 | `13b960cf5f85085f7f5cd3984b8f5f3b7e452af2b6515bf2f7d618e1838dc6a5` | disk + `checksum.json` |
| Bundle SHA256 | `a433fa410604b17ad195ec80469c86bca47b3df718f4072b2c5d1dc2b153eb6b` | `checksum.sha256` matches recompute |
| Features / order | 16 columns (11 base + Top5), exact order in `feature_order.json` | matches replay contract |
| Threshold | 0.4 | `config.json` |
| Rule | `evaluate_variant_a` | `config.json` |
| Regime | TREND | `config.json` |
| Split | train 796 / val 171 / test 171 / labeled 1138 | `training_manifest.json` |
| Window | 2023-09-19 → 2025-08-18 (1095 days) | metadata |
| Symbol / TF documented | XAUUSD / M5 | freeze docs; live symbol is `XAUUSD_i` |
| Fingerprint | `70b38325ee1c7e1e` | same family as v40 dataset id |

### Documented inconsistencies (not silently fixed)

1. **Dual checksum files.** `trend_rf_checksum_path()` prefers `checksum.sha256` (bundle hash only). `validate_trend_checksum()` therefore reports `stored_model_sha256=None`. `checksum.json` **does** store the matching model digest. Loader left unchanged.
2. **796 ≠ 470,829.** Phase 17B lab report (`data/ml/reports/phase17b/`) is a different run. Calibration identity is the **freeze bundle**, not that report.
3. **Classification AUC ≠ trading edge.** Manifest CV AUC 0.5035 / WF-AUC 0.5563 are **A) classification metrics** only.

### Feature leakage / look-ahead

Official builders used as-is:

- `compute_trend_features` — EMA/ADX/ATR/RSI/MACD/structure via `diff` / `ewm` / `rolling` on past+current bar
- `atr_percentile` — current ATR vs prior window (`x[:-1] < x[-1]`)
- `attach_top5_features` — documented causal (diff / rolling on ≤ t)
- Replay entry at bar close; SL/TP walk starts at **next** bar; same-bar SL and TP → SL wins

No future-bar feature was introduced. Replay does **not** use `prepare_calibration_candles` (no 3,000-bar downsample).

If a residual contemporaneous-bar effect exists in HH/LL/breakout (current high/low in the rolling window), it is the same contract the frozen model was trained on — not a silent rewrite.

---

## 3. Phase 1.5.37 — isolated TREND-only replay

Code: `tradingbot/ml/research/v41_isolated/replay.py`  
Orchestrator: `tradingbot/ml/research/v41_isolated/run.py`

| Rule | Implementation |
|------|----------------|
| Frozen v41 only | `load_trend_bundle(version="v41")` |
| TREND only | `vectorized_rule_classify` ≡ `rule_classify_row`; RANGE / HIGH_VOL / NO_TRADE excluded |
| Direction | `vectorized_variant_a` ≡ `evaluate_variant_a` |
| Score | batch `predict_proba` on `feature_order`; accept if `p ≥ 0.4` |
| SL/TP | `build_trend_signal` — ATR×1.0 SL, RR 2.0 |
| P/L | forward high/low walk → R-multiple; **not** `prob − 0.40` |
| Overlap | primary book is **non-overlapping** (next entry after prior exit) |
| Data | `CandleStore().load("XAUUSD", "M5")` → `data/ml/raw/candles/m5/XAUUSD_m5.parquet` |
| Window | 2023-08-01 → 2026-07-17 (209,681 M5 bars; 1,484,071 in full store 2004-06-11 → 2026-07-17) |
| Eval start | freeze start 2023-09-19 (warmup bars before that for indicators only) |
| In-sample tag | `ts ≤ 2025-08-18` |
| OOS tag | `ts > 2025-08-18` |
| Costs | **NOT APPLIED** — this ATR SL/TP research path has no spread/slippage/commission |
| Invalid priors | Phase 17C `prob−0.40` and Phase 19A mixed RANGE+TREND 3y book were **not** used |

Market data was **not** invented. Candles were present.

---

## 4. Phase 1.5.38 — TREND-only performance book

### A) Model classification metrics (not trading)

| Metric | Value | Source |
|--------|-------|--------|
| Train / val / test rows | 796 / 171 / 171 | `training_manifest.json` |
| Time-series CV mean AUC | 0.5035 | same |
| Walk-forward mean AUC | 0.5563 | same |

**Do not treat AUC as PF, expectancy, or edge.**

### B) Trading performance (R-multiples, isolated TREND)

| Field | Combined (IS+OOS) | In-sample (≤ 2025-08-18) | OOS (> 2025-08-18) |
|-------|-------------------|--------------------------|--------------------|
| Trades | 10,734 | 7,325 | 3,409 |
| Wins | 3,665 | 2,491 | 1,174 |
| Losses | 7,069 | 4,834 | 2,235 |
| Win rate | 34.14% | 34.01% | 34.44% |
| Total R | +253.29 | +140.64 | +112.65 |
| Average R / expectancy | +0.0236 | +0.0192 | +0.0330 |
| Profit factor | 1.036 | 1.029 | 1.050 |
| Max drawdown (R) | −84.60 | −84.60 | −33.02 |
| Sharpe (mean/std, per trade) | 0.0166 | 0.0135 | 0.0232 |
| Meaningful (n≥30) | yes | yes | yes |

| Funnel | Count |
|--------|-------|
| Eval observations after freeze start | 200,015 |
| TREND observations | 118,353 |
| Non-TREND (excluded) | 81,662 |
| Variant-A BUY/SELL | 92,131 |
| Rule HOLD | 26,222 |
| Below threshold 0.4 | 45,216 |
| Overlapping accepts | 46,915 |
| Non-overlapping trades (book) | 10,734 |
| Rejected / filtered (HOLD + below + overlap skip) | 107,619 |

| Other | Value |
|-------|-------|
| Average holding time | **6.20 bars ≈ 31 minutes** (M5) |
| Trade date range | 2023-09-19 07:00Z → 2026-07-17 18:40Z |
| RR contract | 1:2 (`DEFAULT_RR` / `RR_RATIO` = 2.0) |
| Costs / slippage / spread | **NOT APPLIED** |
| Phase 17C pseudo-return | not used |
| RANGE mixed into TREND book | no |

Primary book for DD / Sharpe / PF is the **non-overlapping** series.

---

## 5. Phase 1.5.39 — walk-forward + Monte Carlo

Retraining the frozen pickle on expanding windows was **not** performed (would create a different model). What was run is a **time-ordered evaluation of the frozen v41 object** after its training end. 2024 and in-sample 2025 are **not** valid WF folds.

### Frozen-model OOS folds

| Fold | Trades | WR | Total R | Exp | PF | Max DD | Sharpe |
|------|--------|----|---------|-----|----|--------|--------|
| oos_2025 (2025-08-18 → 2025-12-31) | 1,450 | 34.28% | +39.98 | +0.0276 | 1.042 | −33.02 | 0.0194 |
| oos_2026 (2026-01-01 → 2026-07-17) | 1,959 | 34.56% | +72.67 | +0.0371 | 1.057 | −30.00 | 0.0260 |
| OOS aggregate | 3,409 | 34.44% | +112.65 | +0.0330 | 1.050 | −33.02 | 0.0232 |

Status: **OK** (each fold n≥30, no future training).

Expanding-window **retrain** WF: **not run** — would not be evidence for this frozen checksum.

### Monte Carlo (real OOS R-multiples, 2,000 paths, seed 42)

`prob − 0.40` was not used.

| Distribution | p05 | p25 | p50 | p75 | p95 |
|--------------|-----|-----|-----|-----|-----|
| Profit factor | 0.991 | 1.027 | 1.050 | 1.076 | 1.113 |
| Expectancy (R) | −0.006 | +0.018 | +0.033 | +0.049 | +0.072 |
| Max DD (R) | −118.0 | −79.0 | −63.0 | −50.3 | −38.0 |
| Terminal R | −21.0 | +60.0 | +112.0 | +168.0 | +246.6 |

| Risk | Value |
|------|-------|
| P(terminal R < 0) | 8.15% |
| P(ruin) at −20 R threshold | **1.00** |
| Sample | OOS 3,409 real R |

P(ruin)=1.0 is **meaningful as a path-length warning**, not a broker-balance model: with 3,409 trades, WR ~34%, and losers ≈ −1 R, bootstrap equity almost always touches −20 R. The −20 R threshold is severe for this sample size. It does **not** authorize a “robust” claim.

---

## 6. Phase 1.5.40 — calibration decision

Exactly one class:

**B — promising but requires more evidence**

| Class | Why not |
|-------|---------|
| A | OOS PF 1.05 < 1.20; costs missing; DD catastrophic vs 0.03 R expectancy; not Phase 13.10-comparable |
| C | Isolated TREND book, OOS n=3409, frozen-model WF, and real-R MC now **exist** |
| D | OOS PF > 1 and expectancy > 0 — does not *contradict* an edge; it is just too thin / uncosted |

**Not done even though a book exists:**

- No write to `engine_calibrator.py`, `calibration_policy.py`, `risk_types.py`
- No change to `TREND_MODEL_ID` / `TREND_ENGINE_ID`
- No factory / RiskGate / execution / live / `.env` change
- **No v40 factor copied onto v41**
- v41 **remains neutral 1.0**

---

## 7. Limitations

- Costs, spread, and slippage are **missing** on this path (`INSUFFICIENT EVIDENCE — NOT PROVEN` that the 0.03 R edge survives them).
- Sharpe is per-trade mean/std, not annualized.
- High TREND rate (118k / 200k) follows the Phase 13.2 ADX rule on gold; it is not a discretionary TREND label.
- Average hold 6.2 bars is short; same-bar SL-priority is conservative but high/low fill assumption is optimistic vs real MT5.
- Symbol in research candles is `XAUUSD`, not live `XAUUSD_i`.
- Frozen-model OOS evaluation ≠ expanding retrain walk-forward.
- In-sample 7,325 trades cannot authorize calibration by themselves.
- Phase 17C and Phase 19A remain invalid as TREND evidence (documented in `V41_CALIBRATION_EVIDENCE.md`).

---

## 8. Tests

`tests/test_v41_isolated_trend_replay.py` — bundle identity/checksum, feature contract, TREND-only, causal R, no `prob−0.40`, classification vs trading metrics, insufficient-sample WF/MC, no v40 inheritance, no live/MT5 imports.

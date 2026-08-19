# Phase 34A — Final Diagnosis

**Date:** 2026-07-30  
**Branch:** `phase34a_minimal_live_truth` — **NOT CREATED** (git not in PATH on audit machine; run locally: `git checkout -b phase34a_minimal_live_truth`)

**Evidence sources:**
- `logs/runtime_truth.json`
- `docs/adaptive_regime_live_truth_7d.md`
- `docs/minimal_live_core.mmd`
- `data/backtest_last.json` (14-day reference)

---

## 1. Is the active live engine profitable on the tested window?

**No.**

| Window | PF | Return | Trades | Source |
|--------|-----|--------|--------|--------|
| **7 days** (cached M5, last 7d of 14d parquet) | **0.0** | **-11.5%** | 5 | `adaptive_regime_live_truth_7d.md` |
| 14 days (prior run) | 0.32 | -30.14% | 13 | `data/backtest_last.json` |

All 5 trades in the 7-day window exited via **stop loss** (100% loss rate). Expectancy: **-4.60** per trade.

---

## 2. Which single gate blocks the most potentially profitable trades?

**SESSION gate** — by a wide margin.

From 7-day bar scan (1936 bars in session-eligible window after warmup):

| Stage | Block events | Share of blocks |
|-------|-------------:|----------------|
| **SESSION** | **1516** | **~71%** |
| CONFLUENCE | 412 | ~19% |
| H1_ALIGN | 114 | ~5% |
| EMA_SEP | 66 | ~3% |
| REGIME | 0 | 0% |

Session filter allows trading **only 12–17 UTC** (5 hours/day). ~78% of all M5 bars fall outside this window and never reach signal logic.

*Note: Block counts count rejection events per sub-check; one bar may emit multiple events (e.g. SESSION on wrapped MTF+VOL calls). SESSION remains the dominant bottleneck.*

---

## 3. Is `CONFLUENCE_ONLY` the primary cause of low trade frequency?

**Partially — it is the second-largest bottleneck, not the first.**

- **8 signals** generated in 7 days (~1.1/day) from 1936 scanned bars.
- **CONFLUENCE** blocked **412** evaluation paths — requires MTF trend + VOL regime to agree with ATR 30–70%.
- **SESSION** blocked **1516** paths — more than 3× confluence.

So: CONFLUENCE_ONLY **materially reduces** trade count (412 blocks), but **session window** is the primary frequency limiter. Disabling confluence alone would not fix low frequency without widening session.

---

## 4. What is the minimum change required to reach PF > 1.0 without enabling the ML kernel?

Based on evidence (not optimized — hypothesis for next phase):

| Priority | Change | Rationale |
|----------|--------|-----------|
| 1 | **Fix exit economics** | 5/5 trades hit SL; 0 TPs in 7d. RR presets (CONFLUENCE 2.0/2.0) may be too tight vs gold volatility. Test wider TP or tighter SL with same session. |
| 2 | **Disable or relax CONFLUENCE_ONLY** | Set `ADAPTIVE_CONFLUENCE_ONLY=false` to allow MTF_TREND / HIGH_VOL_MOMENTUM standalone — 412 fewer confluence blocks; more samples to tune. |
| 3 | **Widen session** | Extend beyond 12–17 UTC (e.g. 10–20 UTC) — addresses 1516 session blocks. |
| 4 | **Wire risk_factor to lot sizing** | HIGH_VOL 0.5× metadata is cosmetic; reduce loss size in volatile regimes. |

**Minimum single change to test first:** `ADAPTIVE_CONFLUENCE_ONLY=false` + re-run 7d backtest — lowest code risk, measurable via existing `tools/adaptive_regime_live_truth_7d.py`.

PF > 1.0 is **not proven achievable** with one flag change; current SL-hit rate suggests **strategy economics** must change, not just gates.

---

## 5. Which research subsystems can be completely ignored for the next optimization phase?

**Safe to ignore (no impact on ADAPTIVE_REGIME live path):**

| Subsystem | Path |
|-----------|------|
| ML kernel entire stack | `tradingbot/ml/integration/factory.py` ML branch |
| phase9_9 range engine | `ml/phase15a/engine_registry.py` |
| trend v41 / v40 | same |
| phase22c thresholds | `ml/research/phase22c/` |
| phase19c RSI/ADX filters | `ml/phase19c/filters.py` |
| WPSQF filter | default OFF |
| Meta-labeler | skipped for adaptive |
| Legacy Price Action | `LegacyStrategyRegistry` |
| Research phases 14–32 (except L2 round2) | `ml/research/phase*` |
| L2 unused hypotheses | PULLBACK_VWAP, LONDON_KZ, NY_REVERSAL, BOS_RETEST |

**Must NOT ignore:**

| Module | Why |
|--------|-----|
| `ml/research/live_l2/edge_discovery_round2.py` | Feature frame + MTF/VOL signals |
| `strategies/adaptive_regime.py` | Live router |
| `adapters/risk_gate.py` | Live gates |
| `adapters/mt5_position_manager.py` | Exits |

See `docs/research_cloud.mmd` for visual separation.

---

## Phase 34A deliverables checklist

| Item | Status |
|------|--------|
| Branch `phase34a_minimal_live_truth` | Manual — git unavailable in environment |
| `tools/runtime_truth_report.py` | Done |
| `logs/runtime_truth.json` at startup | Done — wired in `LiveRunner` |
| `config/live_runtime.env.example` | Done |
| `docs/runtime_config_diff.md` | Done |
| `docs/minimal_live_core.mmd` | Done |
| `docs/research_cloud.mmd` | Done |
| `logs/rejection_events.jsonl` instrumentation | Done |
| `docs/adaptive_regime_live_truth_7d.md` | Done |
| This diagnosis | Done |

---

## Owner quick start

1. Open **`logs/runtime_truth.json`** — see exactly what is active.
2. Open **`docs/minimal_live_core.mmd`** — see the 8-step live path.
3. After bot runs, inspect **`logs/rejection_events.jsonl`** — see why signals were blocked.
4. Re-run 7d test: `python tools/adaptive_regime_live_truth_7d.py` (MT5 optional if parquet cache exists).

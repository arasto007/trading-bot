# PA Live-Edge & Parity Audit (Phases 1.5.56–1.5.60)

**Status:** RESEARCH / OFFLINE  
**Last verified:** 2026-09-01  
**Live impact:** none  
**Artifact class:** RESEARCH-ONLY (uncosted rule replay). Not CURRENT live fills. Not a size-up.  
**Production activation:** **no**  
**v41:** remains **C / neutral 1.0 / research-watch**

This is an audit of the **current locked live Price Action path**. Parameters were not optimized. No MT5, no orders, no calibration or routing changes.

Machine-readable: `data/ml/reports/phase15_56/pa_live_edge_audit.json`.

---

## 1. Executive summary

Default live production selects **Price Action only** (`MultiEngineRouter` + `PA_PRODUCTION_LOCK`). The signal owner is `PriceActionStrategy` → `evaluate_m5_london_sweep` with M5 preset `gold_ny_sweep` (NY 15–16 UTC, Asian range 00–08 UTC).

A causal, uncosted replay of those **live rules** on research **XAUUSD M5** candles (2004-06-11 → 2026-07-17) produced 2,537 closed trades, full-sample expectancy **+0.054 R**, PF **1.083**, max DD **−60 R**. Pre-declared OOS from 2025-01-01: 151 trades, exp **+0.297 R**, PF **1.408**. That OOS is **not** broker-realistic and is **concentrated in 2026**.

Parity vs backtest/research is mostly **C (understood differences)** — especially symbol (`XAUUSD_i` vs `XAUUSD`), ~~default backtest TF **M1**~~ **backtest TF now M5 (Phase 25B; was M1)**, assumed costs, and execution model. No unexplained **D** rows.

**Not A:** no live/backtest economic identity, no class-A cost tape, thin full-sample PF, large DD.  
**Not D:** uncosted OOS expectancy is positive with n≥30.  
**B:** historical rule-replay is slightly positive; more evidence is required before any real-money increase.

v41 is unchanged: **C / 1.0**. Do not activate ML.

---

## 2. Exact PA live path (code)

```text
start_bot / live_runner / bootstrap.build_kernel_live
  → get_live_config()          # PRIMARY_SYMBOL=XAUUSD_i; router on → TIMEFRAMES=['5m']
  → factory.build_strategy_registry()
  → MultiEngineRouterRegistry  # PA_PRODUCTION_LOCK → PA only
       VOL + Adaptive generated and logged, never selected
  → LegacyStrategyRegistry.generate_signal
  → StrategyManager + PriceActionStrategy.generate_signals
  → exclude_forming_bar (closed M5)
  → enrich_price_action + evaluate_gold_setup
       → evaluate_m5_london_sweep + apply_setup_hardening
  → build_trading_signal
  → RiskGate (spread/news/Friday/positions/cooldown/ATR filters/optional meta)
  → Mt5ExecutionAdapter
```

| Hop | Class |
|-----|--------|
| PA signal / router / RiskGate / MT5 execution | **LIVE** |
| VOL + Adaptive inner registries | **SHADOW** (probed, not selected) |
| ML shadow wrap | **SHADOW** |
| ML kernel / v41 calibrators / M15–H4 PA / scalp–H4 gold modes | **DEAD/UNUSED** on default path |
| `BacktestEngine` | **BACKTEST** |
| phase14 / setup_quality scripts | **RESEARCH** |

---

## 3. PA strategy specification (live M5)

| Item | Value |
|------|--------|
| Owner | `engine/strategies/price_action_strategy.py::PriceActionStrategy.generate_signals` |
| Implementation | `domain/gold_strategies/m5_london_sweep.py::evaluate_m5_london_sweep` |
| Preset | `gold_ny_sweep` / `GOLD_STRATEGY_MODE=london_sweep` |
| Symbol | Live `XAUUSD_i`; preset key `XAUUSD` |
| Timeframe | **M5 only** when router is on |
| Indicators | ATR(14) true range mean; Asian high/low; 12-bar sweep + 0.12 ATR buffer; BOS/FVG flags for quality |
| Entry | Closed bar; UTC 15≤h<16; sweep Asian extreme then close back inside; MIN_CONFIDENCE 0.52; quality ≥55; CHoCH off; rejection candle off |
| SL | Sweep extreme ± 0.35 ATR |
| TP | max(opposite Asian bound, 1.5R) |
| Session | NY 15–16; Asian 00–08 UTC; kill zones off |
| Sizing | RiskGate lot from live equity and SL distance |
| Risk | Cooldown 18 bars; max 3/day; max 3 total / 2 per symbol; market filters in RiskGate; HTF M5 not required; meta 0.38 if gating |
| Execution | Live MT5 fill + tick spread (999 pips if tick missing → reject) |

---

## 4. Live / backtest / research parity matrix

Classes: **A** identical · **B** materially equivalent · **C** different but understood · **D** unexplained.

| Item | Class | Notes |
|------|-------|--------|
| Signal function | B | Same sweep function if factory defaults; research often skips wrappers |
| ATR | C | Some research uses (H−L) rolling mean |
| Forming bar | C | Live drops last MT5 row; backtest bars already closed |
| Look-ahead | C | Full-frame `find_swings(..., right=3)` is not live-safe |
| OHLC source | C | MT5 `XAUUSD_i` vs cache vs `XAUUSD_m5.parquet` |
| Symbol | C | Identity unproven (1.5.52) |
| Timeframe | B | **BacktestConfig default M5** (Phase 25B; aligned with live M5; was M1 pre-25B) |
| Spread | C | Live tick vs backtest 2.5/0.8 vs research 0 |
| SL/TP formula | B | Same if same preset |
| Entry timing | C | Close vs simulated fill vs first-touch |
| Exit / PM | C | Backtest trailing/partial/zscore defaults vs live M5 partial TP off |
| Session | B | Same preset; demo session bypass exists |
| Confirmation bars | A | 0 |
| Sizing | C | Live equity vs $1000 sim vs R-only |
| Rounding / tick | C | `order_value` XAUUSD vs XAUUSD_i |
| Execution | C | MT5 vs SimulatedBroker vs bar H/L |
| Missing data | C | Live spread fail-closed 999 |
| RiskGate vs BacktestRiskGate | C | Meta + MT5 account only on live |
| Meta | C | Wired; continuous live enforcement NOT PROVEN |

**D count: 0.** Divergences were not silently fixed.

---

## 5. PA historical edge (uncosted research replay of live rules)

Replay uses frozen live M5 preset. Fill = signal-bar close. Same-bar SL+TP → SL. One position at a time. No spread, commission, meta, news, or live equity. Research symbol **XAUUSD**, not `XAUUSD_i`.

Asian-range prefilter is vectorized (groupby day hours 0–8) then **`evaluate_gold_setup` is the official accept**. Equivalent to live while NY starts after Asian end.

| Book | n | WR | Exp (R) | PF | Max DD (R) | Sharpe | Longest L |
|------|---|----|---------|----|------------|--------|-----------|
| Full | 2537 | 34.65% | +0.054 | 1.083 | −60.1 | 0.032 | 17 |
| In-sample (<2025) | 2386 | 35.12% | +0.039 | 1.060 | −60.1 | 0.025 | 17 |
| OOS (≥2025-01-01) | 151 | 27.15% | +0.297 | 1.408 | −19.5 | 0.090 | 16 |

Direction (full): BUY 1193, exp +0.021, PF 1.033; SELL 1344, exp +0.084, PF 1.127.  
Session: all entries **NY** (by construction).  
Hold: 1–3 bars **−0.62 R**; 4–12 **−0.17 R**; 13–36 **+0.26 R**; 37+ **+0.40 R** — descriptive only, not a new filter.

Yearly expectancy changes sign often (e.g. 2017 −0.20, 2022 −0.15, 2024 −0.12, 2008 +0.31, 2026 +0.80). Full-sample edge is **thin** relative to a 0.04 R cost (v41-style sensitivity): +0.054 would not survive that cost if it applied.

---

## 6. OOS evidence quality

The 2025-01-01 cut was **declared before metrics** (calendar holdout, not a fitted walk-forward).

It is **not** a trustworthy isolated production OOS:

- Costs are **zero by construction**
- Symbol is not the live broker symbol
- OOS total R is **dominated by 2026** (+37.7 R / 47 trades) vs 2025 (+7.2 R / 104 trades, PF 1.09)
- Live closed PA round-trips in the journal are **not** this book

Treat OOS as **WEAK / research-only**.

---

## 7–8. Live-failure root causes (ranked)

Repository evidence only. Nothing invented.

| Sev | Finding |
|-----|---------|
| HIGH | XAUUSD vs XAUUSD_i identity unproven |
| HIGH | No class-A round-trip cost tape (17 entry slips only) |
| HIGH | ~~Backtest default TF M1 ≠ live M5~~ **RESOLVED (Phase 25B):** BacktestConfig default M5 = live M5 |
| HIGH | Bar/sim fill ≠ Mt5ExecutionAdapter |
| HIGH | n=17 live fills cannot prove live PA expectancy |
| MEDIUM | Backtest PM defaults (trailing/partial/zscore) vs live M5 |
| MEDIUM | Meta can reject PA; continuous gating NOT PROVEN |
| MEDIUM | Missing tick → spread 999 → reject |
| MEDIUM | Full-frame research enrich look-ahead |
| MEDIUM | Some scripts use ATR proxy |
| MEDIUM | DEMO_DISABLE_SESSION_FILTER can bypass NY window |
| LOW | In-memory PA dedup lost on restart |
| UNKNOWN | Partial fills / rejection rates (phase20c count=0) |
| UNKNOWN | Latency as proven PnL cause |
| UNKNOWN | Position-state bugs as proven cause |

Historical “strong backtest / weak live” is **consistent with** C-class parity (TF, symbol, costs, execution) plus missing live tape. That is **not** proof those items caused any specific live loss.

---

## 9. Final classification

PA classification: **B — promising but requires more evidence.** Artifact class remains RESEARCH-ONLY (uncosted replay), not CURRENT live fills.

1. Further validation of **this frozen rule set**: yes (evidence collection, not retuning).  
2. Paper/shadow of **this PA path**: yes, offline or operator-run; this agent must not start the bot.  
3. Production activation / size-up: **no**.  
4. Missing before real-money increase: `XAUUSD_i` bid/ask + commission; identity proof; cost-aware replay; live PA round-trip journal n≫30; backtests forced to M5 + live preset.  
5. v41 remains research-watch / **neutral 1.0**.  
6. Continue **PA as the locked live path**; do **not** switch live to ML. Next work is tape/parity evidence, not a new optimizer. v41 stays C.

---

## 10. v41 status

Unchanged: **C — insufficient evidence**, calibration **1.0**, not production-active.

---

## Safety

MT5 / bot / orders / `.env` / ML gate / v41 / PA lock / router / RiskGate / execution / Adaptive / `PIPELINE_TIMEOUT_MS`: **not changed**. No commit.

**Recommended next phase:** **STOP.** Do not auto-start 1.5.61. If an operator later provides an offline `XAUUSD_i` cost tape, a new ingest phase may cost-adjust this frozen PA book.

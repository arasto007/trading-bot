# Phase 28.3 — Monte Carlo Robustness

**Status:** PASS_WITH_DEFERRAL
**Class:** RESEARCH ONLY
**Conclusion:** `INSUFFICIENT_SAMPLE`
**Live trading authorized:** NO
**Parameters optimized:** NO
**Costs:** MODELED / not realized
**FINAL_GATE:** `BLOCKED`

Monte Carlo on **stored Phase 28.1/28.2 trade-level results only**. No new strategy walk. No optimization. No OHLC rewalk.

STOP AFTER PHASE 28.3. DO NOT START PHASE 28.4.

---

## Baseline

| Item | Value |
|---|---|
| Dataset fingerprint | `ab3e25bab0c6d6689d6654317264cc7774e1b49f88df907a3ea1bd1ade313ed5` |
| RAW trades | 24 |
| EXECUTABLE fills | 0 |
| Observed final R | -21.5000 |
| Observed expectancy R | -0.8958 |
| Observed PF | 0.0652 |
| Observed WR | 0.0417 |
| Observed max DD R | 22.0000 |
| Observed longest losing streak | 22 |
| Seed | `283003` |
| Paths | 2000 |

Fingerprint matches Phase 28.0/28.1/28.2. Canonical parquet was not rewritten.

---

## Sequence resampling (stored RAW R)

Shuffle permutes the 24 observed R values. Bootstrap resamples them with replacement. Neither invents new trades.

| Metric | median | p5 | p25 | p75 | p95 |
|---|---:|---:|---:|---:|---:|
| Shuffle final R | -21.5000 | -21.5000 | -21.5000 | -21.5000 | -21.5000 |
| Shuffle max DD R | 21.5000 | 21.5000 | 21.5000 | 21.5000 | 23.0000 |
| Bootstrap final R | -21.5000 | -24.0000 | -24.0000 | -19.0000 | -16.5000 |
| Bootstrap max DD R | 21.5000 | 17.0000 | 20.5000 | 24.0000 | 24.0000 |

| Path set | P(DD≥10R) | P(DD≥20R) | P(final R < 0) | losing-streak median / p95 |
|---|---:|---:|---:|---|
| Shuffle | 1.0000 | 1.0000 | 1.0000 | 18 / 23 |
| Bootstrap | 1.0000 | 0.7735 | 1.0000 | 19 / 24 |

Ruin / large-DD here is **descriptive R-space only**: P(max DD ≥ 10R) and P(max DD ≥ 20R). Not a broker-margin ruin model. Not realized.

Shuffle expectancy / PF / WR are invariant because the trade set is unchanged. Bootstrap bands:

| Metric | median | p5 | p95 |
|---|---:|---:|---:|
| Expectancy R | -0.8958 | -1.0000 | -0.6875 |
| PF | 0.0652 | 0.0000 | 0.2143 |
| Win rate | 0.0417 | 0.0000 | 0.1250 |

---

## MODELED perturbations

These are **not** historical realized costs. `BacktestConfig.spread_pips=2.5 and slippage_pips=0.8 are assumptions. Phase 27.30: 0 genuine requested-vs-fill pairs. Do not treat as realized costs.`

Assumptions (labeled MODELED / MODELED_PROXY): spread `2.5` pips, slippage `0.8` pips, pip size `0.1`. Entry is shifted on stored SL/TP/outcome; OHLC is not rewalked.

| Shock | expectancy R | PF | WR | max DD R | final R |
|---|---:|---:|---:|---:|---:|
| Observed (no shock) | -0.8958 | 0.0652 | 0.0417 | 22.0000 | -21.5000 |
| Entry spread adverse MODELED | -0.8960 | 0.0650 | 0.0417 | 22.0000 | -21.5052 |
| Entry ± spread MODELED | -0.8956 | 0.0654 | 0.0417 | 22.0000 | -21.4948 |
| Slippage adverse MODELED | -0.8960 | 0.0651 | 0.0417 | 22.0000 | -21.5033 |
| Spread + slippage adverse MODELED | -0.8962 | 0.0648 | 0.0417 | 22.0000 | -21.5085 |

MODELED haircuts move expectancy / PF by a few thousandths of an R. They do not change the sample-size problem.

---

## EXECUTABLE

n=0. Monte Carlo is not defined on an empty executable book. 0 fills is not proof of no edge.

---

## Robustness

**INSUFFICIENT_SAMPLE**

24 theoretical baseline trades cannot support ROBUST / CONDITIONALLY_ROBUST / FRAGILE. Executable n=0 cannot be Monte-Carlo'd. Descriptive MC paths are not a robustness proof.

Descriptive paths look uniformly negative (bootstrap p95 final R still `-16.5000`). That is not enough trades to label the strategy FRAGILE.

---

## Conclusion

INSUFFICIENT_SAMPLE. The baseline RAW book has 24 theoretical trades and 0 executable fills. Shuffle/bootstrap and MODELED spread/slippage shocks are descriptive only. They are not historical realized costs and do not prove robustness or fragility. No parameters were optimized. FINAL_GATE remains BLOCKED. Phase 28.4 was not started.

## Safety

No MT5, no `.env`, no parquet rewrite, no strategy/RiskGate/ML/parameter changes. Phase 28.4 was **not** started.

Artifacts: `logs/phase28_3_monte_carlo.json`, `docs_v2/02_research/PHASE28_3_MONTE_CARLO.md`, `tradingbot/backtest/phase28_3_monte_carlo.py`, `tests/test_phase28_3_monte_carlo.py`

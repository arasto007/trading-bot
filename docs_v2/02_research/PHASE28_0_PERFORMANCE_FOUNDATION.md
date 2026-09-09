# Phase 28.0 — Performance Foundation

**Status:** PASS_WITH_DEFERRAL
**Class:** RESEARCH ONLY
**Live trading authorized:** NO
**FINAL_GATE:** `BLOCKED`
**EV-EQ-01:** `NOT_PROVEN`
**Cost completeness:** `BLOCKED`

This phase stops broker-evidence auditing and starts **performance validation** of GoldenEdge Price Action / `gold_ny_sweep` using only defensible `XAUUSD_i` data.

It does **not** authorize live trading. It does **not** satisfy `COMPLETE_COSTS_REQUIRED`. It does **not** prove or disprove edge when the sample is short. Zero executable trades is **not** proof the strategy has no edge.

STOP AFTER PHASE 28.0. DO NOT START PHASE 28.1.

---

## Best dataset

| Field | Value |
|---|---|
| Path | `data/XAUUSD_i_5m.parquet` |
| Symbol | `XAUUSD_i` |
| Timeframe | `M5` |
| Rows | `3000` |
| Range | `2026-08-13 20:20:00+00:00 → 2026-08-28 17:25:00+00:00` |
| Timezone | `UTC` |
| Fingerprint | `ab3e25bab0c6d6689d6654317264cc7774e1b49f88df907a3ea1bd1ade313ed5` |
| Fingerprint match | `True` |
| Bid/Ask | `PROXY_OHLC_ONLY` |
| Spread | `PROXY` |
| Provenance | `XAUUSD_i label match; OBSERVED_BROKER_EVIDENCE economics; spread PROXY; EV-EQ-01 NOT_PROVEN for bare XAUUSD` |
| Sidecar env | `DEMO` |
| Eligibility | `ELIGIBLE_ENTRY` |

Logical `XAUUSD` datasets are **BLOCKED** (`MISSING_EXPLICIT_MAP`). No silent `XAUUSD`→`XAUUSD_i` map was inserted. Phase 26 19-candidate / 0-allowed trace used `data/backtest/XAUUSD_M5_183d.parquet` (blocked here) and must not be reused as the 28.0 baseline.

H4 context file `data/XAUUSD_i_4h.parquet` is ELIGIBLE_CONTEXT when present. No canonical `XAUUSD_i` M15 parquet was found.

---

## Canonical quality

| Check | Result |
|---|---|
| Duplicate timestamps | `0` |
| Malformed OHLC | `0` |
| Impossible candles | `0` |
| Zero volume | `0` |
| Negative volume | `0` |
| Gap count | `11` |
| Weekend/session gaps | `11` |
| Weekday unexpected gaps | `0` |

Production parquet was **not** overwritten.

---

## Research configuration (unchanged strategy)

- Symbol: `XAUUSD_i` (empty `dataset_symbol_map`)
- Entry: M5 `gold_ny_sweep` / `london_sweep`
- Context: H4 bias where file exists; M15 missing
- NY 15–16 UTC; Asian end 08:00
- `MIN_CONFIDENCE=0.52`, `MIN_QUALITY_SCORE=55`, `MIN_RR`/`TP_RR=1.5`, `SL_ATR_MULT=0.35`
- `COOLDOWN_BARS=18`, `MAX_TRADES_PER_DAY=3`
- `REQUIRE_HTF_ALIGNMENT_M5=False`
- Risk per trade `0.005`
- RiskGate unchanged; meta-labeler on; commission `UNKNOWN` (fail-closed, not ZERO)
- No parameter optimization

Fingerprint: `30bb5fb668632073`

---

## Lookahead / entry timing

Official signal is generated on the last closed M5 bar after exclude_forming_bar. A synthetic forming bar is appended only to match the live/backtest window shape, then dropped, so its OHLC is not used for features or signal generation. Entry price is PriceActionStrategy setup.entry on that closed bar. Theoretical SL/TP evaluation starts at the next bar. Same-bar SL is taken before TP, matching SimulatedBroker.check_exits.

- Official signals use **closed bars only**
- Features do not include future candle data
- Signal generation does not use future high/low
- Exits may use future bars **after** entry
- Forming bar is appended then excluded (`simulate_forming_bar` + `exclude_forming_bar`)

---

## A) SIGNAL EDGE (before RiskGate)

| Metric | Value |
|---|---|
| Setups | `24` |
| BUY | `16` |
| SELL | `8` |
| Wins | `1` |
| Losses | `23` |
| Open at end | `0` |
| Win rate | `0.041667` |
| Expectancy R | `-0.895833` |
| Profit factor | `0.065217` |
| Max drawdown R | `22.0` |
| Consecutive losses | `22` |
| Trade frequency | `1.613069` |

These are theoretical SL/TP outcomes on subsequent bars. They are **not** cost-adjusted and **not** executable.

---

## B) EXECUTABLE EDGE (current RiskGate)

| Metric | Value |
|---|---|
| Candidates | `24` |
| Allowed | `0` |
| Rejected | `24` |
| Rejection reasons | `{"ATR percentile too high (100>95)": 4, "meta-labeler rejected (p=0.04)": 3, "meta-labeler rejected (p=0.06)": 1, "meta-labeler rejected (p=0.01)": 3, "meta-labeler rejected (p=0.03)": 2, "meta-labeler rejected (p=0.02)": 2, "meta-labeler rejected (p=0.10)": 2, "meta-labeler rejected (p=0.09)": 2, "meta-labeler rejected (p=0.23)": 1, "meta-labeler rejected (p=0.30)": 1, "meta-labeler rejected (p=0.12)": 1, "ATR percentile too high (100>96)": 1, "ATR percentile too high (99>95)": 1}` |
| Executed simulated trades | `0` |
| Expectancy R | `None` |
| PF | `None` |
| DD | `None` |

Gates were **not** changed to produce trades. `SimulatedBroker refuses commission UNKNOWN. Default BacktestConfig.commission_status is UNKNOWN (not ZERO). Allowed RiskGate trades still do not become fills in this research config. Do not interpret 0 fills as proof of no strategy edge.`

---

## Statistical sufficiency

**DATA_INSUFFICIENT**

Reasons: resolved_trades=24<30, calendar_days=14.9<60

Do not invent confidence. A ~15-day canonical tape cannot support a strategy-edge claim.

---

## Determinism

`{'signal_scan_repeated': True, 'setups_fingerprint_match': True, 'fingerprint': 'd16a1f14b2fb44a14ffa8e44b24c8267e7ade0888095d9dda33eabe3cca529d2'}`

---

## Conclusion

DATA_INSUFFICIENT. The defensible XAUUSD_i M5 tape is too short for a statistical edge claim. Signal-edge metrics on this window are descriptive only. Zero RiskGate-allowed / zero SimulatedBroker fills is not proof the strategy has no edge. EV-EQ-01 remains NOT_PROVEN. Cost completeness remains BLOCKED. This research does not authorize live trading or Phase 28.1.

---

## Safety

- No MT5, no live orders, no bot/daemon, no `.env`
- No production dataset modification
- No RiskGate / strategy / sizing / RR / ML changes
- No silent XAUUSD→XAUUSD_i dataset mapping
- `FINAL_GATE` remains BLOCKED
- Phase 28.1 was **not** started

Artifacts:

- `logs/phase28_0_performance_dataset_manifest.json`
- `logs/phase28_0_baseline_performance.json`
- `docs_v2/02_research/PHASE28_0_PERFORMANCE_FOUNDATION.md`
- `tradingbot/backtest/phase28_0_performance_foundation.py`
- `tests/test_phase28_0_performance_foundation.py`

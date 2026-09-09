# Phase 28.1 — Chronological Full Baseline

**Status:** PASS_WITH_DEFERRAL
**Class:** RESEARCH ONLY
**Live trading authorized:** NO
**FINAL_GATE:** `BLOCKED`
**EV-EQ-01:** `NOT_PROVEN`
**Monte Carlo:** NO
**Parameters optimized:** NO

Chronological historical baseline of the **unchanged** GoldenEdge `gold_ny_sweep` strategy on the Phase 28.0 approved `XAUUSD_i` M5 dataset.

STOP AFTER PHASE 28.1. DO NOT START PHASE 28.2.

---

## Dataset

| Field | Value |
|---|---|
| Path | `data/XAUUSD_i_5m.parquet` |
| Fingerprint | `ab3e25bab0c6d6689d6654317264cc7774e1b49f88df907a3ea1bd1ade313ed5` |
| Matches Phase 28.0 | `True` |
| Period | `2026-08-13 20:20:00+00:00 → 2026-08-28 17:25:00+00:00` |
| Rows | `3000` |
| Timezone | UTC |
| dataset_symbol_map | `{}` |
| Silent XAUUSD mapping | `False` |
| Chunking | `NOT_REQUIRED` |

Logical `XAUUSD` tapes were not used. H4 context: `data/XAUUSD_i_4h.parquet`.

---

## Lookahead

Closed bars only. Forming bar appended then excluded. No future high/low in signal generation. Exits may use bars after entry. SL before TP on the same exit bar.

---

## RAW_SIGNAL

| Metric | Value |
|---|---|
| Setups | `24` |
| BUY / SELL | `16 / 8` |
| Trades (resolved) | `24` |
| Wins / losses | `1 / 23` |
| Win rate | `0.041667` |
| Average R / expectancy R | `-0.895833 / -0.895833` |
| PF | `0.065217` |
| Gross profit R / gross loss R | `1.5 / 23.0` |
| Max DD R | `22.0` |
| Avg duration (minutes) | `805.625` |
| Trades/calendar day | `1.613069` |
| Trades/NY session | `2.4` |
| Consecutive wins / losses | `1 / 22` |

Monthly: `{"2026-08": 24}`
Weekly: `{"2026-W34": 4, "2026-W35": 20}`

Independent theoretical outcomes. Not cost-adjusted. Overlapping NY setups overstate concurrent exposure.

---

## EXECUTABLE_RISKGATE

| Metric | Value |
|---|---|
| Candidates | `24` |
| Allowed | `0` |
| Rejected | `24` |
| Simulated fills | `0` |
| Win rate / expectancy / PF / DD | `None / None / None / None` |

Gates were **not** changed.

---

## RAW vs EXECUTABLE

- **population:** RAW 24 strategy setups on closed NY bars — EXECUTABLE 24 RiskGate candidates; 0 allowed; 0 fills — RAW_SIGNAL stops before RiskGate. EXECUTABLE is RiskGate then SimulatedBroker.
- **session filter:** RAW 120 NY bars eligible for generate_signals — EXECUTABLE SESSION bucket counts RiskGate session/friday rejects only (0 if strategy already filtered) — NY 15-16 UTC is applied in PriceActionStrategy, not as a RiskGate first-line bucket.
- **overlapping exposure:** RAW every setup is an independent theoretical trade — EXECUTABLE max positions / cooldown / daily cap would bind only after an allowed fill — Live RiskGate occupancy is not part of raw theoretical R.
- **blocking gates:** RAW no LOT/META/ATR/SPREAD/NEWS/COOLDOWN — EXECUTABLE {"ATR": 6, "COOLDOWN": 0, "LOT": 0, "META": 18, "NEWS": 0, "OTHER": 0, "SESSION": 0, "SPREAD": 0} — Gates were not changed. META and ATR are configured live behavior.
- **costs / fills:** RAW theoretical SL/TP R, no spread/commission/slippage — EXECUTABLE commission UNKNOWN fail-closes SimulatedBroker even if RiskGate allows — COMPLETE_COSTS_REQUIRED still BLOCKED; ZERO commission is not assumed.
- **0 executable trades:** RAW resolved=24 — EXECUTABLE 0 allowed, 0 fills — Do not interpret 0 executable trades as proof the strategy has no edge.

---

## RiskGate attribution

| Bucket | Count |
|---|---|
| LOT | `0` |
| META | `18` |
| ATR | `6` |
| SPREAD | `0` |
| NEWS | `0` |
| SESSION (RiskGate) | `0` |
| COOLDOWN | `0` |
| OTHER | `0` |

Strategy session funnel (not RiskGate): `{'warmup': 300, 'bars_after_warmup': 2700, 'bars_outside_ny_session': 2580, 'bars_in_ny_session': 120, 'ny_session_days': 10, 'ny_window': '15-16 UTC', 'session_filter_owner': 'PriceActionStrategy.generate_signals (not RiskGate)'}`.

---

## Statistical sufficiency

**DATA_INSUFFICIENT**

DATA_INSUFFICIENT. The approved XAUUSD_i M5 range is still ~15 days. Chronological RAW_SIGNAL metrics are descriptive only. 0 RiskGate-allowed / 0 SimulatedBroker fills is not proof of no edge. Gates and parameters were not changed. No Monte Carlo. EV-EQ-01 remains NOT_PROVEN. FINAL_GATE remains BLOCKED. This research does not authorize live trading or Phase 28.2.

---

## Safety

- No MT5, no live orders, no `.env`, no parquet rewrite
- No strategy / RiskGate / sizing / RR / ML / parameter changes
- No Monte Carlo
- Phase 28.2 was **not** started

Artifacts: `logs/phase28_1_full_baseline.json`, `docs_v2/02_research/PHASE28_1_FULL_BASELINE.md`, `tradingbot/backtest/phase28_1_full_baseline.py`, `tests/test_phase28_1_full_baseline.py`

# Phase 28.2 — Chronological Walk-Forward

**Status:** PASS_WITH_DEFERRAL
**Class:** RESEARCH ONLY
**Live trading authorized:** NO
**Parameters optimized:** NO
**TRAIN/VALIDATION:** descriptive only — not used to fit or select parameters
**FINAL_GATE:** `BLOCKED`
**Stability:** `INSUFFICIENT_SAMPLE`

Identical unchanged `gold_ny_sweep` / RiskGate on the Phase 28.0/28.1 approved `XAUUSD_i` M5 tape, split **60% TRAIN / 20% VALIDATION / 20% OOS** by chronological bar index.

STOP AFTER PHASE 28.2. DO NOT START PHASE 28.3.

---

## Dataset and splits

Fingerprint `ab3e25bab0c6d6689d6654317264cc7774e1b49f88df907a3ea1bd1ade313ed5` matches Phase 28.0/28.1. Empty `dataset_symbol_map`. Logical `XAUUSD` not used.

{
  "method": "chronological_bar_index",
  "fractions": {
    "TRAIN": 0.6,
    "VALIDATION": 0.2,
    "OOS": 0.2
  },
  "folds": {
    "TRAIN": {
      "start_index": 0,
      "end_index": 1800,
      "bars": 1800,
      "start": "2026-08-13 20:20:00+00:00",
      "end": "2026-08-24 09:25:00+00:00",
      "calendar_days": 10.5451,
      "ny_session_days": 6,
      "role": "descriptive_only"
    },
    "VALIDATION": {
      "start_index": 1800,
      "end_index": 2400,
      "bars": 600,
      "start": "2026-08-24 09:30:00+00:00",
      "end": "2026-08-26 13:25:00+00:00",
      "calendar_days": 2.1632,
      "ny_session_days": 2,
      "role": "descriptive_only"
    },
    "OOS": {
      "start_index": 2400,
      "end_index": 3000,
      "bars": 600,
      "start": "2026-08-26 13:30:00+00:00",
      "end": "2026-08-28 17:25:00+00:00",
      "calendar_days": 2.1632,
      "ny_session_days": 3,
      "role": "held_out_descriptive"
    }
  },
  "assignment": "entry_bar_index",
  "exits_may_cross_fold_boundary": true,
  "later_fold_uses_earlier_closed_bars_as_context": true
}

Later folds may use earlier bars as closed-bar context. That is past data, not lookahead. A setup is assigned by **entry** bar. Theoretical exits may occur after the fold boundary.

---

## RAW_SIGNAL

| Fold | setups | trades | BUY/SELL | WR | exp R | PF | DD | freq/day |
|---|---:|---:|---|---:|---:|---:|---:|---:|
| TRAIN | 4 | 4 | 0/4 | 0.0 | -1.0 | 0.0 | 4.0 | 0.379323 |
| VALIDATION | 10 | 10 | 7/3 | 0.0 | -1.0 | 0.0 | 10.0 | 4.622781 |
| OOS | 10 | 10 | 9/1 | 0.1 | -0.75 | 0.166667 | 8.0 | 4.622781 |

Session / BUY-SELL:

```
{
  "TRAIN": {
    "by_hour_utc": {
      "15": 4
    },
    "by_weekday": {
      "Thursday": 4
    },
    "BUY": 0,
    "SELL": 4,
    "buy_share": 0.0,
    "sell_share": 1.0
  },
  "VALIDATION": {
    "by_hour_utc": {
      "15": 10
    },
    "by_weekday": {
      "Monday": 3,
      "Tuesday": 7
    },
    "BUY": 7,
    "SELL": 3,
    "buy_share": 0.7,
    "sell_share": 0.3
  },
  "OOS": {
    "by_hour_utc": {
      "15": 10
    },
    "by_weekday": {
      "Thursday": 8,
      "Friday": 2
    },
    "BUY": 9,
    "SELL": 1,
    "buy_share": 0.9,
    "sell_share": 0.1
  }
}
```

---

## EXECUTABLE_RISKGATE

| Fold | setups | trades | BUY/SELL | WR | exp R | PF | DD | freq/day |
|---|---:|---:|---|---:|---:|---:|---:|---:|
| TRAIN | 0 | 0 | 0/0 | None | None | None | None | 0.0 |
| VALIDATION | 0 | 0 | 0/0 | None | None | None | None | 0.0 |
| OOS | 0 | 0 | 0/0 | None | None | None | None | 0.0 |

Allowed / rejected by fold: `{"TRAIN": {"allowed": 0, "rejected": 4, "attribution": {"ATR": 4}}, "VALIDATION": {"allowed": 0, "rejected": 10, "attribution": {"META": 10}}, "OOS": {"allowed": 0, "rejected": 10, "attribution": {"META": 8, "ATR": 2}}}`

Gates were not changed. Commission remains UNKNOWN.

---

## Degradation (RAW, descriptive)

- TRAIN→VALIDATION: `{"total_trades": {"from": 4, "to": 10, "abs": 6.0, "pct": 1.5}, "win_rate": {"from": 0.0, "to": 0.0, "abs": 0.0, "pct": null}, "expectancy_R": {"from": -1.0, "to": -1.0, "abs": 0.0, "pct": 0.0}, "profit_factor": {"from": 0.0, "to": 0.0, "abs": 0.0, "pct": null}, "max_drawdown_R": {"from": 4.0, "to": 10.0, "abs": 6.0, "pct": 1.5}, "trades_per_calendar_day": {"from": 0.379323, "to": 4.622781, "abs": 4.243458, "pct": 11.186925}}`
- VALIDATION→OOS: `{"total_trades": {"from": 10, "to": 10, "abs": 0.0, "pct": 0.0}, "win_rate": {"from": 0.0, "to": 0.1, "abs": 0.1, "pct": null}, "expectancy_R": {"from": -1.0, "to": -0.75, "abs": 0.25, "pct": 0.25}, "profit_factor": {"from": 0.0, "to": 0.166667, "abs": 0.166667, "pct": null}, "max_drawdown_R": {"from": 10.0, "to": 8.0, "abs": -2.0, "pct": -0.2}, "trades_per_calendar_day": {"from": 4.622781, "to": 4.622781, "abs": 0.0, "pct": 0.0}}`
- TRAIN→OOS: `{"total_trades": {"from": 4, "to": 10, "abs": 6.0, "pct": 1.5}, "win_rate": {"from": 0.0, "to": 0.1, "abs": 0.1, "pct": null}, "expectancy_R": {"from": -1.0, "to": -0.75, "abs": 0.25, "pct": 0.25}, "profit_factor": {"from": 0.0, "to": 0.166667, "abs": 0.166667, "pct": null}, "max_drawdown_R": {"from": 4.0, "to": 8.0, "abs": 4.0, "pct": 1.0}, "trades_per_calendar_day": {"from": 0.379323, "to": 4.622781, "abs": 4.243458, "pct": 11.186925}}`

These deltas are **not** an optimization signal.

---

## Stability

**INSUFFICIENT_SAMPLE**

TRAIN/VALIDATION/OOS are too small for a stability claim. Descriptive degradation numbers are not a walk-forward proof.

---

## Lookahead

Closed bars only. No future candle data in features or signal generation. Exits may use bars after entry.

---

## Conclusion

INSUFFICIENT_SAMPLE. Chronological 60/20/20 on the approved ~15-day XAUUSD_i tape cannot support a stability, degradation, or edge claim. TRAIN/VALIDATION were not used to optimize. Strategy and RiskGate were unchanged. 0 executable trades in a fold is not proof of no edge. EV-EQ-01 remains NOT_PROVEN. FINAL_GATE remains BLOCKED. This research does not authorize live trading or Phase 28.3.

## Safety

No MT5, no `.env`, no parquet rewrite, no strategy/RiskGate/parameter changes, no Monte Carlo. Phase 28.3 was **not** started.

Artifacts: `logs/phase28_2_walk_forward.json`, `docs_v2/02_research/PHASE28_2_WALK_FORWARD.md`, `tradingbot/backtest/phase28_2_walk_forward.py`, `tests/test_phase28_2_walk_forward.py`

# Phase 32 — Chronological Walk-Forward & Out-of-Sample

**Status:** PASS_WITH_DEFERRAL
**Class:** RESEARCH ONLY
**Conclusion:** `INSUFFICIENT_SAMPLE`
**Live trading authorized:** NO
**Parameters optimized / searched:** NO
**Strategy/RiskGate/ML changed:** NO
**FINAL_GATE:** `BLOCKED`

STOP AFTER PHASE 32. DO NOT START PHASE 33.

The question is whether the **unchanged** `gold_ny_sweep` is qualitatively consistent across
unseen chronological periods. This is **not** parameter optimization. TRAIN/VALIDATION are descriptive.

---

## Data

Canonical Phase 29 / Phase 28 M5: `data/XAUUSD_i_5m.parquet`.  
Fingerprint `ab3e25bab0c6d6689d6654317264cc7774e1b49f88df907a3ea1bd1ade313ed5`. Logical `XAUUSD` not used.

## Folds

Chronological bar-index 60/20/20, identical to Phase 28.2. No random split. No shuffle.
OOS starts after VALIDATION; VALIDATION starts after TRAIN. No fold was dropped.

| Fold | bars | days | sessions | events | setups | WR | exp R | PF | DD | streak | /day | event exp | event WR | exe allowed |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| TRAIN | 1800 | 10.5451 | 6 | 1 | 4 | 0.0 | -1.0 | 0.0 | 4.0 | 4 | 0.379323 | -1.0 | 0.0 | 0 |
| VALIDATION | 600 | 2.1632 | 2 | 2 | 10 | 0.0 | -1.0 | 0.0 | 10.0 | 10 | 4.622781 | -1.0 | 0.0 | 0 |
| OOS | 600 | 2.1632 | 3 | 3 | 10 | 0.1 | -0.75 | 0.166667 | 8.0 | 8 | 4.622781 | -0.166667 | 0.333333 | 0 |

Rolling WINDOW 1/2/3: **not produced** — tape `14.88` days < 60. Length gate applied before inspecting fold P/L.

## Stability

Stability is not defined as profitability alone.

{
  "direction_consistency": {
    "buy_share_by_fold": {
      "TRAIN": 0.0,
      "VALIDATION": 0.7,
      "OOS": 0.9
    },
    "consistent": false,
    "note": "TRAIN is 100% SELL; later folds are BUY-heavy. Descriptive only."
  },
  "expectancy_sign_consistency": {
    "signs": {
      "TRAIN": -1,
      "VALIDATION": -1,
      "OOS": -1
    },
    "consistent": true
  },
  "pf_consistency": {
    "pf_by_fold": {
      "TRAIN": 0.0,
      "VALIDATION": 0.0,
      "OOS": 0.166667
    },
    "all_below_one": true
  },
  "drawdown_stability": {
    "dd_by_fold": {
      "TRAIN": 4.0,
      "VALIDATION": 10.0,
      "OOS": 8.0
    },
    "note": "Fold DDs are not comparable while samples are insufficient."
  },
  "event_concentration": {
    "signals_per_event_by_fold": {
      "TRAIN": 4.0,
      "VALIDATION": 5.0,
      "OOS": 3.3333333333333335
    },
    "high_dependence_context": true
  },
  "trade_frequency_stability": {
    "trades_per_day_by_fold": {
      "TRAIN": 0.379323,
      "VALIDATION": 4.622781,
      "OOS": 4.622781
    },
    "stable": false,
    "note": "TRAIN ~0.4/day vs VALIDATION/OOS ~4.6/day on a 15-day tape."
  },
  "profitability_is_not_the_only_stability_definition": true,
  "phase28_2_sample_gate": {
    "classification": "INSUFFICIENT_SAMPLE",
    "fold_trade_counts": {
      "TRAIN": 4,
      "VALIDATION": 10,
      "OOS": 10
    },
    "min_fold_trades_required": 10,
    "min_total_trades_required": 30,
    "confidence_invented": false,
    "note": "TRAIN/VALIDATION/OOS are too small for a stability claim. Descriptive degradation numbers are not a walk-forward proof."
  },
  "classification": "INSUFFICIENT_SAMPLE"
}

## Data sufficiency

Every primary fold is `FOLD_INSUFFICIENT` under Phase 28.0/28.2 floors.

{
  "tape_calendar_days": 14.8785,
  "min_fold_trades": 10,
  "min_fold_events": 10,
  "min_total_trades": 30,
  "min_calendar_days": 60,
  "folds": {
    "TRAIN": {
      "classification": "FOLD_INSUFFICIENT",
      "criteria": {
        "signals": {
          "value": 4,
          "required": 10,
          "pass": false
        },
        "events": {
          "value": 1,
          "required": 10,
          "pass": false
        },
        "calendar_days": {
          "value": 10.5451,
          "required": 60,
          "pass": false
        }
      },
      "reasons": [
        "signals",
        "events",
        "calendar_days"
      ],
      "thresholds_source": "MIN_FOLD_TRADES=10 and MIN_TOTAL_TRADES=30 from Phase 28.2; MIN_FOLD_EVENTS uses the same 10-count independence floor; MIN_CALENDAR_DAYS_FOR_SUFFICIENCY=60 from Phase 28.0 applied per fold. Not invented this phase."
    },
    "VALIDATION": {
      "classification": "FOLD_INSUFFICIENT",
      "criteria": {
        "signals": {
          "value": 10,
          "required": 10,
          "pass": true
        },
        "events": {
          "value": 2,
          "required": 10,
          "pass": false
        },
        "calendar_days": {
          "value": 2.1632,
          "required": 60,
          "pass": false
        }
      },
      "reasons": [
        "events",
        "calendar_days"
      ],
      "thresholds_source": "MIN_FOLD_TRADES=10 and MIN_TOTAL_TRADES=30 from Phase 28.2; MIN_FOLD_EVENTS uses the same 10-count independence floor; MIN_CALENDAR_DAYS_FOR_SUFFICIENCY=60 from Phase 28.0 applied per fold. Not invented this phase."
    },
    "OOS": {
      "classification": "FOLD_INSUFFICIENT",
      "criteria": {
        "signals": {
          "value": 10,
          "required": 10,
          "pass": true
        },
        "events": {
          "value": 3,
          "required": 10,
          "pass": false
        },
        "calendar_days": {
          "value": 2.1632,
          "required": 60,
          "pass": false
        }
      },
      "reasons": [
        "events",
        "calendar_days"
      ],
      "thresholds_source": "MIN_FOLD_TRADES=10 and MIN_TOTAL_TRADES=30 from Phase 28.2; MIN_FOLD_EVENTS uses the same 10-count independence floor; MIN_CALENDAR_DAYS_FOR_SUFFICIENCY=60 from Phase 28.0 applied per fold. Not invented this phase."
    }
  },
  "any_fold_insufficient": true,
  "classification": "DATA_INSUFFICIENT",
  "confidence_invented": false
}

## Lookahead

Signals assigned by official Phase 28.2 **entry** bar. Later folds may use earlier closed bars as context. Exits may cross a fold boundary. Future never used to form a past signal.

## CONCLUSION

**INSUFFICIENT_SAMPLE**

INSUFFICIENT_SAMPLE. The unchanged gold_ny_sweep 60/20/20 walk-forward on the Phase 29 canonical XAUUSD_i tape has TRAIN=4 / VALIDATION=10 / OOS=10 signals and 1 / 2 / 3 mechanical events. Phase 28.2 requires >= 10 signals per fold and >= 30 total; Phase 28.0 requires >= 60 calendar days (tape ~15; VAL/OOS ~2). Rolling windows were not produced (tape shorter than that day floor). Descriptive fold numbers are not a generalization proof. 0 executable allows is not a strategy failure. No fold was dropped.

## Safety

No MT5 trading, no `.env`, no parquet rewrite, no strategy/RiskGate/ML/parameter changes. Phase 33 was **not** started.

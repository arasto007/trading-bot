# Phase 27.27 — Dataset Provenance & Explicit Symbol Binding Closure

**Status:** PASS  
**Artifact:** `logs/phase27_27_dataset_symbol_binding.json`  
**Timestamp UTC:** `2026-09-07T18:10:32Z`

## Policy

| Decision | Value |
|---|---|
| Canonical gold symbol | `XAUUSD_i` |
| Logical XAUUSD datasets | `ONLY_WITH_EXPLICIT_DATASET_MAP` |
| EV-EQ-01 | **NOT_PROVEN** |

An explicit `dataset_symbol_map` is an auditable alias rule. It does **not** prove `XAUUSD` ≡ `XAUUSD_i`.
Decision 2 authorizes the mechanism. It does not populate filename-only aliases.
`XAUUSD` → `XAUUSD_i` remains a **proposed** binding only.

## Totals

| Metric | Count |
|---|---|
| total relevant datasets | `37` |
| DIRECT_CANONICAL_MATCH | `6` |
| EXPLICIT_MAPPED | `0` |
| MISSING_EXPLICIT_MAP | `30` |
| INVALID_MAP | `0` |
| UNKNOWN_PROVENANCE | `1` |
| allowed | `6` |
| blocked | `31` |

Maps inserted: **False**. Default `BacktestConfig.dataset_symbol_map`: `{}`.

## Binding matrix

| Dataset | Logical Symbol | Broker Symbol | Binding State | Explicit Map | Provenance | Status |
|---------|----------------|---------------|---------------|--------------|------------|--------|
| `_phase26b_replay_tail.parquet` | `UNKNOWN` | `None` | `UNKNOWN_PROVENANCE` | `False` | `UNKNOWN` | `BLOCKED` |
| `XAUUSD_H4.parquet` | `XAUUSD` | `None` | `MISSING_EXPLICIT_MAP` | `False` | `UNKNOWN` | `BLOCKED` |
| `XAUUSD_H4_14d.parquet` | `XAUUSD` | `None` | `MISSING_EXPLICIT_MAP` | `False` | `UNKNOWN` | `BLOCKED` |
| `XAUUSD_H4_14d_off14d.parquet` | `XAUUSD` | `None` | `MISSING_EXPLICIT_MAP` | `False` | `UNKNOWN` | `BLOCKED` |
| `XAUUSD_H4_21d.parquet` | `XAUUSD` | `None` | `MISSING_EXPLICIT_MAP` | `False` | `UNKNOWN` | `BLOCKED` |
| `XAUUSD_H4_30d.parquet` | `XAUUSD` | `None` | `MISSING_EXPLICIT_MAP` | `False` | `UNKNOWN` | `BLOCKED` |
| `XAUUSD_H4_5d.parquet` | `XAUUSD` | `None` | `MISSING_EXPLICIT_MAP` | `False` | `UNKNOWN` | `BLOCKED` |
| `XAUUSD_H4_7d.parquet` | `XAUUSD` | `None` | `MISSING_EXPLICIT_MAP` | `False` | `UNKNOWN` | `BLOCKED` |
| `XAUUSD_M5_14d.parquet` | `XAUUSD` | `None` | `MISSING_EXPLICIT_MAP` | `False` | `UNKNOWN` | `BLOCKED` |
| `XAUUSD_M5_14d_off14d.parquet` | `XAUUSD` | `None` | `MISSING_EXPLICIT_MAP` | `False` | `UNKNOWN` | `BLOCKED` |
| `XAUUSD_M5_180d.parquet` | `XAUUSD` | `None` | `MISSING_EXPLICIT_MAP` | `False` | `UNKNOWN` | `BLOCKED` |
| `XAUUSD_M5_183d.parquet` | `XAUUSD` | `None` | `MISSING_EXPLICIT_MAP` | `False` | `UNKNOWN` | `BLOCKED` |
| `XAUUSD_M5_21d.parquet` | `XAUUSD` | `None` | `MISSING_EXPLICIT_MAP` | `False` | `UNKNOWN` | `BLOCKED` |
| `XAUUSD_M5_30d.parquet` | `XAUUSD` | `None` | `MISSING_EXPLICIT_MAP` | `False` | `UNKNOWN` | `BLOCKED` |
| `XAUUSD_M5_33d.parquet` | `XAUUSD` | `None` | `MISSING_EXPLICIT_MAP` | `False` | `UNKNOWN` | `BLOCKED` |
| `XAUUSD_M5_35d.parquet` | `XAUUSD` | `None` | `MISSING_EXPLICIT_MAP` | `False` | `UNKNOWN` | `BLOCKED` |
| `XAUUSD_M5_5d.parquet` | `XAUUSD` | `None` | `MISSING_EXPLICIT_MAP` | `False` | `UNKNOWN` | `BLOCKED` |
| `XAUUSD_M5_63d.parquet` | `XAUUSD` | `None` | `MISSING_EXPLICIT_MAP` | `False` | `UNKNOWN` | `BLOCKED` |
| `XAUUSD_M5_65d.parquet` | `XAUUSD` | `None` | `MISSING_EXPLICIT_MAP` | `False` | `UNKNOWN` | `BLOCKED` |
| `XAUUSD_M5_70d.parquet` | `XAUUSD` | `None` | `MISSING_EXPLICIT_MAP` | `False` | `UNKNOWN` | `BLOCKED` |
| `XAUUSD_M5_93d.parquet` | `XAUUSD` | `None` | `MISSING_EXPLICIT_MAP` | `False` | `UNKNOWN` | `BLOCKED` |
| `XAUUSD_M5_95d.parquet` | `XAUUSD` | `None` | `MISSING_EXPLICIT_MAP` | `False` | `UNKNOWN` | `BLOCKED` |
| `XAUUSD_M5_180d.parquet` | `XAUUSD` | `None` | `MISSING_EXPLICIT_MAP` | `False` | `UNKNOWN` | `BLOCKED` |
| `XAUUSD_M5_30d.parquet` | `XAUUSD` | `None` | `MISSING_EXPLICIT_MAP` | `False` | `UNKNOWN` | `BLOCKED` |
| `XAUUSD_M5_60d.parquet` | `XAUUSD` | `None` | `MISSING_EXPLICIT_MAP` | `False` | `UNKNOWN` | `BLOCKED` |
| `XAUUSD_M5_90d.parquet` | `XAUUSD` | `None` | `MISSING_EXPLICIT_MAP` | `False` | `UNKNOWN` | `BLOCKED` |
| `XAUUSD_15m.parquet` | `XAUUSD` | `None` | `MISSING_EXPLICIT_MAP` | `False` | `UNKNOWN` | `BLOCKED` |
| `XAUUSD_1d.parquet` | `XAUUSD` | `None` | `MISSING_EXPLICIT_MAP` | `False` | `UNKNOWN` | `BLOCKED` |
| `XAUUSD_1h.parquet` | `XAUUSD` | `None` | `MISSING_EXPLICIT_MAP` | `False` | `UNKNOWN` | `BLOCKED` |
| `XAUUSD_4h.parquet` | `XAUUSD` | `None` | `MISSING_EXPLICIT_MAP` | `False` | `UNKNOWN` | `BLOCKED` |
| `XAUUSD_5m.parquet` | `XAUUSD` | `None` | `MISSING_EXPLICIT_MAP` | `False` | `UNKNOWN` | `BLOCKED` |
| `XAUUSD_i_4h.parquet` | `XAUUSD_i` | `XAUUSD_i` | `DIRECT_CANONICAL_MATCH` | `False` | `OBSERVED_BROKER_EVIDENCE` | `ALLOWED` |
| `XAUUSD_i_5m.parquet` | `XAUUSD_i` | `XAUUSD_i` | `DIRECT_CANONICAL_MATCH` | `False` | `OBSERVED_BROKER_EVIDENCE` | `ALLOWED` |
| `XAUUSD_i_5m_phase38.parquet` | `XAUUSD_i` | `XAUUSD_i` | `DIRECT_CANONICAL_MATCH` | `False` | `UNKNOWN` | `ALLOWED` |
| `XAUUSD_i_m15_phase38.parquet` | `XAUUSD_i` | `XAUUSD_i` | `DIRECT_CANONICAL_MATCH` | `False` | `UNKNOWN` | `ALLOWED` |
| `XAUUSD_i_m1_phase38.parquet` | `XAUUSD_i` | `XAUUSD_i` | `DIRECT_CANONICAL_MATCH` | `False` | `UNKNOWN` | `ALLOWED` |
| `XAUUSD_i_ticks_phase38.parquet` | `XAUUSD_i` | `XAUUSD_i` | `DIRECT_CANONICAL_MATCH` | `False` | `UNKNOWN` | `ALLOWED` |

## Blocked datasets

| path | logical | current binding | required mapping | reason |
|---|---|---|---|---|
| `C:\Users\AMIR\Desktop\TradingBot new\data\backtest\_phase26b_replay_tail.parquet` | `UNKNOWN` | `None` | `None` | dataset symbol is empty |
| `C:\Users\AMIR\Desktop\TradingBot new\data\backtest\XAUUSD_H4.parquet` | `XAUUSD` | `None` | `{'XAUUSD': 'XAUUSD_i'}` | logical XAUUSD without explicit dataset_symbol_map; XAUUSD -> XAUUSD_i is proposed only and not proven |
| `C:\Users\AMIR\Desktop\TradingBot new\data\backtest\XAUUSD_H4_14d.parquet` | `XAUUSD` | `None` | `{'XAUUSD': 'XAUUSD_i'}` | logical XAUUSD without explicit dataset_symbol_map; XAUUSD -> XAUUSD_i is proposed only and not proven |
| `C:\Users\AMIR\Desktop\TradingBot new\data\backtest\XAUUSD_H4_14d_off14d.parquet` | `XAUUSD` | `None` | `{'XAUUSD': 'XAUUSD_i'}` | logical XAUUSD without explicit dataset_symbol_map; XAUUSD -> XAUUSD_i is proposed only and not proven |
| `C:\Users\AMIR\Desktop\TradingBot new\data\backtest\XAUUSD_H4_21d.parquet` | `XAUUSD` | `None` | `{'XAUUSD': 'XAUUSD_i'}` | logical XAUUSD without explicit dataset_symbol_map; XAUUSD -> XAUUSD_i is proposed only and not proven |
| `C:\Users\AMIR\Desktop\TradingBot new\data\backtest\XAUUSD_H4_30d.parquet` | `XAUUSD` | `None` | `{'XAUUSD': 'XAUUSD_i'}` | logical XAUUSD without explicit dataset_symbol_map; XAUUSD -> XAUUSD_i is proposed only and not proven |
| `C:\Users\AMIR\Desktop\TradingBot new\data\backtest\XAUUSD_H4_5d.parquet` | `XAUUSD` | `None` | `{'XAUUSD': 'XAUUSD_i'}` | logical XAUUSD without explicit dataset_symbol_map; XAUUSD -> XAUUSD_i is proposed only and not proven |
| `C:\Users\AMIR\Desktop\TradingBot new\data\backtest\XAUUSD_H4_7d.parquet` | `XAUUSD` | `None` | `{'XAUUSD': 'XAUUSD_i'}` | logical XAUUSD without explicit dataset_symbol_map; XAUUSD -> XAUUSD_i is proposed only and not proven |
| `C:\Users\AMIR\Desktop\TradingBot new\data\backtest\XAUUSD_M5_14d.parquet` | `XAUUSD` | `None` | `{'XAUUSD': 'XAUUSD_i'}` | logical XAUUSD without explicit dataset_symbol_map; XAUUSD -> XAUUSD_i is proposed only and not proven |
| `C:\Users\AMIR\Desktop\TradingBot new\data\backtest\XAUUSD_M5_14d_off14d.parquet` | `XAUUSD` | `None` | `{'XAUUSD': 'XAUUSD_i'}` | logical XAUUSD without explicit dataset_symbol_map; XAUUSD -> XAUUSD_i is proposed only and not proven |
| `C:\Users\AMIR\Desktop\TradingBot new\data\backtest\XAUUSD_M5_180d.parquet` | `XAUUSD` | `None` | `{'XAUUSD': 'XAUUSD_i'}` | logical XAUUSD without explicit dataset_symbol_map; XAUUSD -> XAUUSD_i is proposed only and not proven |
| `C:\Users\AMIR\Desktop\TradingBot new\data\backtest\XAUUSD_M5_183d.parquet` | `XAUUSD` | `None` | `{'XAUUSD': 'XAUUSD_i'}` | logical XAUUSD without explicit dataset_symbol_map; XAUUSD -> XAUUSD_i is proposed only and not proven |
| `C:\Users\AMIR\Desktop\TradingBot new\data\backtest\XAUUSD_M5_21d.parquet` | `XAUUSD` | `None` | `{'XAUUSD': 'XAUUSD_i'}` | logical XAUUSD without explicit dataset_symbol_map; XAUUSD -> XAUUSD_i is proposed only and not proven |
| `C:\Users\AMIR\Desktop\TradingBot new\data\backtest\XAUUSD_M5_30d.parquet` | `XAUUSD` | `None` | `{'XAUUSD': 'XAUUSD_i'}` | logical XAUUSD without explicit dataset_symbol_map; XAUUSD -> XAUUSD_i is proposed only and not proven |
| `C:\Users\AMIR\Desktop\TradingBot new\data\backtest\XAUUSD_M5_33d.parquet` | `XAUUSD` | `None` | `{'XAUUSD': 'XAUUSD_i'}` | logical XAUUSD without explicit dataset_symbol_map; XAUUSD -> XAUUSD_i is proposed only and not proven |
| `C:\Users\AMIR\Desktop\TradingBot new\data\backtest\XAUUSD_M5_35d.parquet` | `XAUUSD` | `None` | `{'XAUUSD': 'XAUUSD_i'}` | logical XAUUSD without explicit dataset_symbol_map; XAUUSD -> XAUUSD_i is proposed only and not proven |
| `C:\Users\AMIR\Desktop\TradingBot new\data\backtest\XAUUSD_M5_5d.parquet` | `XAUUSD` | `None` | `{'XAUUSD': 'XAUUSD_i'}` | logical XAUUSD without explicit dataset_symbol_map; XAUUSD -> XAUUSD_i is proposed only and not proven |
| `C:\Users\AMIR\Desktop\TradingBot new\data\backtest\XAUUSD_M5_63d.parquet` | `XAUUSD` | `None` | `{'XAUUSD': 'XAUUSD_i'}` | logical XAUUSD without explicit dataset_symbol_map; XAUUSD -> XAUUSD_i is proposed only and not proven |
| `C:\Users\AMIR\Desktop\TradingBot new\data\backtest\XAUUSD_M5_65d.parquet` | `XAUUSD` | `None` | `{'XAUUSD': 'XAUUSD_i'}` | logical XAUUSD without explicit dataset_symbol_map; XAUUSD -> XAUUSD_i is proposed only and not proven |
| `C:\Users\AMIR\Desktop\TradingBot new\data\backtest\XAUUSD_M5_70d.parquet` | `XAUUSD` | `None` | `{'XAUUSD': 'XAUUSD_i'}` | logical XAUUSD without explicit dataset_symbol_map; XAUUSD -> XAUUSD_i is proposed only and not proven |
| `C:\Users\AMIR\Desktop\TradingBot new\data\backtest\XAUUSD_M5_93d.parquet` | `XAUUSD` | `None` | `{'XAUUSD': 'XAUUSD_i'}` | logical XAUUSD without explicit dataset_symbol_map; XAUUSD -> XAUUSD_i is proposed only and not proven |
| `C:\Users\AMIR\Desktop\TradingBot new\data\backtest\XAUUSD_M5_95d.parquet` | `XAUUSD` | `None` | `{'XAUUSD': 'XAUUSD_i'}` | logical XAUUSD without explicit dataset_symbol_map; XAUUSD -> XAUUSD_i is proposed only and not proven |
| `C:\Users\AMIR\Desktop\TradingBot new\data\cache\XAUUSD_M5_180d.parquet` | `XAUUSD` | `None` | `{'XAUUSD': 'XAUUSD_i'}` | logical XAUUSD without explicit dataset_symbol_map; XAUUSD -> XAUUSD_i is proposed only and not proven |
| `C:\Users\AMIR\Desktop\TradingBot new\data\cache\XAUUSD_M5_30d.parquet` | `XAUUSD` | `None` | `{'XAUUSD': 'XAUUSD_i'}` | logical XAUUSD without explicit dataset_symbol_map; XAUUSD -> XAUUSD_i is proposed only and not proven |
| `C:\Users\AMIR\Desktop\TradingBot new\data\cache\XAUUSD_M5_60d.parquet` | `XAUUSD` | `None` | `{'XAUUSD': 'XAUUSD_i'}` | logical XAUUSD without explicit dataset_symbol_map; XAUUSD -> XAUUSD_i is proposed only and not proven |
| `C:\Users\AMIR\Desktop\TradingBot new\data\cache\XAUUSD_M5_90d.parquet` | `XAUUSD` | `None` | `{'XAUUSD': 'XAUUSD_i'}` | logical XAUUSD without explicit dataset_symbol_map; XAUUSD -> XAUUSD_i is proposed only and not proven |
| `C:\Users\AMIR\Desktop\TradingBot new\data\XAUUSD_15m.parquet` | `XAUUSD` | `None` | `{'XAUUSD': 'XAUUSD_i'}` | logical XAUUSD without explicit dataset_symbol_map; XAUUSD -> XAUUSD_i is proposed only and not proven |
| `C:\Users\AMIR\Desktop\TradingBot new\data\XAUUSD_1d.parquet` | `XAUUSD` | `None` | `{'XAUUSD': 'XAUUSD_i'}` | logical XAUUSD without explicit dataset_symbol_map; XAUUSD -> XAUUSD_i is proposed only and not proven |
| `C:\Users\AMIR\Desktop\TradingBot new\data\XAUUSD_1h.parquet` | `XAUUSD` | `None` | `{'XAUUSD': 'XAUUSD_i'}` | logical XAUUSD without explicit dataset_symbol_map; XAUUSD -> XAUUSD_i is proposed only and not proven |
| `C:\Users\AMIR\Desktop\TradingBot new\data\XAUUSD_4h.parquet` | `XAUUSD` | `None` | `{'XAUUSD': 'XAUUSD_i'}` | logical XAUUSD without explicit dataset_symbol_map; XAUUSD -> XAUUSD_i is proposed only and not proven |
| `C:\Users\AMIR\Desktop\TradingBot new\data\XAUUSD_5m.parquet` | `XAUUSD` | `None` | `{'XAUUSD': 'XAUUSD_i'}` | logical XAUUSD without explicit dataset_symbol_map; XAUUSD -> XAUUSD_i is proposed only and not proven |

## Resolver audit

Dataset bind is `resolve_broker_symbol_for_dataset`. Missing or invalid maps fail closed (`SYMBOL_MISMATCH` / `INVALID_MAP`).
Silent `XAUUSD` → `XAUUSD_i` conversion is **not** possible on the dataset path.

`tradingbot.adapters.symbols.resolve_broker_symbol` remains the live/environment helper and is **not** a dataset bind. RiskGate / execution were not changed.

## Immutability

Canonical parquet changed: `False`.  
Fingerprints preserved: `True`.  
Sidecars rewritten: `False`.

## FINAL_GATE

dataset_binding_before: `BLOCKED (30 logical XAUUSD MISSING_EXPLICIT_MAP / INSUFFICIENT_PROVENANCE)`  
dataset_binding_after: `BLOCKED`  
COMPLETE_COSTS_REQUIRED remains enforced. FINAL_GATE remains `BLOCKED`.

## Next

STOP after Phase 27.27.

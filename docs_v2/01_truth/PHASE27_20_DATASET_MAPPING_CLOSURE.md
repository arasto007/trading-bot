# Phase 27.20 — Explicit Dataset Symbol Map Closure

**Status:** PASS  
**Artifact:** `logs/phase27_20_dataset_mapping_closure.json`

## Policy

**ONLY_WITH_EXPLICIT_DATASET_MAP.** Canonical broker symbol = `XAUUSD_i`.

Never silently convert `XAUUSD` → `XAUUSD_i`. A filename containing `XAUUSD` is not a mapping. An empty `dataset_symbol_map` is not a relationship. EV-EQ-01 remains **NOT_PROVEN**.

## Existing configuration location

The repository already has an explicit map convention. No new convention was invented.

| Location | Role | Default |
|---|---|---|
| `tradingbot/backtest/config.py::BacktestConfig.dataset_symbol_map` | runtime/backtest map | `{}` |
| `{parquet}.metadata.json::dataset_symbol_map` | per-dataset sidecar map | `{}` |

`tradingbot.adapters.symbols.resolve_broker_symbol` is the live/environment helper and is **not** a dataset bind. Economics lookup occurs only after `resolve_broker_symbol_for_dataset`.

## Classification

| Category | Count | Action |
|---|---|---|
| `DEFENSIBLE_MAPPING_CANDIDATE` | `0` | PROPOSED map only; not inserted |
| `INSUFFICIENT_PROVENANCE` | `30` | **BLOCKED** — operator authorization required |
| `ALREADY_CANONICAL_XAUUSD_i` | `12` | unchanged MATCH |
| `OTHER/UNKNOWN` | `1` | no XAUUSD map |

Logical `XAUUSD` datasets: `30`. Maps inserted: **False**. Datasets requiring explicit operator authorization: **30**.

Decision 2 authorizes the *mechanism* (`dataset_symbol_map` → `XAUUSD_i`). It does not populate thirty filename-only aliases.

## Dataset report

| dataset | logical_symbol | proposed_broker_symbol | mapping_status | provenance | economics_status | cost_status | reason |
|---|---|---|---|---|---|---|---|
| `_phase26b_replay_tail.parquet` | `UNKNOWN` | `None` | `UNKNOWN_SYMBOL` | `UNKNOWN` | `UNKNOWN` | `UNKNOWN` | not a logical XAUUSD / XAUUSD_i dataset |
| `XAUUSD_H4.parquet` | `XAUUSD` | `None` | `BLOCKED` | `UNKNOWN` | `UNKNOWN` | `PARTIAL` | logical XAUUSD from filename/sidecar label only; broker/server/source insufficient; not mapped |
| `XAUUSD_H4_14d.parquet` | `XAUUSD` | `None` | `BLOCKED` | `UNKNOWN` | `UNKNOWN` | `PARTIAL` | logical XAUUSD from filename/sidecar label only; broker/server/source insufficient; not mapped |
| `XAUUSD_H4_14d_off14d.parquet` | `XAUUSD` | `None` | `BLOCKED` | `UNKNOWN` | `UNKNOWN` | `PARTIAL` | logical XAUUSD from filename/sidecar label only; broker/server/source insufficient; not mapped |
| `XAUUSD_H4_21d.parquet` | `XAUUSD` | `None` | `BLOCKED` | `UNKNOWN` | `UNKNOWN` | `PARTIAL` | logical XAUUSD from filename/sidecar label only; broker/server/source insufficient; not mapped |
| `XAUUSD_H4_30d.parquet` | `XAUUSD` | `None` | `BLOCKED` | `UNKNOWN` | `UNKNOWN` | `PARTIAL` | logical XAUUSD from filename/sidecar label only; broker/server/source insufficient; not mapped |
| `XAUUSD_H4_5d.parquet` | `XAUUSD` | `None` | `BLOCKED` | `UNKNOWN` | `UNKNOWN` | `PARTIAL` | logical XAUUSD from filename/sidecar label only; broker/server/source insufficient; not mapped |
| `XAUUSD_H4_7d.parquet` | `XAUUSD` | `None` | `BLOCKED` | `UNKNOWN` | `UNKNOWN` | `PARTIAL` | logical XAUUSD from filename/sidecar label only; broker/server/source insufficient; not mapped |
| `XAUUSD_M5_14d.parquet` | `XAUUSD` | `None` | `BLOCKED` | `UNKNOWN` | `UNKNOWN` | `PARTIAL` | logical XAUUSD from filename/sidecar label only; broker/server/source insufficient; not mapped |
| `XAUUSD_M5_14d_off14d.parquet` | `XAUUSD` | `None` | `BLOCKED` | `UNKNOWN` | `UNKNOWN` | `PARTIAL` | logical XAUUSD from filename/sidecar label only; broker/server/source insufficient; not mapped |
| `XAUUSD_M5_180d.parquet` | `XAUUSD` | `None` | `BLOCKED` | `UNKNOWN` | `UNKNOWN` | `PARTIAL` | logical XAUUSD from filename/sidecar label only; broker/server/source insufficient; not mapped |
| `XAUUSD_M5_183d.parquet` | `XAUUSD` | `None` | `BLOCKED` | `UNKNOWN` | `UNKNOWN` | `PARTIAL` | logical XAUUSD from filename/sidecar label only; broker/server/source insufficient; not mapped |
| `XAUUSD_M5_21d.parquet` | `XAUUSD` | `None` | `BLOCKED` | `UNKNOWN` | `UNKNOWN` | `PARTIAL` | logical XAUUSD from filename/sidecar label only; broker/server/source insufficient; not mapped |
| `XAUUSD_M5_30d.parquet` | `XAUUSD` | `None` | `BLOCKED` | `UNKNOWN` | `UNKNOWN` | `PARTIAL` | logical XAUUSD from filename/sidecar label only; broker/server/source insufficient; not mapped |
| `XAUUSD_M5_33d.parquet` | `XAUUSD` | `None` | `BLOCKED` | `UNKNOWN` | `UNKNOWN` | `PARTIAL` | logical XAUUSD from filename/sidecar label only; broker/server/source insufficient; not mapped |
| `XAUUSD_M5_35d.parquet` | `XAUUSD` | `None` | `BLOCKED` | `UNKNOWN` | `UNKNOWN` | `PARTIAL` | logical XAUUSD from filename/sidecar label only; broker/server/source insufficient; not mapped |
| `XAUUSD_M5_5d.parquet` | `XAUUSD` | `None` | `BLOCKED` | `UNKNOWN` | `UNKNOWN` | `PARTIAL` | logical XAUUSD from filename/sidecar label only; broker/server/source insufficient; not mapped |
| `XAUUSD_M5_63d.parquet` | `XAUUSD` | `None` | `BLOCKED` | `UNKNOWN` | `UNKNOWN` | `PARTIAL` | logical XAUUSD from filename/sidecar label only; broker/server/source insufficient; not mapped |
| `XAUUSD_M5_65d.parquet` | `XAUUSD` | `None` | `BLOCKED` | `UNKNOWN` | `UNKNOWN` | `PARTIAL` | logical XAUUSD from filename/sidecar label only; broker/server/source insufficient; not mapped |
| `XAUUSD_M5_70d.parquet` | `XAUUSD` | `None` | `BLOCKED` | `UNKNOWN` | `UNKNOWN` | `PARTIAL` | logical XAUUSD from filename/sidecar label only; broker/server/source insufficient; not mapped |
| `XAUUSD_M5_93d.parquet` | `XAUUSD` | `None` | `BLOCKED` | `UNKNOWN` | `UNKNOWN` | `PARTIAL` | logical XAUUSD from filename/sidecar label only; broker/server/source insufficient; not mapped |
| `XAUUSD_M5_95d.parquet` | `XAUUSD` | `None` | `BLOCKED` | `UNKNOWN` | `UNKNOWN` | `PARTIAL` | logical XAUUSD from filename/sidecar label only; broker/server/source insufficient; not mapped |
| `XAUUSD_M5_180d.parquet` | `XAUUSD` | `None` | `BLOCKED` | `UNKNOWN` | `UNKNOWN` | `PARTIAL` | logical XAUUSD from filename/sidecar label only; broker/server/source insufficient; not mapped |
| `XAUUSD_M5_30d.parquet` | `XAUUSD` | `None` | `BLOCKED` | `UNKNOWN` | `UNKNOWN` | `PARTIAL` | logical XAUUSD from filename/sidecar label only; broker/server/source insufficient; not mapped |
| `XAUUSD_M5_60d.parquet` | `XAUUSD` | `None` | `BLOCKED` | `UNKNOWN` | `UNKNOWN` | `PARTIAL` | logical XAUUSD from filename/sidecar label only; broker/server/source insufficient; not mapped |
| `XAUUSD_M5_90d.parquet` | `XAUUSD` | `None` | `BLOCKED` | `UNKNOWN` | `UNKNOWN` | `PARTIAL` | logical XAUUSD from filename/sidecar label only; broker/server/source insufficient; not mapped |
| `XAUUSD_15m.parquet` | `XAUUSD` | `None` | `BLOCKED` | `UNKNOWN` | `UNKNOWN` | `PARTIAL` | logical XAUUSD from filename/sidecar label only; broker/server/source insufficient; not mapped |
| `XAUUSD_1d.parquet` | `XAUUSD` | `None` | `BLOCKED` | `UNKNOWN` | `UNKNOWN` | `PARTIAL` | logical XAUUSD from filename/sidecar label only; broker/server/source insufficient; not mapped |
| `XAUUSD_1h.parquet` | `XAUUSD` | `None` | `BLOCKED` | `UNKNOWN` | `UNKNOWN` | `PARTIAL` | logical XAUUSD from filename/sidecar label only; broker/server/source insufficient; not mapped |
| `XAUUSD_4h.parquet` | `XAUUSD` | `None` | `BLOCKED` | `UNKNOWN` | `UNKNOWN` | `PARTIAL` | logical XAUUSD from filename/sidecar label only; broker/server/source insufficient; not mapped |
| `XAUUSD_5m.parquet` | `XAUUSD` | `None` | `BLOCKED` | `UNKNOWN` | `UNKNOWN` | `PARTIAL` | logical XAUUSD from filename/sidecar label only; broker/server/source insufficient; not mapped |
| `XAUUSD_i_15m_phase37.parquet` | `XAUUSD_i` | `XAUUSD_i` | `MATCH` | `UNKNOWN` | `UNKNOWN` | `UNKNOWN` | already canonical XAUUSD_i; no map required |
| `XAUUSD_i_4h.parquet` | `XAUUSD_i` | `XAUUSD_i` | `MATCH` | `OBSERVED_BROKER_EVIDENCE` | `OBSERVED_BROKER_EVIDENCE` | `PARTIAL` | already canonical XAUUSD_i; no map required |
| `XAUUSD_i_4h_phase29.parquet` | `XAUUSD_i` | `XAUUSD_i` | `MATCH` | `UNKNOWN` | `UNKNOWN` | `UNKNOWN` | already canonical XAUUSD_i; no map required |
| `XAUUSD_i_5m.parquet` | `XAUUSD_i` | `XAUUSD_i` | `MATCH` | `OBSERVED_BROKER_EVIDENCE` | `OBSERVED_BROKER_EVIDENCE` | `PARTIAL` | already canonical XAUUSD_i; no map required |
| `XAUUSD_i_5m_phase29.parquet` | `XAUUSD_i` | `XAUUSD_i` | `MATCH` | `UNKNOWN` | `UNKNOWN` | `UNKNOWN` | already canonical XAUUSD_i; no map required |
| `XAUUSD_i_5m_phase37.parquet` | `XAUUSD_i` | `XAUUSD_i` | `MATCH` | `UNKNOWN` | `UNKNOWN` | `UNKNOWN` | already canonical XAUUSD_i; no map required |
| `XAUUSD_i_5m_phase38.parquet` | `XAUUSD_i` | `XAUUSD_i` | `MATCH` | `UNKNOWN` | `UNKNOWN` | `UNKNOWN` | already canonical XAUUSD_i; no map required |
| `XAUUSD_i_m15_phase38.parquet` | `XAUUSD_i` | `XAUUSD_i` | `MATCH` | `UNKNOWN` | `UNKNOWN` | `UNKNOWN` | already canonical XAUUSD_i; no map required |
| `XAUUSD_i_m1_phase37.parquet` | `XAUUSD_i` | `XAUUSD_i` | `MATCH` | `UNKNOWN` | `UNKNOWN` | `UNKNOWN` | already canonical XAUUSD_i; no map required |
| `XAUUSD_i_m1_phase38.parquet` | `XAUUSD_i` | `XAUUSD_i` | `MATCH` | `UNKNOWN` | `UNKNOWN` | `UNKNOWN` | already canonical XAUUSD_i; no map required |
| `XAUUSD_i_ticks_phase37.parquet` | `XAUUSD_i` | `XAUUSD_i` | `MATCH` | `UNKNOWN` | `UNKNOWN` | `UNKNOWN` | already canonical XAUUSD_i; no map required |
| `XAUUSD_i_ticks_phase38.parquet` | `XAUUSD_i` | `XAUUSD_i` | `MATCH` | `UNKNOWN` | `UNKNOWN` | `UNKNOWN` | already canonical XAUUSD_i; no map required |

## Canonical XAUUSD_i

Direct datasets `XAUUSD_i_15m_phase37.parquet, XAUUSD_i_4h.parquet, XAUUSD_i_4h_phase29.parquet, XAUUSD_i_5m.parquet, XAUUSD_i_5m_phase29.parquet, XAUUSD_i_5m_phase37.parquet, XAUUSD_i_5m_phase38.parquet, XAUUSD_i_m15_phase38.parquet, XAUUSD_i_m1_phase37.parquet, XAUUSD_i_m1_phase38.parquet, XAUUSD_i_ticks_phase37.parquet, XAUUSD_i_ticks_phase38.parquet` remain MATCH. They were not rewritten.

## Production

**BLOCKED.** FINAL_GATE remains `BLOCKED`. No Strategy, RiskGate, execution, parquet, or canonical-symbol changes. Phase 27.21+ not started.

## Next

STOP after Phase 27.20.

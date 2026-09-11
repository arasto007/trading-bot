# Phase 27.10 — Dataset Symbol Binding & XAUUSD_i Canonicalization

**Status:** PASS  
**Artifact:** `logs/phase27_10_dataset_symbol_binding.json`

## Objective

Audit and harden the dataset-to-broker-symbol contract so there is no silent `XAUUSD`→`XAUUSD_i` conversion.

## Operator policy (inherited, not re-decided)

| Decision | Value |
|---|---|
| Canonical symbol | `XAUUSD_i` |
| Logical XAUUSD datasets | `ONLY_WITH_EXPLICIT_DATASET_MAP` |
| EV-EQ-01 | **NOT_PROVEN** (independent of mapping) |

An explicit `dataset_symbol_map` is an auditable alias rule. It does **not** prove economic equivalence.

## Contract

- Missing map → **BLOCKED** (`MISSING_MAP` / `SYMBOL_MISMATCH`)
- Invalid map (empty target, target ≠ configured, self-map of a non-canonical label) → **BLOCKED** (`INVALID_MAP`)
- `XAUUSD_i` label matching configured `XAUUSD_i` → `MATCH`
- Mapping provenance is recorded (`mapping_source`, `map_entry_used`, sidecar vs config map)

## Inventory summary

| Metric | Count |
|---|---|
| Datasets audited | 43 |
| Logical XAUUSD | 30 |
| Logical XAUUSD_i | 12 |
| Binding blocked | 31 |
| Cost-ready | 0 |

### Mapping status

| Status | Count |
|---|---|
| `MATCH` | 12 |
| `MISSING_MAP` | 30 |
| `UNKNOWN_SYMBOL` | 1 |

Direct `XAUUSD_i` matches: 12.  
Blocked logical aliases (no fabricated maps): 31.

## Paths

Backtest data load/cache/inject now bind through `resolve_broker_symbol_for_dataset`.  
`tradingbot.adapters.symbols.resolve_broker_symbol` remains the live helper and is **not** used for dataset binding. RiskGate / execution were not changed.

## Immutability

Parquet contents unchanged: **True**. Sidecars were not rewritten. No explicit maps were inserted.

## Production

**BLOCKED**. Phase 27.10 is a contract audit, not a strategy or profitability phase.

## Next

STOP after Phase 27.10.

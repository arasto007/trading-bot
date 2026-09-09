# Phase 31 — Event-Level Independence, Clustering & Concentration

**Status:** PASS
**Class:** RESEARCH ONLY
**Conclusion:** `HIGH_DEPENDENCE`
**Live trading authorized:** NO
**Parameters optimized / searched:** NO
**Strategy/RiskGate/ML changed:** NO
**FINAL_GATE:** `BLOCKED`

STOP AFTER PHASE 31. DO NOT START PHASE 32.

---

## Event definition

Official unit: **mechanical Asian-range + side**.

One EVENT = one (UTC date, asian_high, asian_low, side) tuple. The strategy computes the Asian range once per UTC date, then may emit multiple closed-bar NY 15-16 UTC signals while that same range remains the reference and the same side (BUY=Asian-low sweep, SELL=Asian-high sweep) remains valid. Repeated fires on that range+side are the same market occurrence, not independent liquidity events.

Phase 28.4's 30-minute proximity cluster is **diagnostic only**. It is not the official event ID.
It can split one Asian-range+side day (2026-08-27 BUY). That is not a second sweep event.

Selection for event-level performance: earliest official signal in the mechanical event. Not optimized.

## Classification

Every RAW signal is labeled: unique event / repeated within event / same-direction re-entry /
opposite-direction on the same day / same sweep / same NY session / same day / overlapping hold.

## Event metrics

| Metric | Value |
|---|---:|
| Signals | 24 |
| Events | 6 |
| Mean signals/event | 4.0 |
| Median | 3.5 |
| p75 | 6.25 |
| p90 | 7.5 |
| Maximum | 8 |
| Clustered signal share | 0.9166666666666666 |
| Phase 28.4 heuristic clusters | 7 |

## Performance

| Book | N | WR | Expectancy R | PF | Net R |
|---|---:|---:|---:|---:|---:|
| Per-signal | 24 | 0.041667 | -0.895833 | 0.065217 | -21.5 |
| Per-event | 6 | 0.166667 | -0.583333 | 0.3 | -3.5 |

Per-day / per-session rows are in the JSON. All signals sit in NY 15-16 UTC.

## Concentration

| Slice | Events | Signal share | Share of \|R\| |
|---|---:|---:|---:|
| Top 1 | 1 | 0.3333333333333333 | 0.32653061224489793 |
| Top 2 | 2 | 0.625 | 0.6122448979591837 |
| Top 5 | 5 | 0.9583333333333334 | 0.9591836734693877 |
| Top 10% | 1 | 0.3333333333333333 | 0.32653061224489793 |

Largest cluster signal share: `0.3333333333333333`.

## Dependence

Overlapping holds: `{'signals': 24, 'share': 1.0}`.  
Same-sweep clones: `11`.  
Shared-stop groups: `5`.  
Criteria hits: `['A', 'B', 'C', 'D', 'E', 'F']` (Explicit Phase 31 floors: mean signals/event>=2; largest-cluster share>=25%; clustered share>=50%; overlapping holds>=50%; >=1 shared-stop group of size>=3; events/signals<=0.5. HIGH if >=2 criteria hit; MODERATE if 1; LOW if 0. Not invented silently. Dependence is not a strategy failure.).

Treating 24 signals as independent **exaggerates** the evidence. This is **not** a strategy failure.

## Bootstrap

Two versions, seed `310031`, `2000` paths.

- SIGNAL-LEVEL: **not** independent evidence.
- EVENT-LEVEL: correct unit under `HIGH_DEPENDENCE`.

## CONCLUSION

**HIGH_DEPENDENCE**

HIGH_DEPENDENCE. 24 RAW signals collapse to 6 mechanical events (mean 4.00 signals/event; largest cluster 33% of the book). Treating signals independently exaggerates the sample. This is an independence finding, not a strategy failure, not an edge claim, and not a no-edge claim.

## Safety

No MT5 trading, no `.env`, no parquet rewrite, no strategy/RiskGate/ML/parameter changes. Phase 32 was **not** started.

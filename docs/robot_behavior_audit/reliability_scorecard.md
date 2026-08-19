# Reliability Scorecard

**Repository:** `TradingBot new`  
**Scoring:** 0 = broken / untrustworthy, 10 = production-grade  
**Basis:** Code structure, config clarity, backtest evidence, prior live observations

Be brutally honest — this bot executes real orders on demo but **backtest shows negative expectancy**.

---

| Subsystem | Score | Reason |
| --------- | ----- | ------ |
| **Startup** | 7/10 | Clear chain START_BOT → watchdog → kernel; startup validator requires USE_ML_KERNEL set; daemon kills stale processes and releases MT5 lock. Deduction: ML factory imports bloat startup even when ML off. |
| **Data feed** | 7/10 | MT5 health check (tick age ≤120s), reconnect in global cycle, min 80 bars gate. Deduction: broker/server time vs UTC session filter may drift (NOT PROVEN fixed). |
| **Feature generation** | 4/10 | **Duplicate feature pipelines** — IndicatorStage vs adaptive frame prep (`edge_discovery_round2`) compute overlapping indicators differently. High confusion risk, not a single source of truth. |
| **Signal generation** | 5/10 | Adaptive engine runs and produced live BUY (conversation evidence). Deduction: CONFLUENCE mode rarely fires; fixed 0.60 confidence; depends on research module in `ml/research/live_l2/`. |
| **Filter consistency** | 3/10 | **Worst subsystem.** WPSQF, TQ, meta-labeler, HTF, PA filters, ML RSI/ADX — different paths skip different filters. Adaptive bypasses most gates that `.env.example` suggests are ON. Owner cannot trust config labels. |
| **Risk management** | 7/10 | Solid live gates: spread (tick), cooldown, max trades/day, max concurrent=1, daily loss, kill switch, demo guard. Deduction: adaptive `risk_factor=0.5` not wired to lot sizing; emergency pip config may not match live.py. |
| **Execution** | 8/10 | guarded_order_send, retry on requote, slippage logging, autotrading check, journal on fill. One of the cleaner subsystems. |
| **Position management** | 7/10 | Shared `position_logic.py` with backtest; trailing, partial TP, EOD, Friday, emergency. Deduction: legacy PositionProtector disabled; position age timeout NOT PROVEN live; overlapping config keys. |
| **Accounting** | 4/10 | Entry executions logged to SQLite. **Exit PnL sync for live MT5 closes NOT PROVEN.** Paper mode has full lifecycle. Backtest JSON exists but live trade analytics gap. |
| **Replay parity** | 5/10 | Same kernel pipeline in backtest; but spread model differs (estimated vs tick), backtest `_position_size` duplicates lot logic, adaptive metadata risk_factor ignored in both paths potentially. 14d backtest: PF 0.32. |
| **Configuration clarity** | 3/10 | Many live.py keys unused; `.env.example` flags imply RSI/ADX filtering that adaptive ignores; three regime taxonomies; VOL_REGIME_ENABLED true but shadowed. Owner-facing config lies. |
| **Monitoring** | 6/10 | TradeJournal cycle_events, Notifier/Telegram optional, LiveOps daily report, kill switch, startup diagnostics. Deduction: no proven live exit analytics dashboard; watchdog logs only. |

---

## Overall Weighted Assessment

| Metric | Value |
|--------|-------|
| **Average score** | **5.4 / 10** |
| **Median** | 6.5 |
| **Lowest** | Filter consistency (3), Configuration clarity (3) |
| **Highest** | Execution (8) |

---

## Subsystem Risk Matrix

```
HIGH RISK          MEDIUM              LOWER RISK
─────────          ──────              ──────────
Filter consistency  Signal generation   Execution
Config clarity      Feature gen         Risk mgmt (gates)
Accounting gaps     Replay parity       Startup
                    Data feed           Position mgmt
```

---

## What Scores Would Need to Reach 8+

| Subsystem | Required fix |
|-----------|--------------|
| Feature generation | Single indicator service consumed by kernel + adaptive |
| Filter consistency | One documented gate list; remove or wire all .env flags |
| Configuration clarity | Delete unused keys; truth table in one config file |
| Accounting | Close-event handler writing PnL to journal |
| Replay parity | Backtest uses same spread + lot path as live |
| Signal generation | Demonstrated PF > 1 on 30+ days before raising score |

---

## Evidence References

- Backtest: `data/backtest_last.json` — PF 0.32, -30.14% return
- Duplicate logic: `duplicate_work.md`
- Dead config: `dead_features.md`, `configuration_truth.md`
- Live execution path: `execution_flow.md`

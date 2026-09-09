# Price Action Live Spec

**Status:** VERIFIED (code + preset; live fills NOT PROVEN)  
**Last verified:** 2026-09-01  
**Epistemic-Role:** OWNER of PA_STRATEGY including SL/TP numbers.  
**Operator-effective state:** UNKNOWN  
**Research class of uncosted replay:** B (`PA_LIVE_EDGE_AUDIT.md`) — not a size-up warrant.

Do not confuse module name `m5_london_sweep` / mode `london_sweep` with London hours.

---

| Field | Live value | Source |
|-------|------------|--------|
| Strategy id | `priceaction` | `ACTIVE_STRATEGIES`, `PA_STRATEGY_NAME` |
| Preset | `gold_ny_sweep` | `pa_symbol_tf_presets.py` `XAUUSD.M5` |
| Mode name | `london_sweep` | same → `evaluate_gold_setup` → `evaluate_m5_london_sweep` |
| Symbol | `XAUUSD_i` (preset key `XAUUSD`) | `PRIMARY_SYMBOL`; `normalize_symbol` |
| Timeframe | M5 / `5m` | `get_live_config()` |
| Session | NY 15–16 UTC | `NY_ENTRY_*`; `M5_USE_NY_SESSION=True` |
| London session | **OFF** | `M5_USE_LONDON_SESSION=False` |
| Asian range | 00–08 UTC | `ASIAN_START_HOUR`, `ASIAN_SESSION_END_UTC` |
| Forming bar | last row dropped | `exclude_forming_bar` |
| Entry | sweep of Asian high/low with buffer, then close **inside** range in NY window | `evaluate_m5_london_sweep` |
| Direction | sweep high + inside → SELL; sweep low + inside → BUY | same |
| SL | sweep extreme ± `SL_ATR_MULT * ATR` (0.35) | `sl_pad = atr * SL_ATR_MULT` |
| TP | `price ± max(distance to other Asian bound, risk * MIN_RR)` | `MIN_RR`/`TP_RR` 1.5 |
| Confidence floor | 0.52 | `MIN_CONFIDENCE` |
| Quality | ≥ 55 | `MIN_QUALITY_SCORE` |
| Cooldown | 18 bars; 10 min dedup | `COOLDOWN_BARS`, `PA_DEDUP_COOLDOWN_MINUTES` |
| Max trades/day | 3 | preset |
| Positions | max total 3, per symbol 2 | preset / live config |
| HTF M5 | **not required** | `REQUIRE_HTF_ALIGNMENT_M5=False` |
| CHoCH continuation | **off** | `ENABLE_CHOCH_CONTINUATION=False` |
| Rejection candle | **off** | `M5_REQUIRE_REJECTION=False` |
| ADX filter | off | `USE_ADX_FILTER=False` |
| ATR percentile | 12–94 | `USE_ATR_PERCENTILE_FILTER` |
| BOS / FVG flags | True in preset | hardening may apply |
| Session bypass | default false | `DEMO_DISABLE_SESSION_FILTER` operator UNKNOWN |

Function-default trap: `_in_entry_window` uses `M5_USE_LONDON_SESSION` default **True** if the key is missing. Live preset **sets it False**. Document **preset**, not the function default.

After setup: `apply_setup_hardening` then `build_trading_signal`. Then RiskGate (spread, news, Friday, meta, sizing) — not part of the setup function.

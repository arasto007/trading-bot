# Session Filter — False Negative Analysis

**Generated:** 2026-07-30T07:41:25.683374+00:00
**Data window:** 7 days M5 XAUUSD

## Question: Does SESSION remove winning trades?

**Answer:** Mostly no — blocked signals are mostly losers

## Method

For each bar **outside 12–17 UTC**, evaluate signal with:
1. No session filter (would trade)
2. Current session filter (blocked)

If (1) produces signal and (2) does not → **SESSION-blocked candidate**. Replay hypothetically on historical bars (SL/TP/timeout, no live execution).

## Results

| Metric | Value |
|--------|------:|
| Total SESSION-blocked signals replayed | 38 |
| Would-be winners (R > 0) | 4 |
| Would-be losers (R < 0) | 34 |
| Flat / timeout | 0 |
| **false_negative_rate** | **10.53%** |

### Formula

```
false_negative_rate = winning_blocked / total_session_blocked
                      = 4 / 38 = 10.53%
```

## Scenario comparison (hypothetical replay)

| Scenario | Signals | Win% | PF | Expectancy R | Net R | Max DD R |
|----------|--------:|-----:|---:|-------------:|------:|---------:|
| A — Current SESSION 12–17 | 8 | 25.0% | 0.45 | -0.4125 | -3.3 | 6.0 |
| B — No SESSION | 46 | 13.04% | 0.209 | -0.688 | -31.65 | 31.65 |

## Sample SESSION-blocked trades (first 15)

| timestamp | hour | dir | outcome | R | MFE R | MAE R |
|-----------|-----:|-----|---------|---:|------:|------:|
| 2026-07-21 10:10:00 | 10 | BUY | SL | -1.0 | 0.356 | 1.0124 |
| 2026-07-21 10:40:00 | 10 | BUY | SL | -1.0 | 0.1334 | 1.0008 |
| 2026-07-21 10:45:00 | 10 | BUY | SL | -1.0 | 0.1305 | 1.0239 |
| 2026-07-21 18:45:00 | 18 | BUY | TP | 1.6 | 1.7758 | 0.66 |
| 2026-07-21 19:25:00 | 19 | BUY | SL | -1.0 | 0.0806 | 1.1133 |
| 2026-07-21 19:30:00 | 19 | BUY | SL | -1.0 | 0.0236 | 1.1847 |
| 2026-07-22 06:50:00 | 6 | BUY | SL | -1.0 | 0.0748 | 1.0374 |
| 2026-07-22 06:55:00 | 6 | BUY | SL | -1.0 | 0.0501 | 1.0358 |
| 2026-07-22 08:50:00 | 8 | BUY | SL | -1.0 | 0.7757 | 2.1198 |
| 2026-07-22 09:05:00 | 9 | BUY | SL | -1.0 | 0.1819 | 2.0335 |
| 2026-07-22 09:10:00 | 9 | BUY | SL | -1.0 | 0.2543 | 1.9317 |
| 2026-07-22 09:15:00 | 9 | BUY | SL | -1.0 | 0.0329 | 1.9984 |
| 2026-07-22 17:50:00 | 17 | BUY | SL | -1.0 | 1.0108 | 1.047 |
| 2026-07-22 19:00:00 | 19 | BUY | SL | -1.0 | 0.2405 | 1.1142 |
| 2026-07-22 19:05:00 | 19 | BUY | SL | -1.0 | 0.0022 | 1.1579 |

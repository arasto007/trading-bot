# Phase 82 — Profit-Protection Design Taxonomy

RESEARCH ONLY. No walks in this phase. No parameter search. Production unchanged.

Predeclared: trigger MFE>=0.5R (Phase 74 L3 LOSS_AFTER_0.5R); fraction=0.5 (unique half of [0, MFE], not searched among 0.3/0.4/0.6).
Reversal anatomy (25 min / 5 M5 bars) motivates diagnosing retracement, not a bar-count search.
ATR on frozen parquet: `False` (columns=['open', 'high', 'low', 'close', 'volume']). Family D = DATA_LIMITED.
Naive BE/lock remain rejected from Phase 75. Hybrid is not created automatically.

## A. MFE-percentage protection

- Causal rationale: Naive BE floors at 0R regardless of how far price went. A unique structural half (0.5) of running MFE ratchets a floor that stays inside open profit, so a 32R peak would floor near 16R rather than 0R.
- Required data: ['entry', 'SL/risk', 'OHLC path after entry']
- Available data: ['jsonl entry/SL/TP', 'frozen M5 OHLC']
- Unavailable data: []
- Right-tail risk: If the +31.84R path retraced through 0.5*MFE after first arming, the tail is cut. Diagnostic, not a reason to retune fraction.
- Testable on frozen tape: True
- Parameter unresolved: False

## B. Peak-to-current retracement protection

- Causal rationale: Giveback is peak-to-SL surrender. Exit when half of peak MFE is given back. Trigger MFE>=0.5R from L3. Half is the unique structural fraction. 5-bar anatomy remains a TIME concept (Phase 75 E was NEUTRAL) and is not mixed in unless A and B independently help.
- Required data: ['running MFE from OHLC', 'current adverse extreme']
- Available data: ['frozen M5 OHLC']
- Unavailable data: ['true intrabar order inside a bar']
- Right-tail risk: Same-bar MFE+retrace is AMBIGUOUS (conservative floor-first).
- Testable on frozen tape: True
- Parameter unresolved: False

## C. Structural swing protection

- Causal rationale: Protect behind an already-confirmed in-trade swing (BUY below confirmed swing low, SELL above confirmed swing high) after meaningful MFE.
- Required data: ['OHLC after entry']
- Available data: ['frozen M5 OHLC']
- Unavailable data: ['persisted strategy swings/BOS on jsonl']
- Right-tail risk: Early confirmed swings near entry can act like a tight trail and clip extensions.
- Testable on frozen tape: True
- Parameter unresolved: False

## D. Volatility-normalized protection

- Causal rationale: Retrace thresholds in R ignore changing ATR. Normalization would need ATR known at the event bar.
- Required data: ['ATR at or before entry timestamp']
- Available data: []
- Unavailable data: ['atr column on frozen parquet', 'ATR on jsonl']
- Right-tail risk: UNKNOWN
- Testable on frozen tape: False
- Parameter unresolved: True

## E. Hybrid protection

- Causal rationale: Combine only if two families independently show TRAIN+VAL HELPFUL without parameter search.
- Required data: ['results of A-D tests']
- Available data: ['Phase 83 outcomes']
- Unavailable data: []
- Right-tail risk: Compounded clipping.
- Testable on frozen tape: conditional
- Parameter unresolved: False

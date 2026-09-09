# Phase 98 — State at First Favorable Excursion

FROZEN-DATA-EVIDENCE. Snapshots stop at first causal reach. Same-bar fav+SL is not credited.
ATR was not computed (not in the frozen OHLC source). No future information.

**DISCRIMINATOR_AT_FIRST_FAVORABLE:** `NOT_ESTABLISHED`

TRAIN+VAL confirmed separators: `[]`

Predeclared levels A–E: +0.25R / +0.5R / +1.0R / +1.5R / +2.0R. Majority cut = unique half (0.5). Velocity cut = 0.5R / 5 bars. Not searched.

- level 0.25R n=`315` CD=`151` EF=`121` med_bars CD=`1.0` EF=`2.0`
- level 0.5R n=`267` CD=`146` EF=`121` med_bars CD=`2.0` EF=`3.0`
- level 1.0R n=`205` CD=`84` EF=`121` med_bars CD=`4.5` EF=`7.0`
- level 1.5R n=`147` CD=`26` EF=`121` med_bars CD=`3.5` EF=`14.0`
- level 2.0R n=`78` CD=`18` EF=`60` med_bars CD=`3.0` EF=`11.0`

Same-bar fav+adv or SL-ambiguous snapshots are common (n_ambiguous=394). That is CODE-EVIDENCE of the conservative same-bar rule, not a C/D vs E/F separator.

INFERENCE: binary state features at first favorable excursion overlap across C/D and E/F on TRAIN and VAL. Descriptive median-bar differences exist (EF slower to +1.5R/+2R) but were not promoted to a searched threshold.

The +31.84R class-F event remains in the compact tape.

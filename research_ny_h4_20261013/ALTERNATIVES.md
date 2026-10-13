# Second exploratory batch, frozen before its outcomes

Repeat comparison failed. Do not tune it after seeing losses. Test three
specified alternatives on the same cached three pairs, phases and costs:
1. NY close breakout continuation, first per NY day, stop at that M5 bar's
   opposite extreme, next-open entry, 2R.
2. That same first continuation candidate only when aligned with complete H1
   EMA20/EMA50 trend (no hunting for a later acceptable candidate).
3. First original reclaim candidate only when aligned with that H1 trend.

H1 group must contain all 12 M5 bars. Indicators reset on missing H1 / weekend
gap, need 50 consecutive complete hours. Only H1 close-time <= entry timestamp
used. EMA20>EMA50 admits LONG; EMA20<EMA50 admits SHORT. No wick-confirmations.
No threshold sweep, no cost exclusions or ignored unknowns. Same six-day
coverage and costs as repeat comparison. These are exploratory reused-data
results, NOT validated strategies. Nine alternatives =>36phase/cost cells;
simultaneous CI within this batch only, not global post-selection certainty.
An apparently positive candidate would still require new independent data.

# Fixed Fibonacci hypothesis, before outcomes — 2026-10-13

Video specifies levels 0, .5, .618, 1 but leaves swings/trend/confirmation vague.
This is an explicit operational interpretation, NOT the author's exact bot.
Cached cTrader EURUSD/GBPUSD/USDJPY 2024-01-01..2026-10-07, reused research
data, NOT fresh holdout. No live strategy edits, funded paper entries or orders.

H1 confirmed swings: strict high/low compared with two complete H1 bars each
side, available ONLY after second right bar closes. At least two confirmed
highs and lows; both higher=>LONG trend, both lower=>SHORT. Reset on H1 gaps.
LONG anchors: latest confirmed high and preceding confirmed low; SHORT:
latest confirmed low and preceding high. 0 is terminal extreme / target;
1 is origin. Freeze anchor until its identity changes, origin is breached,
or pre-entry stop level is touched. One setup per anchor, not per calendar day.
Every H1 update must still agree with trend. No unconfirmed future extremes.

Main zone .5..618. Controls of identical width: .382..5 and .618..736.
Controls test whether chosen Fibonacci zone is distinctive; no parameter sweep.
Anchor must be known before M5 open. Wait for price-range touch of the zone.
Confirmation: bullish Close>Open AND Close>previous M5 High for LONG;
bearish Close<Open AND Close<previous M5 Low for SHORT. Same touch/confirmation
bar permitted if all information is known at its close. Wick alone no entry.
Stop: beyond deep zone edge by one pip (EUR/GBP .0001;JPY .01). Any pre-entry
stop touch invalidates that anchor. Target original level0, not arbitrary2R.
Entry modeled next M5 open, gaps outside valid stop/target geometry skipped.
This restrictive confirmation/stop choice is a hypothesis, not the video claim.

No forced time exit. Six-day path limit: missing or unfinished =>unknown,
not zero result. Stop-first for ambiguous OHLC, adverse gaps at opening price.
Independent observations can overlap; NOT a funded portfolio. Costs conditional
2/4pips round-trip (JPY .02/.04); no actual bid/ask fills, swaps, margin or USD
account conversion. Dimensionless netR only. USD5 illustration not used.

Early2024–25 / late2026 split. Each9pair/zone combination reported at2costs,
2phases =>36cells. 6000 bootstrap replicates with10setup-day circular blocks;
simultaneous95%bounds across36cells, closed-only results with unknown counts.
Gate: main zone early+late stress mean>0 and lowerCI>0, late>=100 closed,
no unknowns. Even passing reused-data screen needs new independent validation.

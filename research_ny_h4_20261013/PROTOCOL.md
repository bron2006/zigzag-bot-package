# Frozen comparison before outcomes — 2026-10-13

Compare owner's unchanged NY 00–04 close-break/close-reclaim pattern:
first setup per pair/day versus all distinct repeated setups, including a
non-overlap subset. Exact M5 closes, movement extreme stop, next open, 2R.
After a return, require a NEW subsequent closed breakout followed by another
return. No re-entry using the same return bar. No filters optimized here.

Cached cTrader EURUSD, GBPUSD and USDJPY, 2024-01-01..2026-10-07.
2024–25 early; 2026 late. Reused history, NOT untouched holdout.
Round-trip costs: EUR/GBP 2 or 4 pips; USDJPY 2 or 4 pips = 0.02/0.04 JPY.
Dimensionless netR, NOT USD funded-account results. No swap/fill/margin model.
First and repeated arms use identical price paths and costs.
Max six-day path; missing data/unfinished trades remain unknown.
Independent repeat observations can overlap and are not executable portfolio.
Non-overlap arm blocks each pair until modeled exit; unknown path blocks that
pair through its six-day coverage boundary (explicit quarantine, not a close).
No assumption of known resolution, or zero PnL for unknown trades.

Closed-only mean netR and PF reported with unknown counts. Day-block bootstrap
uses all setup days, including no-close days. Conservative simultaneous 95%
intervals across 36 pair/arm/phase/cost cells; overlaps and missing outcomes
still limit inference. No trading activation or live-strategy changes.
Positive gate: early AND late stress mean>0, late >=100 closed, no unknown
setups in either phase, simultaneous CI lower bound>0 in both phases.

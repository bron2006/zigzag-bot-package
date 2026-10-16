# Frozen fixing-reversal hypothesis, 2026-10-16

Written before candidate outcomes. One rule, EURUSD and GBPUSD, no grid,
no threshold adaptation after results. Local cached broker CFD M5 history,
already studied in other research, NOT independent holdout or verified WMR flow.
No duplicate exact London16 fixing mechanism found in reviewed CLAUDE/research
protocols; prior EMA/VWAP/channel/NY-reclaim mechanisms are not reused.

Europe/London civil clock including DST. Weekdays only. Require all 12 actual
M5 bars 15:00--16:00 plus actual 16:00--16:05 bar. Hour movement is last Close
minus first Open; absolute movement >=0.5*(hour High-hour Low), nonzero range.
The first post-fix bar must close against that impulse (bearish after positive
hour, bullish after negative hour), and past the preceding hour Close.
Decision16:05, actual entry16:10 after full M5 delay. Fade the hour impulse.
Structural stop beyond extreme of all 13 known bars by0.1*hour range.
Require positive actual entry-to-stop distance; never force minimum volume.
TP2 raw risk, max hold60min. One opportunity/day/pair. No overnight intent.
Missing entry/path before known exit is unknown and halts that arm; missing
after known exit does not erase it. Stop-first ambiguity, adverse gap Open,
favorable target gap only target limit. Cost2/4pip roundtrip, illustrative not
actual historical commission/spread/slippage; no funding assumed for intraday.

Same-event alwaysBUY, alwaysSELL, and hour-momentum use same risk distance,
entry, target ratio, hold and costs. Controls are counterfactual outcomes, not
funded portfolios. Neither volume nor cost chooses signal opportunities.
Independent USD1000 accounts per pair/cost, Jan2025--Oct7 2026 continuous (no
year reset), risk0.5% current cash including cost, current Oct14 metadata
min/step/max APIvolume divided100, roundDOWN, 5x notional cap (not verified
margin), skip unattainable units. Report 2025 and2026 separately,2024 diagnostic.
Unit-R includes structurally valid opportunities; USD ledger can skip minsize.

Gate each pair: >=50 known outcomes in BOTH2025 and2026; zero unknown or
censored controls; stress netR positive BOTH years; stress2026 daily-netR AND
paired excess over ALL three controls adjusted CI lower>0; stress USD2025end>
1000 and2026end>2025end. Overall candidate requires BOTH pairs pass.
10calendar-day circular moving block bootstrap10000 seed20261015, inherited
64cell adjusted intervals (not correction for all historical strategy searches).
No optimization or deployment if gate fails. Preserve original pkl/config/cash.

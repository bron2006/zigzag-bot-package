# Fixed weekday FX drift, frozen before candidate outcomes, 2026-10-16

Different hypothesis: recurring calendar-day demand, NOT price momentum,
currencygraph, moving average, rangebreak or event reversal. EURUSD and GBPUSD
only. London08:00 decision each weekday, actual08:05 M5 open delayed entry,
hard exit12:05London (4h), no overnight/swap. DST from Europe/London, not UTC
offset guessed. Direction for each pair/weekday is sign of mean simple return
08:05Open→12:00M5Close in2024 ONLY; full48M5bars required for training, >=30
observations perweekday, zero mean/noadequate training=>no signal. All five
weekday signs frozen across2025..2026Oct7, no threshold/grid/bestweekday picking.
2024 is already studied cache, NOT fresh blind development or OOS guarantee.

At decision stopdistance1.5*mean true range of latest14 complete H1bars whose
close<=decision, newest<=2h old, no gap>7days in those14. Previousclose needed
for all14TR; observed weekend bars allowed, no imputation. Stop actual delayed
entry +/-distance; TP2distance. Stop-first ambiguities, adverse gap actualOpen,
favorable TP gap capped at target. Missing entry/path=>UNKNOWN, notzero;
halt candidate afterwards to avoid inventing flat state. One open trade per
independent pair account; do NOT sum two $1000 accounts as sharedportfolio.

Base2pip/stress4pip assumed all-inRT friction, NOT actual historical costs.
CurrentOct14 metadata min/step/max/100 conditional only; dynamiccash1000USD,
.5%risk inclcost,5xillustrative notionalcap (notverifiedmargin), roundDOWN and
skip minimum. Decision sized using lastclosedM5price andactualentry rechecked;
common opportunities gated on4pip and1000USD, then actual evolvingcash ledger.
No future liquidity/session completeness used to choose testdays.

Controls alwaysBUY/SELL and opposite frozenweekday direction SAMEevent/stop/
cost; counterfactual controls not funded portfolios. Each2025/2026counts,
PF/netR, independent dollarbalances, cashDD. 10calendardayblockbootstrap10000
seed20261015, conservative64cell existinghelper correction, not global search
guarantee. Gate>=50known eachyear, unknown0/controlunknown0, positive stressR
bothyears, positive2026adjusted dailyR and excessovereachcontrol lowerCI,
stressend2025>1000/end2026>end2025. Everypair reported, no promote bestsubset.
No DB/runtime/model/config/account/orders/deploy writes.

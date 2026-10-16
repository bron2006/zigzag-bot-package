# London fixing fade: completed, rejected for activation

2026-10-16. Frozen one-rule PROTOCOL, not grid search. London civil16:00 DST
anchor, strong preceding hour, closed first-five-minute reversal confirmation,
full5minute entry delay, structural stop,2R target,1hour max hold. This is NOT
proof the broker CFD candles contain actual WMR order flow. Official anchor
reference supplied by coordinator: https://www.lseg.com/en/ftse-russell/benchmarks/wmr-fx-benchmarks

Cached Jan2024--Oct7 2026 data has been studied previously: NOT untouched OOS.
2024 is diagnostic, funded illustration starts Jan2025 with independent1000USD
per pair/cost and no annual reset. Current Oct14 volume terms, assumed2/4pip
roundtrip costs, .5%cash risk including cost,5x notional ceiling (not margin).

| Pair | Known2025/2026 | Base endUSD | Stress endUSD |
|---|---:|---:|---:|
| EURUSD |50/45|914.980|875.708|
| GBPUSD |61/48|939.537|886.790|

All opportunities were attainable for1000USD: EUR95/95 andGBP109/109 funded,
ZERO minimum-size skips. No unknown actual outcomes or censored controls.
All years/pairs have negative netR;2026 sample below50 forboth. Stress2025/26
EUR -21.154681/-19.127613R;GBP -17.171724/-18.165056R. Both pair gatesFAIL.
All2026 adjusted paired excess intervals over same-event BUY/SELL/momentum
includezero, so no demonstrated direction-selection advantage.

Important attribution (2025--2026 funded trades):

| Pair/scenario | Gross USD | Costs USD | Net USD |
|---|---:|---:|---:|
| EUR base |-24.420|60.600|-85.020|
| EUR stress |-19.892|104.400|-124.292|
| GBP base |-4.863|55.600|-60.463|
| GBP stress |-12.010|101.200|-113.210|

Thus not merely minimum volume blocking otherwise good opportunities. Gross
funded PnL is also negative, so replacing assumed cost withzero for these SAME
frozen funded quantities would still not profit. Unit-R gross likewise negative
in2025 and2026 for bothpairs; do NOT infer everyfixing strategy impossible.
Stress/base different grossUSD reflects cost-aware position quantities, not
different price exits. Same-event controls are counterfactual, not funded books.

11 targeted testsPASS (London DST including springboundary; signalclose versus
wick; causal decision/entrydelay/futurepoisoning; mirror; missing signal excluded;
missing entry haltsunknown; stopfirst/adversegap; unknownpathnotzero; earlyknown
exit preserved; unknown forbids fullcash; binary-residue threshold equality).
Coordinator detected a numerical control-boundary discrepancy in the initial
float simulator. Initial local audit covered ACTUAL exits, not all CONTROLS.
NUMERICAL_REPAIR.md documents this AFTER-results repair; original protocol is
unchanged. Both candidate and controls now use Decimal with12decimal derived
distance precision, not executable broker tick snapping. Recomputed cash at
displayed precision is unchanged; confidence intervals remain includingzero.
Expanded independent Decimal auditPASS:632 actual scenario exits all2024--2026
AND1896 control path/excess replays, exact stopgeometry/reasons/timestamps,
408 funded quantity/cash trades (EUR95*2+GBP109*2), maxnetR/excesserror4.44e-16.
Input hashes, protocolhash and originalmodel/scaler hashes verified unchanged.
No config/DB/broker runtime imports, no real orders/cash reset/deploy/UIchanges.
Source imports shared research math; only isolated research/test files added.

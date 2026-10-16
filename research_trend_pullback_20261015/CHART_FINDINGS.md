# Alternative charts: all six fixed arms fail activation screen

Same trend/pullback family, different paired signal/context candle durations.
UTC M30/H2, H2/H8, H8/D1; stop/target/cost/4h max holding unchanged. Separate
$1000 accounts per asset/arm, Jan2025..Oct7 2026. Reused history, not new OOS.

| Signal/context | EURUSD base/stress end | EUR trades 2025/2026 | GBPUSD base/stress end | GBP trades 2025/2026 |
|---|---:|---:|---:|---:|
| M30/H2 | 1007.00 / 988.58 | 25/2 | 992.66 / 979.30 | 23/19 |
| H2/H8 | 977.83 / 976.93 | 14/5 | 989.98 / 989.19 | 11/5 |
| H8/D1 | 999.08 / 998.88 | 1/0 | 1000 / 1000 | 0/0 |

2/4pip roundtrip conditional costs, not actual historical fills. Both years
and controls retained in charts_result. No unresolved selected paths. Gates
all fail, every arm under50known/year. Flat zero-trade arm is NOT profitable.
EUR M30 base year2025end1007.023 vs final1007.003, so not positive each year.

M30 often fails the fixed cost-to-risk screen (EUR94/151 raw intents across
2024..2026), so more chart candles do NOT imply more acceptable funded entries.
H8 with this unchanged08..15UTC/4h holding schedule has only08UTC decisions.
Fully complete UTC D1 requirement rejects319EUR/371GBP partial daily buckets;
only348EUR/155GBP daily indicator bars survive after warmup/filter. Daily
maintenance/session boundaries in source can make D1 completeness demanding;
do NOT claim every rejected bucket is specifically a feed outage, nor that
H8/D1 trading generally cannot work. H8 EUR3raw intents,2minimum-size rejects,
1funded;GBP0intents. Broker min1000units and .5% budget bind wide stops.

Baseline H1/H4 exact old intents regression-checked unchanged for both pairs.
Five new tests: true complete aggregation, all-scale prefix indicator causality,
closed context/5min delayed entry,15:00 boundary,unsupported charts rejection.
Independent Decimal replay300scenario exits/reasons/R and funded cash matched;
maxR discrepancy1.12e-13;input/original model hashes match. No live changes.

Conclusion: changing chart scales alone did not validate this entry family.
Do not select a lucky cost scenario, fill missing candles, loosen filters after
results or label reused history an unseen holdout to claim a working strategy.

# Fixed three-rule M5 comparison — 2026-10-09: all gates failed

Owner authorized this comparison with «роби». No trading, deployments, production
model changes, DB writes, token refreshes, executor starts or VWAP reactivation.
Supabase skill used for existing persisted-token read only; demo account verified
before allowlisted broker history requests. Hard isolated fetch deadline900s.

## Data and locked method

105 immutable gzip pages,630000 raw bars received; after bounds/dedup620069 M5
bars: EURUSD206736, GBPUSD206653, USDJPY206680. Requested2024-01-01 through
2026-10-07 inclusive. Early2024–2025 full sessions517/516/516; final2026 full
sessions198 per pair. Incomplete sessions excluded early2/3/3, final1/1/1.
An extra early GBPUSD reversion day had no qualifying signal. No missing-bars
interpolation. Prior studied fragments mean retrospective, NOT blind OOS.

COMPARATIVE_PROTOCOL.md fixed before acquisition/results: trend EMA10/EMA50,
past20bar breakout, non-VWAP mean reversion. Indicator reset on gaps,60barwarmup,
one first signal per pair/day/rule,08–16UTC. Decide completedbar i, buffer i+1,
entryOpen i+2, expiryClose i+2 (300s). Results finalized only after113research
tests passed and early report locked engine/protocol SHA. No post-result tuning.

Forex units are signalATR, NOT fixed-risk R/deposit return. Costs illustrative,
not broker fills: base max(.22ATR,2pips), stress max(.44ATR,4pips). Binary separate
direction proxy: assumed payout80%, flatrefund, fixedstake1, NOT Binomo settlement.
Common day axis, circular10sessiondayblocks,4000draws,seed20261009,98.333% family
intervals for these3 rules. Correction does not cover the project's other past
experiments; passing would still require prospective validation. No rule passed.

## All results, including failures

Early trend1549selected/1526nonflat,50.524%; breakout1549/1528,48.233%;
reversion1548/1531,51.012%. Binary80 meanstake respectively-.089219,-.130019,
-.080879; stressforex meanATR-.813083,-.872254,-.848274. All early gates fail.

Final198UTCdays,594 selected observations per rule (observations correlated across
pairs/rules, NOT1782independenttrades and NOT real trades):

- Trend286/585nonflat=48.889%,9ties. GrossATRmean-.004353 interval
  [-.075164,+.065794]; base net-.495929; stress-.987504
  [-1.119807,-.859609]. Binary80mean-.118182stake [-.210774,-.026263].
- Breakout272/582=46.735%,12ties. Gross-.012574 [-.071277,+.051000];
  base net-.514857; stress-1.017140 [-1.167775,-.878283]. Binary80
  -.155556 [-.232104,-.071153].
- Reversion314/583=53.859%,11ties. Gross+.002601 [-.059461,+.069824];
  base net-.498573; stress-.999747 [-1.123745,-.876783]. Binary80
  -.029966 [-.126044,+.061843]. At payout90% retrospective mean+.022896
  does NOT rescue predeclared80% gate or establish robust/executable profit.

Binary breakeven ignoring ties at80% payout=55.556%; none reaches it. Gross forex
effect indistinguishable from zero even without the illustrative fee allowance.
Same-timestamp superiority over alwaysBUY and alwaysSELL not established for any
rule (all paired adjusted intervals includezero). Opposite directions diagnostic
only: finalbinary80means-.078788,-.040404,-.166330; stressforex allnegative too.

Final per-pair198 observations each, ordered EURUSD/GBPUSD/USDJPY:
- Trend stressmeanATR -1.151687/-.809722/-1.001104;
  binary80meanstake -.130303/-.080808/-.143434.
- Breakout stress -1.225753/-.836822/-.988844;
  binary80 -.188889/-.116162/-.161616.
- Reversion stress -1.125521/-.945291/-.928428;
  binary80 -.002020/-.121212/+.033333. The isolated positiveJPY result is
  NOT a selected candidate; pair filtering after seeing outcomes prohibited.

All6 gates false (3forex/3binary). Stop recommendation for THIS fixed three-rule
5minute screen; no deployment or forward test of these rules. Not proof against
every trend/breakout/reversion strategy, other horizons or other venues. Do not
invert live signals or treat more historical data as proof of real profitability.

## Verification and persistence

11 new tests,113research tests total pass: future mutation, gap reset, price scale,
prior range, no volume/VWAP, first signal, entry/expiry, incomplete session, year
split, pair pip costs, same-observation baselines, bootstrap and gate failures.
Independent stdlib reconstruction of compressed rawOHLC, rollingATR, recursiveEMA,
all firstsignals/sessioncoverage and price/cost/baseline endpoints passed6428
records across early/final phases and105pageSHA checks. Audit makes no engine
indicator calls. Bootstrap/modeling assumptions remain assumptions, not fills.

Early reportSHA f7624729fa60963ce2642205479728c3470a00d62ce1b5c47b32f2e7caccebea
Final reportSHA f6f04dea3471822ed9e2e8cc84c2e6fc5a86f3acba5f2ac932415878e8aac371
Raw broker caches/full derivedprice reports remain ignored localresearch data;
source, protocol, tests, audit and this aggregate report saved on recoverybranch.
Production health NOT inspected in this task; do not infer current health.

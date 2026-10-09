# External strategy reference — 2026-10-09

Owner «вперед»: external strategy search, selection and arithmetic reproduction.
One reference selected: Industry Timing, Zarattini/Antonacci, complete daily
portfolio process. Open data and methodology allow reproduction without account
credentials. Not chosen as production strategy; synthetic industry indices cannot
be directly traded on the current cTrader venue. No new actual strategy deployed.

## Search decision

Compared primary methods with existing project experiments before computation:
- AQR47futures momentum is NOT our previous4CFD adaptation, but exact individual
  instruments/rollover and borrowing costs not established for this broker.
- ORBstocks-in-play requires equity universe and true exchange volume, not FX tick
  volume; cannot reproduce by relabeling our EURUSD/GBPUSD/USDJPY.
- SPYintraday requires actual ETF minute data/dividends. Accessible primary code
  uses providercredentials. No APIaccountcreated, subscription or payment made.
- Industry Timing: public daily48industryreturns and factor/RF data. Selected as
  an independentlyimplementable reference, not an account suitability claim.

Primary sources:
https://concretumgroup.com/backtest-a-profitable-trend-following-strategy-using-python/
https://concretumgroup.com/wp-content/uploads/2026/02/A-Century-of-Profitable-Industry-Trends.pdf
https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html
Independent discussion of robustness/modern applicability:
https://arxiv.org/html/2412.14361v1

## Reproduction boundary

Source version discrepancy found BEFORE our outcome calculations: currentpaper
uses14dayvol/.015sizing numerator; tutorial uses20dayvol/.02. These are different
reference specifications, NOT a reason to optimize. EXTERNAL_REFERENCE_PROTOCOL.md
explicitly pins tutorial mechanics, no parameter search. Therefore do NOT claim
exact replication of the paper's18.2%CAGR/1.39Sharpe. We implemented formulas
independently; did not execute downloaded author/thirdparty code.

Downloaded originalKennethFrenchZIP using publicGET, bounded isolatedchild90s,
verifiedoneCSVpayload/filelimits; localgz checkpoints. Industry archive4098912bytes,
factor178184bytes,202608CRSP vintage. Public data revised historically, not an
original1926–2024 or point-in-timevintage. Equalweight block NOT mistaken for first
valueweight block. Missingcodes -99.99/-999 retainedNaN, factor dates strictly
checked. Raw export CRCRLF introduced empty line after EVERY row; initial parser
failedheader safely before outcomes. Fixed before first successful calculation and
added exact-format regression. No invented dates/missingRF fills.

## Calculated outcomes, NOT executable returns

Reference1926-07-01–2024-03-28:25710observed days. Tutorialstrategy grossreference
CAGR21.972%, annualizedvol15.315%, RF-excessSharpe1.126, dailycloseMDD-42.342%.
MarketCAGR10.084%, vol17.116%, excessSharpe.450,MDD-84.074%.
EqualweightindustriesCAGR11.601%,MDD-83.200%. Averagegross exposure133.42%NAV,
maximum200%; turnover27.88onewaynotionalunits/NAV/year. Financing atRF included,
tradingfees/slippage NOT included, missingindustry price accumulation0 only as
reference convention. No deposition/dollarprojection or actualfills claim.

Prespecifiedcontemporary diagnostic2024-04-01–2026-08-31:607days. Same unchanged
rules/state, freshperiod equity normalization. Not blindprospectiveOOS; no gate.
StrategyCAGR3.270%,vol13.733%, excessSharpe-.032,MDD-15.052%; marketCAGR18.750%,
vol16.262%,excessSharpe.857,MDD-19.558%; equalindustryCAGR15.139%,MDD-18.589%.
Meanexposure114.01%,max200%, annualturnover23.70. Historicalreturn positive but
recent marketunderperformance/cost/financing sensitivity important. Do not confuse
slightlysmallerDD with proven timing advantage or promised regularincome.

## Verification

11 new tests,124 research tests total. Futuremutation, weightslag, caps, warmup,
cash/borrowarithmetic, missingcodes, block selection, duplicate dates, CRCRLF,
turnoverweightdrift, summary. Separate scalarEMA/rollingbands/trailingstate/
populationvol/portfoliocaps reconstruction agrees with engine across220days×8
syntheticassets. This is independentfixture verification, NOT independentaudit of
all historical signals. No bootstrap/significance claimed for these reference
results. Modern25/26period includes knownhistory and is not future validation.

IndustrycacheSHA d6f0c5d388012d34b604823f0436c84c3a11dfb5010ead77aa80bc83f8ea94f7
FactorcacheSHA 8ec58e6c5292576376fbf7e28cd0ba2c8c448f745bae5fd0315cb2e21478474c
Data/resultJSON remain ignoredlocalresearch. Source/protocol/aggregateaudit kept
on recoverybranch, not main. No broker/DBconnection, orders, tokenrefresh,
cloudchanges, accountmigration, VWAPrestart or recurringprocessstarted.

## Decision / next boundary

Selected reference is a full portfolio strategy, not yet deployable candidate.
Do NOT replace the productionclassifier with tutorial signals or quote21.97% as
owner'sexpectedreturn. Need source-version reconciliation/exactpaper replication
first, then realistictradeableETF-universe, delay/fill/financing/cost validation.
ETF/account migration is a MATERIAL scope decision, not implied permission to
trade a newvenue. Framework functions are offline only, production_allowed=false.
No strategy proved suitable to the owner's$1000 in this turn.

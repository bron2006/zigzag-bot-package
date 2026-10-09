# Funding premium public-data screen — fixed before fetching outcomes,2026-10-09

Owner asks to keep searching. New MECHANISM, not forecast direction: longspot plus
shortperpetual can receive positivefunding; negativefunding is paid, not removed.
BTCUSDT andETHUSDT only, fixed2023-01-01..2026-10-07inclusive. PublicGET fundingRate
history, end2026-10-08UTCexclusive, page1000 ascending, max10pages/symbol, isolated
child90s; no credentials/DB/accounts/orders. Cacheimmutable/checksum, resumable.

This is a premium component screen ONLY. Sum settled fundingRates per calendar
year, positive/negative counts, extrema, actualtimestamp gaps, observed eventcounts.
No filtering by rate after seeing outcome, no reinvestment, no dynamichedgerule.
Constant1notional convention; sumrates is NOT actual fixedBTC fundingUSDcashflow,
returnNAV, profitablehedge, knownfutureyield or price/basis PNL. FixedBTCquantity
cashflow uses price at each settlement; that is NOT simulated here.
No interpolation of missing settlements. Expect8hour settlementspacing for these
symbols but record actualgaps, do not assume frequency guarantee from today'sspec.
Illustrate only: sumrates/2capital where another1notional is an ARBITRARY collateral
reserve. It does NOT guarantee no liquidation. Annualrateaggregate minus illustrative
.4%/.8%totalfour-leg roundtripcost divided2 is a COMPONENT sensitivity for full
calendar years, NOT strategy performance or actual fee schedule. 2026partial NOT
annualized/extrapolated. No bootstrap tradeprofit/no statisticaledge gate claimed.

Need historicalpairedspot/perpBIDASK/basis, fixedquantitycashflows, actualfee/tax/
fundingavailability, collateralmarginliquidation, transferlatency/default/adl risk
before a hedge strategy could be considered. No order-capablebot created fromthis.
This differs from07Octdatedfuturescarry: no fixed maturity/lockedbasis; variable
periodicpayment can reverse. Never reviveVWAP or buy an advertisedtradingbot.

Primary endpoint docs:
https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data
Economic/collateral background:
https://www.bis.org/publications/working-paper-1087-crypto-carry

## COIN-M extension, before full COIN-M aggregation

Do not select one asset after results. Same fixed period onBTCUSD_PERP/ETHUSD_PERP
using publicdapi fundinghistory. InitialBTC1000record accessibilityprobe already
read (not blind); no aggregation/modelselection. COIN-M rates distinct fromUSD-M,
never transfer one'srate/history to the other'scontract. Some oldmarkPrice fields
empty: preservesource, do NOT fabricate historicalmarkPrice or simulatecashflows.
Component/collateral sensitivity remains arbitrary2capital convention only.
Currentpublic exchangeInfo probe confirmsBTCface100USD/ETHface10USD,marginBTC/ETH,
PERPETUAL/TRADING. It is NOT accesspermission, historicalspec or accountmargincheck.

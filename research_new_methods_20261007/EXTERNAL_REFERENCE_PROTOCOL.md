# External strategy reference, frozen before fetching/calculating — 2026-10-09

Owner «вперед» authorized external-strategy selection/reproduction, not orders,
ETF-account migration, deployment or revival of VWAP. Chosen reproducible
research reference: Zarattini/Antonacci Industry Timing. Universe Kenneth French
48 value-weighted industry daily total-return portfolios, risk-free and market
daily returns. Portfolios are synthetic research indices, NOT directly tradable
assets. Current download is a revised vintage, NOT point-in-time release data.

Primary tutorial (full procedure, not a sales claim):
https://concretumgroup.com/backtest-a-profitable-trend-following-strategy-using-python/
Primary paper current revision2025-10-02:
https://concretumgroup.com/wp-content/uploads/2026/02/A-Century-of-Profitable-Industry-Trends.pdf
Data source:
https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html

One reference, no parameter searches. Tutorial arithmetic profile is fixed20day
volatility ddof0, .02 dailyvol sizing numerator,20/40bands,2.8price-change multiplier,
20% individual weight cap, totalweight<=2; cash earns RF, debt pays RF. Current
paper differs:14dayvol,.015target. Do NOT change parameters to match18.2% claimed
CAGR. This run reproduces tutorial mechanics, NOT exact current-paper statistics.
Reference bands: min(past/current20max,EMA20+2.8mean20abschange) for entry;
max(40min,EMA40-2.8mean40abschange) for exit. Entry uses yesterday upper/lower
and today's completedclose; ongoing trail max(previoustrail,currentlower), exit
if completedclose<=trail. Weights inversevol divided by number of available
industries, individuallycapped20%, then proportional aggregatecap2.

Reference applies completed-close decisions to next close-to-close return.
This is a mathematical close-fill approximation: SAME closing print may be
unavailable after decision. Not an executable fill engine. Cash/return aggregation
strictly lagged; missing industry returns converted to0 ONLY in reference price
index accumulation and reference contribution, never described as observedzero.
Track missing count, causal warmup, exact factor-date coverage, duplicate rejection.

Predeclared range1926-07-01..2024-03-31inclusive (paper period); warmup starts at
first observed day. Additional2024-04-01..2026-08-31 contemporary diagnostic held
until reference calculation/tests completed; NOT blind/prospective OOS. Same
rules/state, separate period equity begins1. No tune to rescue contemporary result.
Report CAGR/calendar time, samplevol252days, Sharpe RF-excess, drawdowndailyclose,
gross exposure, turnover inclweightdrift, available industries. Control market
and daily equalweightindustries same observed dates. Borrowing at RF is unrealistically
cheap for retail; free turnover is a reference assumption, NOT usable tradingPNL.
No capital/dollar forecasts. No pass gate or shortlist from this arithmetic run.

Selection exclusions recorded BEFORE this run: AQR original47futures access not
replicated by previous4CFDs; ORBstocks-in-play needs1000USstocks and realexchange
volume; SPY intradaynoiseband needs minuteETFquotes/dividends/providercredentials.
Chosen reference lets us validate a COMPLETE externallyspecified portfolio process
with public inputs. It does NOT yet establish suitability to the owner's$1000,
broker permissions, tradingcosts, actualETF fills, jurisdiction or profit.

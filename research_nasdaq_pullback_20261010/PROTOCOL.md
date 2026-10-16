# Nasdaq session expansion + pullback: frozen research contract v1

Frozen 2026-10-10 BEFORE acquisition and any PnL calculation. Independent
adaptation, NOT a replication of the SPY paper and NOT a trading executor.
Source idea: https://concretumgroup.com/quantip-improving-performance-with-fast-alphas-a-tactical-overlay-for-intraday-trend-trading/

## Scope and data
USTEC (broker Nasdaq100 CFD) only. 2024-01-01 through 2026-10-07 inclusive.
Warmup D1 from 2023-11-01. M5 broker bars, no interpolation. Cash session
09:30-16:00 America/New_York (DST aware). Exclude published US equity full
holidays and early-closing days; no signals on weekends. Require all 78 RTH
M5 bars. D1 ATR14 = simple average of true ranges of latest 14 completed
weekday broker D1 bars, including preceding close for TR. Require >=15 bars
and no >5 calendar-day gap in that window. Weekday is the UTC date of
bar completion, not its start (overnight Sunday-start bars are retained).
D1 completion conservatively
defined as timestamp+24h <= session open; no current-day high/low leakage.
Broker D1 is NOT the SPY regular-session daily series. All deviations explicit.

## Exactly one fixed strategy
Session open S from 09:30 M5 open. Bands S +/- 0.5 ATR14.
Check completed M5 closes at NY quarter hours starting 09:45, ending 15:00.
First close strictly outside a band sets direction and an intent. One intent
per day, no retry/opposite switch. On SUBSEQUENT M5 closes up to and including
intent+30min, take first counter-direction bar (C<O) for long, (C>O) for short,
provided close still strictly outside same band. Cancel immediately if any
completed close re-enters the band; otherwise expire after 30min.
Entry at NEXT M5 open, never same-bar closing price. If next open re-enters
the band, cancel rather than create a stale trade. Protective stop exactly S;
no moving/deferring stop, TP, trailing, averaging, or martingale. Exit at stop
or 15:55 M5 close (16:00); gap through stop fills at adverse bar open.
Check stop on entry bar too. Only one stop and no TP avoids intrabar order
ambiguity, but OHLC is NOT proof of executable stops, especially ASK short.

## Accounting and costs
Report gross points, conditional 2-point total round-trip friction (base),
conditional 5-point total RT friction (stress), and break-even RT points.
These friction assumptions are NOT measured historical spreads/fills. Current
broker commission metadata is recorded separately; no commission guessed as
historical fact. No overnight swap intended; no dividend/financing inference.
R = net points / actual entry-to-stop distance. One fixed risk 1% of equity;
independent $1000 account at start of each yearly segment, no deposits.
Quantize contract units DOWN to current broker minimum/step (API volumes/100),
reserve friction in risk sizing; skip if below minimum or notional > equity*5.
5x is an illustrative notional cap, NOT confirmed margin availability. Report
ideal fractional and rounded-account results separately; sampled bar-close
equity drawdown with intrabar adverse-range diagnostic, not tick-exact equity.
Account projections conditional on USD quote/account, 1 unit = $1/point.
No execution approval implied and no production candidate from OHLC alone.

## Evaluation before changing parameters
Exploration 2024-2025; locked retrospective confirmation 2026. Not prospective
unseen data. Report every year, all sessions/no-trade/missing coverage. 5000
bootstrap resamples of consecutive 5-session blocks, seed20261010, for net
mean points and mean R (include zero no-trade days; omit unknown sessions).
Cheap gate requires >=100 confirmation trades, >=95% complete scheduled
sessions, positive stress profit each year and positive 95% lower CI of 2026
stress mean points. Below-minimum sizing and return concentration disclosed.
Costs/margin/full tick-path verification remain separate mandatory gates even
if cheap gate passes. No post-result parameter/pair/period cherry-picking.
Raw read-only broker caches local and gitignored; sanitized result retained.

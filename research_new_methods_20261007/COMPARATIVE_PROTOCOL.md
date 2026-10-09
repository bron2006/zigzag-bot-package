# Fixed comparative screen v1 — 2026-10-09, before history acquisition/results

Research only, not production replacement, no orders/refresh/deploy/executors.
Fixed universe EURUSD, GBPUSD, USDJPY, broker M5 history2024-01-01 through
2026-10-07 inclusive (end2026-10-08UTC). Early2024–2025, final2026. Final labels
not evaluated until rule/engine tests pass and early report exists. Some2026
fragments and2025 EURUSD were previously studied: NOT blind prospectiveOOS.
No hyperparameter/threshold/pair/session/holding-period searches, no new candidates
after results. This compares three fixed normalized rules over longer history,
not rerunning the old25-cross six-week hour-momentum/opening/failed-breakout test.

Session08:00–16:00UTC, exactly96 contiguous M5 bars; exclude incomplete sessions.
Indicators restart after any missing M5 interval, warmup60 completed bars. ATR14
is arithmetic mean of causal true ranges; EMA10/EMA50 adjust=False. Past20bar
range/mean excludes current candle. Exactly ONE first eligible signal per pair,
UTCday,rule (whether favorable or not); no replacement later in day. Rules:
1.trend: EMA10-EMA50 >=ATR and close>EMA10 =>BUY; <=-ATR/close<EMA10=>SELL.
2.breakout: close>maxHigh of previous20completebars=>BUY, below minLow=>SELL.
3.reversion: close-prev20mean>=2ATR=>SELL, <=-2ATR=>BUY. NoVWAP computation.

Decision completed candle i, delay one complete M5 candle; modeled entry Open(i+2),
exit Close(i+2) after300s. Require contiguous timestamps signal..exit, no interpolation.
All outcomes close at or before16UTC; no overnight, TP/SL, martingale or compounding.
Price movement divided by signal ATR (units ATR, NOT fixed-risk R). Forex proxies:
roundtrip cost=max(.22ATR,2pips), stress=max(.44ATR,4pips), EUR/GBP pip=.0001,
USDJPY pip=.01. These include illustrative spread/commission/slippage allowances,
NOT actual broker fees/fills/BIDASK. Report gross too; no executablePNLclaim.
Binary separate close-direction proxy, fixedstake1, .70/.80/.90 assumedpayout,
flat assumedrefund; NOT actual Binomo quotes/settlement. No deposit return claim.

Controls same observations: alwaysBUY,alwaysSELL,opposite (diagnostic only).
Final per-pair and pooled results ALL reported, no winner-pair filtering. Common
day axis all pairs, circular moving blocks of10 observed session dates,4000draws,
seed20261009; family-adjusted98.333% intervals for exactly3strategy hypotheses.
Net/stress/binary outcomes paired with baselines on same timestamps. Gates:
final>=300decided observations and>=100selected UTCdays; positiveearly mean;
forex stress loweradjustedCI>0 and pairedstress superiority over BUY/SELL both>0;
binary .80 loweradjustedCI>0 and paired .80 superiority over BUY/SELL both>0.
Positive forex pooled stress mean in at least2/3 pairs / binary positive .80mean
in at least2/3 pairs. Failure not repaired by tuning/inverting. Passing only
justifies historical quote/venue confirmation, NOT paper/real deployment yet.
No shortlisted candidate=>explicit stop recommendation for THIS three-rule search,
not a universal proof that no trading strategy can work.

Official historical interface: https://help.ctrader.com/open-api/messages/

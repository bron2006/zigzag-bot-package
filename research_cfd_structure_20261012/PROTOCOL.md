# Fixed CFD price-structure screen, before outcomes

Research only. Old strategy and production entries remain OFF. No model, VWAP,
orders, DB access or cloud changes. These mechanisms overlap broad breakout /
reversion families previously tried; they are NOT independent discoveries.
The new experiment is H1 FX structure with actual stop/target M5 path, unlike
earlier short-horizon direction bets. Do not call it a validated new strategy.

Existing cTrader midpoint M5 EURUSD/GBPUSD cache 2024-01-01..2026-10-07.
Both pairs fixed for USD quote/account safety, no winner selection. Already
studied history, not unseen holdout. Early2024-25, later2026 separately reported.
Only full twelve-bar UTC H1 candles; reset indicators after any missing hour.
Warmup24hours; arithmeticATR14 includes completed current bar, prior24range
excludes it. Decisions at completed H1 closes09:00..15:00UTC; entry next M5
Open at decision time, no use of that future bar to decide an entry.

Exactly THREE frozen rules:
1. channel24: close outside previous24H1 highs/lows, direction of break;
   stop2ATR, target3ATR.
2. failed24: H1 extreme crosses prior24range and closes back inside with
   directional candle, stop beyond signal extreme by0.1ATR, target priorrange
   midpoint; require net reward/risk>=1.5 at modeled entry for each cost scenario.
3. compression: completed07:00UTC H1 width<=0.75ATR; later completedH1 close
   outside that known range, stop2ATR, target3ATR.

First intent per pair/day/rule retained even if subsequently invalid/missing.
Across both pairs choose earliest intent eachUTCday, alphabetical tie, and
reserve whole session to16UTC, independent of outcomes. No later retry/overlap.
Stops checked on every M5: adverse gap at Open, stop-first if both SL/TP touched,
target gap credited only at target. All positions flat by16UTC; unknownpath
not given zero profit. Historical bids/asks/fills not available: CONDITIONAL
USD calculation only; 2pip roundtrip base /4pip stress include assumed all-in
spread/commission/slippage, not actual broker fees. No overnight swaps needed
under this session assumption. Finite separate1000USD balances perarm, risk0.5%,
min/step1000 units,max1e7,5x notionalcap (assumed FX size terms, not margin model).
No deposit/reset/martingale; realized cash drawdown, not liquidation estimate.

AlwaysBUY/alwaysSELL controls same scheduled intents/stopdistance/targetmultiple,
fixed daily reservation. Report all rules, pairs, years, scenarios and controls.
Daily netR 10-day circular block bootstrap4000draws, fixed seed20261012,
98.333% CI correction for this3-rule batch ONLY, not all prior research.
Gate: early and late stress netUSD positive; late>=100trades and>=100days,
zero unknownpaths, lower netR CI>0, paired superiority over bothcontrols CI>0.
No best-pair/date/parameter filtering or tuning after results. Passing justifies
new prospective PAPER validation, not real orders or profitability promise.

Research context, NOT replication of futures portfolio results:
https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum

Implementation audit amendment, after first complete run: independent Decimal
endpoint subtraction found three one-cent ties caused by float subtraction
before money rounding. Preserved first report; corrected money calculation
ONLY to Decimal endpoint arithmetic and reran unchanged rules/data/costs.
No parameter or strategy selection changed. Early/later phase accounts are
separate diagnostic1000USD runs, NOT a continuous deposit or production reset.
Early has one missing-path intent per channel/failed family; balances are
conditional on observed paths and cannot prove executable total profitability.

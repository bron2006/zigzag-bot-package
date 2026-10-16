# EURUSD M15 walk-forward v1, frozen before fitting/outcomes

User supplied revised experiment plan, asks progress rather than more report
iterations. Offline research only: no DB, broker, credentials, orders, deployment,
old scanner activation, original pkl replacement or cash reset. Existing cached
cTrader EURUSD M5 Jan2024..Oct7 2026, complete M15 derived from exactly three
aligned M5s only. All positive finite valid OHLC, deduplicate identical rows,
reject conflicting duplicates; no interpolation. Record hashes now; legacy
manifest lacks acquisition hashes, present hashes not proof of original integrity.

This is NEW monthly refitting of original LightGBM FAMILY and five indicators,
not validation of the unchanged old pkl or its original training implementation.
Original model100trees,31leaves,.1learningrate,minchild20,seed42; freeze these,
other LightGBM defaults, n_jobs2, deterministic/force_col_wise. Class1 explicitly
UP, class0 DOWN, no historical BUY/SELL inversion. No tuning/selection of folds.
Original binaries only SHA-recorded, never loaded/overwritten by this script.

Features ATR14/ADX14/RSI14/EMA50/EMA200 from pandas_ta, causal continuous segment
after each missing M15 reset, first200bars discarded. NOT exact production's
rolling300-bar reseeded EMA; preprocessing change disclosed as research variant.
All features finalized at bar close. Target entryOpen after ONE FULL M5 delay:
decision=M15start+900, entry=decision+300, exit final M5Close at entry+900.
Exactly15minutes modeled hold. Label sign(exit-entry), ties excluded from fit.
Both entry and all3pathM5bars must exist, otherwise excluded and counted unknown.
Labels need target_ts STRICTLY BEFORE test month boundary. Training-only scaler.
First testJan2025 uses2024 only; monthly expanding fits throughOct2026partial.
22monthly folds, trainingmin1000. Training/test naturally separate by time;
target-end purge prevents overlap, no shuffle, train-only score/feature choices.
History already researched, retrospective temporal OOS, NOT blind/prospective.

Fixed integer score=int(P(UP)*100), BUY>75, SELL<25, else no trade. No inversion
search. Two policies: all selected; selected AND ADX>=20. Single pair, scheduled
entries15minutes apart, fixed15min maximum holding => no overlap within policy.
Gaps unknown, not fake zero. Classifier diagnostic fixed-time proxy .8 payout
ties refund, NOT actual Binomo quotes/payoffs/account. No universal55% gate.

PRIMARY CFD conditional simulation: stop1.5*signalATR, TP2priceR, deadline15min;
entrybar stop checked, stop-first ambiguity, adversegap actualOpen, favorableTP
credit target. No trailing/martingale/overnight holds. Base2pip/stress4pip ALL-IN
RT assumptions, not historic actual quotes/commissions/slippage. Normalize net
pricePnL/(stopDistance+cost); raw2R TP need not net2R. No dollars/leverage/margin
or executablefill guarantee. AlwaysBUY/SELL/signal-candle-momentum controls on
exact same selected timestamps; each uses its own direction/stop outcome.

Report BOTHpolicies ALLmonths incl0trades; classifier accuracy, fixedpayoutproxy,
netR/PF/count, ambiguity, sessions and ADX<20/>=20 without selecting good groups.
Sessions at DECISION: London08-17Europe/London, NY08-17America/New_York withDST;
overlap own group, rest asia_or_offhours NOT a claim rest all Asian market hours.
Statistical tests pooled2025 and2026: 10calendar-day moving-block bootstrap10000,
seed20261015,64-cell familywise95%CI THISbatch only, not entire search history.
ADX policy improvement over unfiltered percommoncalendar-day sumR inclzero days
and paired advantage to controls. Gate: >=200known2026 signals, >=100eachyear,
stresssumRpositive2025AND2026,2026lowerCI>0, all2026controlimprovementlower>0;
filtered also requirespositive2026daily difference lowerCI vsunfiltered. Every
selected trade needs known path; unknowns fail gate. No live promotion on a pass.
Session/month patterns exploratory only; any later chosen filter requires new
independent validation, no switching current bot from a selected subgroup.

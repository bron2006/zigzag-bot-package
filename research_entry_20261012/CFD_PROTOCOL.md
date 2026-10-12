# Product clarified: USD CFD with stop, frozen2026-10-12 BEFORE results

Owner explicitly chose normal trading WITH STOP, NOT binary fixed-time bets.
Do not silently reclassify old binarydirection outcomes as actual CFDprofit.
New pure paper_cfd engine has no broker/DB/config imports or real-order functions.
Cached USTEC USDquoted histories2024..Oct7.2026, already studied (retrospective).
Reuse exactly3transparent rules and2entryrules, no new parameter optimization.
ONEOPENposition, risk.5%currentbalance, initial$1000, stop1ATR14, target1.5ATR14
(existing autotrader default1xSL/1.5xTP), sessionendflat, NOT15minuteexpiry.
Pendingintent occupies its waitinginterval, including latercancellation; new
intent not admitted until that decisiontime (or openpositionclose). Firstarrival
priority, no hindsight acceptance of overlapping waiting setups.
Implementation clarification above added AFTER first provisional replay found
missing pendingintent locking. Corrected replay rerun, no price/risk/indicator
parameter tuning; initial provisional output is not final validation evidence.
No new setup once within last30minutes (time insufficient to complete entry wait
before sessionend); indicator signals still generated from closed historicalbars.
Session09:30..16:00NY with priorvalidatedDST/holiday/earlydaycalendar, require78
M5bars. Missing sessions remain unknown, no interpolation. At signal computeentry
on subsequentbar, reject crosssession waiting, size BEFORE inspecting futurepath.
Exit stops on entrybar too, BOTHhit=>STOPfirst, stopgap=>adverseopen, favorableTPgap
=>targetonly, no ambiguity-resolving profit guesses. Reserve conditional2/5point
ALL-INroundtripcost in sizing. These are sensitivity assumptions NOT actualspread.
Size down to currentUSTEC min/step .1unit, max250units from confirmedcachedspec
(API100=1unit). Quote/accountUSDand1unit=$1/point conditional; historicalterms,
margin/ASKfills/slippage/swap/dividend/tickdrawdown not proven. 5xnotionalcap is
illustrativeNOT confirmedleverage. No averaging/martingale/lossrecovery.
ClosedUSDaccountledgercentrounded, independentbase/stress accounts perarm,
no deposits or yearresets, stop when capitalinsufficient. Report yearlysegments,
loss/win sizes, realizeddrawdown and ambiguousbarcounts, all12arms. Do not promote
to cloud or realorders from OHLC alone. Mainvirtualbinaryreport left unchanged
until separate persistentCFDpaperaccount+UI exists and is verified.

# Payoff-aware candidate, frozen AFTER failed direction-probability audit

New hypothesis motivated by actual goal mismatch: endpoint UP classifier is not
the same task as positive trade expectancy after stop, target, deadline, friction.
Research only; reused history, postdiagnostic candidate, NOT fresh confirmation.
Keep originalmodels/production/scanners/cash untouched, NO orders/DB/network.

Same EURUSD M15 cohort from run.py and22monthlyfolds, entryafterfullM5delay,
15minmaxhold/stop1.5rawATR/TP2rawR/stopfirst/adversegap. Two regressors predict
conditional NET R of BUY and SELL respectively. Traininglabel uses4pip ALL-IN
RT sensitivity; labels include zeroendpointmoves if fullpathknown. NoTP/SL
pathavailable => labelunknown, excludedfromfit, NEVER fakezero. Trainingtarget
endSTRICTLYbeforetestmonth; no label futureleakage. TwoLGBMRegressor L2,
100trees,7leaves,maxdepth3,learningrate.05,minchild200,seed42,n_jobs2,
deterministic, no tuning. Separatetrainingscale fitpastonly. No probability
score interpretation/calibration claim; expectedreturn is NOT guaranteedreturn.

Features fixedBEFOREoutcomes:5normalizedsources(ATR/Close,ADX,RSI,EMA50and200
distancesinATR), logreturns1/4M15, body/range, range/Close, ATR/prior48barATR
median, sin/cosUTCdecisionhour, London/NYsessionbinaryflags(DSTaware),
stresscost/stopdistance. Total15features. ATRmedian excludescurrent, resets
aftergap. No truevolumeororderbook claims: these were not acquired. Existing
200barcontiguous warmup limitations retained, notexactproductionrolling300.

Action choosehigher predictednetR if STRICTLY>0; equalpositivetieBUY, both<=0
FLAT. Economic zero gate predefined, no percentiles/thresholdsearch. Onepair,
fixed15minspacingguaranteesnooverlap; stopmayexit earlier,no reentry untilnext
scheduleddecision. Includeunknownselectedoutcomesascensored, gatefailsunknown.
Evaluate2pip/base and4pip/stress separately. No cash/notional/leverage/dollar
projection. Same-event alwaysBUY/SELL/lastcandlemomentum controls, neverreverse
afterresults. Report allmonths/predictioncounts,negativeandzeroactivity retained.

Gate SAMEpreviousdiagnosticrequirements: >=100knownin2025,>=200in2026,
stresspositiveeachyear, zero unknownselected, 2026positive64celladjusted
10calendardaybootstraplowerdailyR andpositivepairedexcessvsALL3controls.
Newcandidate is one extra arm, family64 conservativeforthisrunonlyNOTglobal
historicalselectioncorrection. No gatepass=>no activation. A passonlywarrants
freshprospectivequotes/fees/slippage/robustness, NOT live trading approval.
No changesof stop/horizon/featuresafterobservingthiscandidate'soutcomes.

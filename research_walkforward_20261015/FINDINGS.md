# Monthly walk-forward completed, 2026-10-15

User's revised expert report now calls for own-model evaluation. Implemented
actual22monthly LightGBM refits Jan2025..Oct7 2026, training2024 onward and only
targets strictly before each next month's start. No random kfold, threshold or
session optimization. NOT re-evaluation of unchanged originalpkl: new refits of
its model family with five sourceindicators and declared causal preprocessing.

Input206736actualM5 =>68890completeM15 =>36582feature rows after200bar warmup
which resets on EACH missingM15 includingweekends. This excludes many earlyweek
hours: NOT all-candle/all-session coverage or exact production rolling300EMA.
Training label15min direction from modeledentryOpen afterfullM5delay; classifier
labelNOTwhether2RTPbeatsstop. PrimaryCFDstop1.5ATR/TP2R/deadline15min plus2/4pip
RTassumptions; raw candle endpoints not actual broker/Binomo fills/payoffs.
Natural class1UP explicit, no legacyinversion. Onepair, nonoverlapping intents.
Historical data already researched: temporal heldoutfolds NOT blind prospective.

## Raw five-feature refits
2025:337selected,336known,1unknownmissingentry/path. Direction172/329nonflat
=52.28%; sevenflat. Base2pip -46.784R,stress4pip -79.675R.
2026toOct7:94selected/known,46/91directioncorrect=50.55%,threeflat.
Base -6.141R,stress -15.520R. Atfixedscore>75/<25 onlyJanuary92,February1,
April1; MaythroughOctober0. These are selectedsignals, not proof allforecasts
lackanypredictiveinformation or that a different threshold/horizon must fail.

ADX>=20:2025 218selected217known109/213correct;base -27.030R/stress -47.154R.
2026 29known15/28correct;base -1.711R/stress -4.335R. Fewer losses in sum is
partlyfewertrades, not validatededge. Common-day filtered-minus-unfiltered
2026stressCI[-.007777,+.228030]R/day includeszero. No supportedpositiveedge.
AllpoliciesgatesFAIL. Allmonths,sessions,controlresults retained, no good-session
postselection. Actual cost completeness/margin/USDaccountPNL unverified.

## Normalized five-source controlled follow-up
Separately frozen NORMALIZED_PROTOCOL AFTERrawresults, before its own outcomes.
ReplaceATRbyATR/Close and EMAlevelsby(Close-EMA)/ATR, retainADX/RSI. Samefolds,
modelhyperparameters/scoregates/labels/stopmath/costs, no otherindicatoradded.
Models/scalersrefitted, never normalize inputs into unchanged originalpkl.
Post-diagnostic search, NOT independent confirmation or preregistered before ALL
use of history.2025 70known30/69directioncorrect;2pip -12.993R/4pip -20.368R.
2026only2known(onecorrect),2pip -.764R/4pip -.995R. ADX2025 49known/18of48correct,
2pip -10.861R/4pip -15.143R;2026same2. GatesFAIL,nothingdeployable. Lessnegative
sum with drasticallyfewerentries does NOT establish normalizationprofitability.

## Verification / operational boundary
9newtestsPASS: prefix/futurepoison, gapwarmup, targetpurge, strictaggregation,
entrybarstop/stopfirst/adversegap/unknown/nettarget,sessionDST,normalizedscale.
Fullisolated712Python testsPASS; existingSQLiteALTER/mockfailurelogs notprod.
Originalpkl/scaler hashesunchanged; sourceprotectionchecks ineachrun.
audit.py independently usesDecimal to replay knownCFD netR andchecks22purges
perrepresentation; inputfeatures shared, not independentoracle oftheMLprocess.
No productioncode/flags/UI/DB/scheduler/cloud/orderchanges, no accountreset,
deployment orGitHubpush. GeneratedresearchJSONlocalignored, notsenttoowner.

Conclusion: monthlyrefitting, ADX20 and thisnormalizedrepresentation do NOT
rescue the fixedhigh-confidence15minconfiguration. No claim ML universally
impossible, originalmodel fullyreproduced, or all thresholds disproven. Next
diagnostic if pursued should record ALL forecast probabilities and calibration
versus prevalence before designing a NEW gate; not blindly lowerthreshold to
force entries or increase stakes. Any new candidate needs fresh validation.

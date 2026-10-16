# H4 affordability / dollar objective completed, 2026-10-15

Owneraskswhat tochange; actuallytestedonefrozen economic modification, not more
SL/TP/hoursearch. AttributionoldH4:356/381deadlineexits gross+38.522equalriskR;
20stops-20R,5targets+10R. Thusdeadlineexit NOTshownlossdriver. Overallgross
28.522R;fixed-equal-grossRiskbreakevenRT3.299pips, notknownfuturecostlimit.
Base1000USDledger211taken170minimumskips,gross58.7203USD,assumed2pip43.4000
USDcost=>15.3203USDnet. SameFROZENunitsbreak-evenRT2.706pips,2025 1.253,
2026 4.256. Costeffectnotonlyproblem, yearvariation substantial. Don'textend
timer merelybecause2Rrare:pastdeadlinecohortwaspositivebeforecosts.

## Concrete modification and result
FEASIBLE_PROTOCOLfrozenafterattributionbeforeoutcomes. SameH4/stop/TP/hold/
22folds, known-decisionclose/ATR1000USDprofilewith.5%risk/5xillustrativecap/
currentminstep1000units. Trainonattainablecohort only, two17featureLGBM
regressorsnetUSDlabel after4pipcost. Unknownlabelsnotzero; knownunattainable
entryquantityzerolabel. Separateactual-entrysizecheck, dynamiccashledger.
2046oldeligible→1526feasible(whole2024..Oct7 2026). min200trainingpredefined
(firstfold604),differentcohort/targetNOTisolatedcausaleffectorblindnewOOS.

2025 147knownselected,base-4.7329R/stress-11.5262R;2026 113known,base+3.5554R/
stress-2.7210R. All260selectedknown,0controlcensored. Basecontinuous1000→
998.2540USD,260taken0skipped,closed-balanceDD3.759%,2025end982.5664.
Stress1000→946.4835USD,254taken6size-skips,DD6.536%,2025end958.1447.
GateFAIL. OperationalaffordabilitybetterbutprofitNOTimprovedversusoldH4
base1015.3203/stress962.7664. DoNOTpromoteorrelabelasfixofprofitability.
No modelthresholdchanges/widerstop/newtimerafteroutcomes, no originalmodel,
cash,productionflags,UI,scanners/deployment/orderchanges. ReadonlyFlydiagnostics
belowONLY, no apprestart/remoteDB/modelimports orGitHubpush.

## Live read-only cost evidence, NOT historical repricing
flystatuscurrentimage01M4XFYXE6B0VYA2BCWAWVNEJE/machine8251e6c7073e48started.
PublichealthOct15~17:37UTCok/READY,TelegramACTIVE83prices2stale. InitialEURUSD
paperquotequeryempty becauseAPIrequiresbothsides<=5secold; subsequent8samples
allhadfreshquotessometimesskewed. DoNOTinferfeeddownfromemptystrictsnapshot.
No secretsorURLtokensprinted; residentHTTPread throughlightweightconfig-only
helper, no secondapp/model/Supabaseinitialization. LocalCLIauthalreadyavailable.

current_cost_probe.py:8bounded2secseparatedsnapshots,6sHTTPtimeouts,60sparent;
quoteage<=5secsANDsideskew<=1sec. CurrentOct14symboltariffsnapshot(pre-existing)
preciseTradingCommissionRate3e9/1e8=30USDpermillionUSD, feeRTassumesbothlegs;
mincommission0USD, pip.0001. OncurrentEURUSD~1.1214,commissionRTproxy~.673pip.
Recordedrepeatprobeaccepted3,rejected5,proxy.672864..672888pip(allaccepted
sampledspreads0). TheEARLIER8samplediagnosticshowed0..0.1pipspread butdidnot
enforce1secsideskewforeachsample. NOThistoricalaccountfeeverification, broad
spread distribution, executionfillprice, futureexitspreadorfulllatency/slippage.
cost_complete=false,historical=false,orders=false. DoNOTreplace2/4pipassumptions
withthese3samplevaluesorclaimnewprofit. No backgroundmonitor/automationstarted.
Officialcommissionprecision/typeverifiedhttps://help.ctrader.com/open-api/model-messages/.

## Verification
7newtestsPASS(feasibility4,currentquote/commission3). Full743isolatedtestsPASS.
IndependentDecimal520knownscenarioR/calculatedcashrowsmatched,maxRerror7.89e-14,
22foldpurgesandoriginalmodel/scalerhashesunchanged. Quote testsrejectstale/
asynchronous/unsupportedcommissiontype; no silentcommissionconversiontoother
assettypes. Data-onlyJSONlocalignored,nofiles/changedlists senttoowner.
Decision: rejectprofitcandidate, retainread-onlymeasurementtool. Futurecost
measurements ornewentryhypothesis require their ownvalidation; no promotion.

# All forecasts and payoff-aware candidate completed, 2026-10-15

User explicitly asks what toDO; implemented nextaudit instead of revisingreports.
SavedEVERYforecast eachrepresentation22719 across22monthlypast-onlyrefits.
2025:13742forecasts,13477nonflat,163flat,102unknown.2026toOct7:8977forecasts,
8786nonflat,118flat,73unknown. Flat/unknown excludedfromdirection/probability
metrics, retainedcounts; NOT trades, missing notzero. Warmupcohortlimitations
frompreviousprotocolunchanged, reusedhistory NOT independentprospective.

## Information audit
Raw2025 accuracy50.575%,past-onlymajority50.560%,AUC.509690;2026accuracy50.228%,
pastmajority49.192%,alwaysDOWN50.808%,AUC.504968. Raw2026accuracyadvantage over
pastmajority64cellblockCI[-.008683,+.031235]fraction includeszero; againstDOWN
[-.031261,+.015321] includeszero. Do notinterpretpositivepoint vsUP as proven.
Normalized2025accuracy50.382%,AUC.501150;2026accuracy49.590%,AUC.494923.
AllfourpairedBrierimprovementCIsnegative (modelprobabilitylosshigherthanpast-
frequencybaseline). Raw2026Brier.253472vsprior.250135; normalized.253072.
BrierreflectsbothcalibrationANDdiscrimination, NOT purecalibrationtest.

AUCuncertaintysupplementaddedAFTERseeingpointresults, notfalselypreregistered:
10calendardayweightedblockbootstrap10000,64cell95%CI. Raw2025[.495079,.524464],
2026[.487842,.520495]; normalized2025[.486655,.515905],2026[.477794,.513387].
Allinclude.5. No established rankinginformationunderthisaudit, NOTproofall
possiblefeatures/horizonslackinformation. DoNOTinvert orselectbestbucketafter.
Calibrationbins10fixedandmonthly/ADX/sessiondiagnosticsretained, notpromoted.
Highthresholdrefitpredictionsmatchsaved431rawand72normalizedselectedtimestamps
andprobabilitiesto1e-12; oldresultsNOTrewritten. Originalpkl/scalerhashesunchanged.
Referencehttps://scikit-learn.org/stable/modules/calibration.html warnsBrier
mixesreliability,resolution,uncertainty; henceAUCsupplementratherthanoverclaim.

## Actual different objective implemented and rejected
PAYOFF_PROTOCOLfrozen AFTER informationaudit before candidateoutcomes. Two
LightGBMregressors predictBUY/SELLNET R after1.5ATRstop/2Rtarget/15mdeadline
with4pipassumedRTcost. Expanding22monthlyfolds,purgetargetends,past-onlyscaler,
include knownflat-endpointpaths inlabels.15fixedcausalfeatures:5normalizedsources,
returns1/4,body/range,range/Close,ATR/prior48median,hourSinCos,DSTLondon/NY,
cost/stop.100trees7leavesdepth3lr.05minchild200seed42;no tuning.
ChoosebestpredictednetR STRICTLY>0 elseFLAT. Original36,582feature-rowcohort
unchanged,22,719testdecisions,0selectedALLmonths; bestpredictednetR-.067073.
GateFAIL(noactivity/no200testtrades), NOTprofitablebot/evidence abstention
modelperfectlyknowswhichhistoricaltradeswouldprofit. No livecandidate.
This is postdiagnosticresearch, notfreshconfirmation. No thresholdlowering,
stopwidening ornewfeaturesearchafteroutcomes. Historicalbidaskcosts unverified.

## Verification / boundaries
13newtests:8allforecastmetrics+1weightedAUCtie/multiplicity+4payoffcausality,
abstention,profitlabel-vsUPmismatch,unknownlabels. Fullsuite725expected; actual
completion recordedinCLAUDEafterrun. IndependentDecimal Brier/priorerrorsand
directioncounts/calibration-bin totals recomputedfromsavedforecasts bothyears;
22foldpurges bothvariantsandpayoffchecked. No sourcepkl/scalerchanges.
No app/DB/brokernetwork calls, credentialaccess, realorders, cloud/UI/scanner/
cashchanges, deploymentorGitHubpush. Existingunrelateduntrackedfilespreserved.
Do notsendownerattachments/changed-filelists. Resultsare research, not runtime
health assurance. Keep thisfailed15mincandidateoutofexecution; anotherhorizon/
informationfamily requires its ownfrozenprotocol, notposthocfixclaims.

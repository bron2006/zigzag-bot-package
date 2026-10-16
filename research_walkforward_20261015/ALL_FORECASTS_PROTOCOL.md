# All-forecast information audit, frozen before full forecast outcomes

2026-10-15, useraskswhat toDO. Complete the explicitlyproposed nextdiagnostic.
ResearchONLY, no DB/network/orders/executors/deployment/pklwrites/cashreset.
Reuse EXACT run.py dataset, original22folds/rawandnormalizedrepresentations,
hyperparameters, seeds, targetpurge and originalmodelhash checks. No new
thresholds, modelsearch, sessionselection, directioninversion or calibratorfit.
Sourcehistoryalreadyresearched, rawselected outcomesalreadyknown: NOT blind
confirmation or exact unchangedproductionbot. Warmupresets aftereachgap,
excludesmanyearlyweekhours; conclusions apply to THISeligiblecandlecohort.

Save EVERY forecast including neutral/highthresholdrejected, unknownpaths and
flatfuturemoves. Probability target class1=UP; class0=DOWN, tiesexcludedfrom
binarymetrics exactly as fitting, NOT silently countflat as DOWN. Unknownnot0.
P>=.5 diagnostic directionUPelseDOWN, NOT newtrading strategy/thresholdpromotion.
Past-only baseline permonth = positiveclassfrequency in THATfold's training.
Past-only majorityclass1 if prior>=.5 else0; alwaysUP/alwaysDOWN and50%probability
also diagnostic. Do NOT use testperiodprevalence as forecastingbaseline.

Pooled2025 and2026 independently: count, nonflat/flat/unknown, allforecast
directionaccuracy, majority/UP/DOWNaccuracy, ROCAUCpointestimate, BrierMSE and
logloss vsprior-only andconstant. P clipped1e-12onlyforloglossnumericstability.
PositiveBrierimprovement=(prior-y)^2-(p-y)^2, pairedaccuracyimprovement against
pastmajority, UP andDOWN at identicaltimestamps. Inaddition report monthly
andADX<20/>=20 andDSTsessiondiagnostics, no discovery/promotionofbestsubgroup.
Fixed10 probabilitybins [0,.1),...,[.9,1], meanP(UP), actualUPfrequency andn;
notclaimedcalibratedprobabilityoftradeprofit. Emptybinsnull, rarebinsdisclosed.
Scorehistogram relevant to WHY highthresholdfewsignals but notcausalproof.

10calendar-day movingblockbootstrap10000,seed20261015, sum pairedmetric /
sum observations perresample, includezerocountdays,64cellfamilywise95%CI for
THISbatchonly(notentireprojectsearch), finite-tailMonteCarlouncertainty.
Diagnostic evidenceflag requires BOTHyears>=1000nonflat, AUC>.5, lowerpaired
BrierimprovementCI>0 ANDloweraccuracyimprovementCI>0vsALL3directioncontrols.
Failure is NOestablishedinformationadvantageunderthisaudit, NOTuniversalproof
thatnoneexistsorpermissiontoinvert/retune. EvenpositiveflagNOTprofitability.
No tradingPNL simulatedhere; existing2/4pip stop-studyresults untouched.
Reproduced highthresholdselected p_up+timestamps MUSTmatchsavedbaseline
results within1e-12 andallfoldtrainingcounts identicalbeforeacceptingaudit.

Primary methodologicalreference:
https://scikit-learn.org/stable/modules/calibration.html

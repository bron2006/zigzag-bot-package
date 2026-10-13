# Frozen operational screen after uploaded-video frame inspection

Charts inspected from correct uploaded clip, including diagrams near35–60s
and example near85–90s. Bearish zone spans initialHigh→initialLow before
HH sweep→LL; limit at initialLow (lowerzoneedge). Bullish inverse, limit at
initialHigh (upperzoneedge). Shown stop beyond final sweep extreme (HH/LL),
NOT a tight stop at the first zone edge. Target2priceR before assumed costs.

Author leaves largebody, pivot definitions, anchor selection and expiry vague.
This screen is an explicit interpretation, NOT certifiedauthorstrategy.
Freeze before outcomes: two definitions, main body>=80% of H1range AND
range>=1.5prior14completeH1ATR; sensitivity body>=70%,range>=1.0ATR.
ATR uses only preceding consecutive completeH1; all60M1required.
Latest newlyclosedeligibleH1 replaces anchor and cancels unfilled priorlimit.
MissingM1 invalidates structure/pendingorders; gapsNOTfilled.

M1 strict1left/1rightconfirmedpivots (availableatrightbarclose). Alternating
pivots; consecutive samekind retain moreextreme confirmedpoint. Dual high/low
ononebar is ambiguous, resetsstructure. Track pivots afteranchorclose, not
onlyafterbreach: initialHigh/Low usually precedesfinalsweep. First boundary
sweep byHigh/Low armsopposite side. Samebarbothboundaries=>ambiguouscancel.
ForSHORT: H1pivot→L1pivot→H2pivot with H2>H1 AND H2at/afteruppersweep;
subsequentM1CLOSE<L1 confirmsstructure. LONGmirror. Limitknownonlyafter
confirmationclose, activefromnextM1. StopH2+.01 /L2-.01; ifconfirmationbar
alreadyviolatesstop, skip. No reusingpasttouches asfills. Oneorder/anchor.

Fillconditionalonmidpointpenetration>=.01; favorableopenfillcreditedonlyatlimit.
Ifopeningalreadythroughstop, cancelfillinvalidgeometry. Ifstopandtptouched
aftermodeledentryinsameM1, stop-first conservative. Entry+TPwithoutstop in
sameM1=>unknown sequence, not automaticwin. Missingpath=>unknown. Pending
atdataend=>pending, neverfakezeroPnL. No timeexit;6daycoverage capunknown.
No cashportfolio/sizing/marginfills/swaps; overlappingobservationsmayoccur.

ActualXAUUSD M1Jan1–Oct12 2026. EarlyJan–Jun; lateJul–Oct12. Newlyacquired
golddata notusedinpriorFXscreens, but selectedaftervideo, not independentlive.
Round-trip conditionalpricecost$0.50/$1.00 perounce, notverifiedbrokertariff.
2settings x2costs x2phases=>8cells. Day-blockbootstrap6000,10setupdayblocks,
familywise95%bounds usingconservative36-cellcorrection(sharedhelper)for8cells.
Positivegate main: stressmean>0/lowerCI>0bothphases,
late>=100closed andno unknowns. Stillneedsindependentforwardfillvalidation.
No liveNYrule/UI/history/cash change, no actualorders or notifications.

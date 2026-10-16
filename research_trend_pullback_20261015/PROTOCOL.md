# Deterministic H4 trend / H1 pullback, frozen before outcomes, 2026-10-15

Ownerexplicitlyaskschange/build ratherthanmore discussion. Implementone clear
entryrule WITHOUTML/score. Isolatedresearch, notactivatefailedstrategy inprod.
Existing cachedEURUSDcTraderM5Jan2024..Oct7 2026; priorstudiedhistoryNOTblindOOS.
MechanismrelatedtobroadEMA/pullbackfamiliesalreadyresearched, notindependent
newdiscovery; exactmultiTFstructuralentrybelow nottheoldM5EMA9/21batchrule.
No sweep/alternativeafterresults. Keepdata/execution/riskarchitectureunchanged.

TRUEUTC H1/H4complete12/48M5aggregation viaexistinghigher_timeframes; nofilled
gaps. Sameobserved-trading-barindicatorcarryacrossweekends,reset>7days,
200barwarmup. H1EMA20addedcausally. AtH1close08..15UTCweekday use latestH4
that is ALREADYclosed and <=8hoursold. H4EMA50>EMA200 ANDClose>EMA50 AND
ADX14>=20 =>LONGbias; inverse =>SHORTbias. ADX20isfrozenhypothesis notmagic.

TwoH1candlesmustcontiguous. LONG: priorred(C<O), priorLow<=itsEMA20;
currentbullish(C>O), currentCLOSE>priorHigh AND>currentEMA20. SHORTmirror.
Wicksalonecannotconfirm. Intentonlyaftercurrentclose. EntryatOpenafterone
FULLM5delay (decision+300). Stop=min(priorLow,currentLow)-.1signalH1ATR
forLONG,maxHigh+.1ATRSHORT. No movingstop orsignal-chasing. Target2priceR
fromACTUALmodeledentry, notfromsignalclose. Atdecision requirestructuralrisk
>=4*stressRTcost(.0004), feasible1000USD/.5%risk/minstep1000/5xillustrative
notionalcap. Recheckrisk/quantityatentry, wronggeometry/tiny/open-gap/belowmin
=>skipped, neverfuture-outcomefilter. Bothcostscenarios SAMEstressgateintents.

Oneopenposition, modelleddeadline4hoursfromentry (latest15:05=>19:05UTC),
noovernightroll. EarlyknownexitallowsnextscheduledH1signal, no forceddaily
trade/cooldown/martingale. Stopfirst,adversegapactualOpen,TPgaplimitcredit,
missingBEFOREexitunknown andhaltsarmtoavoidfakefutureflat; afterknownexitnot
unknown. Cost2/4pipALL-INRT scenarios NOTactualhistoricbidask/fee guarantee.
NetRnormalized(distance+cost),notnet2Rclaim. Bothbase/stresslogged; opportunity
selectionnotchangedbyfutureoutcomes/controlperformance. No realorders.

Report2024warmup-available/2025/2026ALLdays/months,counts(skipped,overlap,
unknown),TP/SL/deadline, PF/netR and1000USDcontinuousaccount2025..Oct7 2026
withactualmin/stepcurrentmetadata/conditionalrisk. 2024isdiagnosticseparate,
notmixedintoprojection. Existinghigher_auditledgerfullknownonly, noannualreset.
ControlsalwaysBUY/SELLandpriorH1direction SAMEintents/distance/4Hwindow;
independentcounterfactualobservationsmayoverlapnotfundedcontrolportfolios.
Thesecontrolsnotselectablealternativesafterresults. Allrejectedarmsretained.

Gate:>=50known2025AND2026,positive4pipnetRbothyears,zerounknownselected/
controlcensor,2026dailyRlower64cell95%CI>0 ANDpairedlowerexcessvsALL3controls>0;
stress1000ledgerend2025>1000ANDend2026>end2025. 10calendar-dayblocks10000draws,
seed20261015; CIsforbatchnotentireaccumulatedsearch/finiteMCguarantee. Gatepass
onlywarrantsindependentprospectivequote/costvalidation, NOT activation.
Failure=>reportasfailed/underpowered,no tweakedEMA/ADX/stop/sessionoptimization.

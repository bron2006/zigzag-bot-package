# True H1/H4 run completed, 2026-10-15

Owner explicitlyaskedrun, notanotherproposal. CachedcTraderEURUSD2024warmup/
training,22monthlyexpandingtestfoldsJan2025..Oct7 2026perarm. BothgatesFAIL.
TRUEUTC H1/H4candles12/48contiguousM5,notM15renamed. H1 complete17201,
H4complete4135. Indicator200OBSERVEDbarwarmup carriesacrossweekends(shortgaps)
instead ofoldM15reset-everygap; explicitpre-resultchange neededbecauseweekly
H1has<200bars. Therefore NOTisolatedcausalestimateofchangingtimeframealone.
No fabricatedpricebars; unexpectedmissingpathbeforeexitunknown. Indicatorgaps
>7daysreset. ReusedhistoryNOTfreshprospective/unmodifiedproductionbot.

Same15normalized/return/volatility/time/costfeatures, twoLGBMregressors perarm
predictNETR of BUY/SELL at4pipRTassumption; maxexpected>0 elseFLAT.100trees,
7leavesdepth3lr.05minchild50seed42,monthlypast-onlyscaler,targetendpurge.
min300train/50knownperyeargate forlowerH4frequency fixedBEFOREoutcomes, NOT
same200M15gate. EntryfullM5delay,SL1.5signalTFATR,TP2rawR,1H/4Hdeadline.
Noovernightrollwindow:weekdayUTCdecision>=01,planneddeadline<=20UTC. Same
nonoverlappingstrategy, no reentryuntilnextTFdecision. Stopfirst/adversegaps,
TPgaplimitcredit. Noorders/fees/margin/fillsguarantee,2/4pipRTillustrations.

## Outcomes, not dollar balances
H1:8241forecastdecisions,105selectedclosed(102in2025/3in2026),0unknown.
Base2pip:2025 -5.590R,2026 -1.063R. Stress4pip:-10.517/-1.187R.
H4:1372forecastdecisions,381selectedclosed(244/137),0unknown.
Base2pip:+3.784R/+6.854R,PF1.082/1.330. Stress4pip:-5.556R/-.0669R,
PF.887/ .997. PositiveH4basescenarioNOTrobustedge orpermissiontolive.
H42026base95%64celladjusted10dayblockCIdailyR[-.039915,+.094430],stress
[-.065311,+.066963],bothincludezero;allpairedcontrolCIsincludezero. GatesFAIL.
ManyH4exitdeadline(225/244in2025,131/137in2026), not381TP/SLresolvedtrades.
Allmodeledclosedpaths/controlpathscomplete, noambiguity. No favorablemonth
selection/modelthreshold/stopwideningafteroutcomes. Allmonths retained.

## Conditional1000USD illustration (NOT saved account)
AddedAFTERRresults forpresentation, notpre-outcomeperformancegate. Four
independentcontinuousaccountsfromJan2025, noyearreset, riskbudget.5%balance
includingRTcost, currentOct14EURUSDmin/step1000baseunits,notionalcap5x
illustrativeNOTconfirmedmargin. RoundingDOWN,belowminskipped, no forcedsize.
Actualhistoricalterms/bidask/accountfeesunverified. USDquotedPnLquantity*delta,
NOTnetR*constant5USD. Reportclosed-balanceDDonly, no intrabarliquidationproof.

H1 base1000→987.7244,84taken21size-skips;stress→963.2544,78taken27skips.
H4 base1000→1015.3203,211taken170skips;stress→962.7664,179taken202skips.
H4base2025ending991.6280 then2026ending1015.3203: doNOTclaimroundedcash
profitableineachyear merelybecauseunitRbasewaspositiveboth. H4stress2025
967.3630,2026ending962.7664. Conditionalwholeperiod+1.53%base/-3.72%stress,
NOTactualbrokerreturn orfutures backtest. Min-sizefilterchangeswhichtradesfit.
No projectbalance/accountreset or injectionofresearchprofitintowebstatistics.

## Verification
11newtestsPASS:aggregation/prefix/knownweekendcarry/delay/deadline/no-roll/
stopfirst/adversegap/knownexitbeforelatermissing/TPgap/netR/abstention,
roundedcash/yearcontinuity/minskip/unknown/overlap. Full736isolatedtestsPASS.
higher_audit.py independentlyDecimalreplayedALL972scenariooutcomes(210H1,
762H4),reasons/exitpriceschecked,maxnetRerror6.41e-14. All44foldpurgespassed,
rawinputhashesmatch,sourcemodel/scalerhashesunchanged. Features/sharedinput
notindependentoracleofMLlogicorhistoricalbrokerexecution. No localapp/DB/
broker/auth/cloud/UI/scannerchanges, no realorders/deploy/GitHubpush.
Userreceivesplainresults, no attachments/changed-filelists. Decision:no
activation ofeitherarm. No claim longhorizons universallyfail orH4isproven.

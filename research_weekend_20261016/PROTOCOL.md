# Fixed crypto weekend calendar screen, frozen 2026-10-16 before outcomes

BTC/ETH Binance SPOT H1 cachedJan2024..Oct7 2026. Notnewfunding/futures/account,
onlypriceproxyforpossiblefutureCFD. Previouslystudiedcache, NOTblindfreshOOS.
Hypothesis: weekendLONG has positiveunitreturn beyond ordinarysameweekLONG.
Onefixedweekendslot, no grid/bestasset/direction selection or refit.

Friday19:00UTCdecision after18:00barclose. ATR = arithmeticmean of14TR for
H1bars05:00..18:00, eachTR=max(H-L,abs(H-prevC),abs(L-prevC));prevClose04:00
required. All15sourcebarsstrictlycontiguous/closedatdecision. Stopdistance2ATR.
WAITentire19→20hour, actualFriday20:00Openentry. Stoponly(noTP), max48hours,
deadlineSunday20:00actualOpen. Checkentrybarandall48H1bars; stop-firsttrivial
withnoTP;adverseopen-gapactualOpen,normalstopfixedstop. RawOHLCunknownbidask.
Decimal12dpnumericalnormalization,notbrokerticksnapping/executablepricepromise.
Ifstopintrabarunknownhour,financingchargedthroughbarend(conservative1hupper);
gapstopchargedtoactualbaropen. Deadline48hexact. Oneposition/event/asset.
Missingbeforeknownexit=>unknown,NEVERzero;haltthatassetactualcandidate
afterfirstunknownbecausepositionstateunknown. No laterunfundedflatfiction.
No entry/endpointaftercachewindow=>pendingnotforcedclose,ifearlystopknown
mayclosebeforewindowends. EnumerateISOweekswhoseMondayisincachewindow;
lastweekfutureFridayentryoutsidecacheexplicitpending,note notobservedtrade.

Controls: LONGTuesday20→Thursday20 SAMEISOweek (Tuesday19decision/ownpastATR),
SHORTsameweekend/ATR. Controlsnotfundedportfolios, no rolloverpositions.
Independentgrosspriceproxy, base20bp/stress30bpROUNDTRIPofinitialnotional,
plusLONGfinancing20%annual*actualchargedhours/(365*24). Gross0friction/0carry.
Shortfinancing0conditional/unverified;NOTexchangefunding. Reportcostcasesall,
donotreinterpretspotshortasexecutable. No$1000CFDreturn/margin/minsizeclaims:
contracts/currentterms/conversionnotverified. No cashportfolio or realorders.

Report2024/25/26counts,unknown/pending,meanunitbp,PF,maxloss,heldhours.
Pairedknownonlyweekendminusweekday andweekendminusshort,explicitcensorcounts.
Bootstrapcircular10calendarweekblocks10000drawsseed20261016,meanofknown
eventreturnsratioofsampledsums/counts;pairedidenticalweekindices;16CIcell
correction95%(.025/16tails),NOTglobalpastsearchguarantee. Unknownfuturehalt
weeksnotfilled0. Gate>=30known2025AND2026,positivegrossANDstressmeanEACH
2024/25/26,unknown0,2026stressmeanlowerCI>0ANDpairedlowerexcessoverweekday
andshort>0. Pendingexplicitnotwins;bothassetsmustpass,notbestassetpromote.
NoDB/config/cloud/credentials/broker/executor/model/deploywrites.

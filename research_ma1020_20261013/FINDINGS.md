# Result — positives in some portions, no robust passing candidate

Uploaded MA10/20volumecryptovideo interpretedexplicitly, notauthor'sexactbot.
BTCUSDT/ETHUSDTpublicSPOT withtrueexchangebasevolume, LONGONLY. M15newcache
26880closedbarsperasset/H1existing6720perasset, commonJan1..Oct7 2026.
NoFXtickvolume substituted. SMA main/EMA sensitivity, with/withoutvolume
controls. Costs conditional0.20/0.30%roundtrip, notindividualbroker tariff.

All16armgatesFAIL; this does NOT mean every arm/period is negative.
All4M15volumeonarms negative inwholeperiod. StresssumR:
BTC/SMA-22.821(n86),BTC/EMA-13.113(n95),ETH/SMA-12.888(n102),
ETH/EMA-16.794(n112). BTCM15lateportionpositivebutearlyportionnegative;
ETHM15SMAlatealmostflatunderstress. No stablepositivebothphases.

H1volumeonstress whole:BTC/SMA+2.881R(n15),BTC/EMA-3.234R(n32),
ETH/SMA-1.344R(n27),ETH/EMA+0.727R(n28). BTC/SMAearly+4.052R,
late-1.172R(n4). ETH/EMAearly+1.351R,late-0.625R(n11). Verysmalllate
samples; do NOTpromotecombinedpositives asvalidatedstrategy. Some controls
alsopositiveinparts, notevidencevolumefilter uniquely addsreliableedge.
No strengthclaim fromrawROI/winrate alone, no copiedgreenbacktest selected.

One modeledpositionperasset/arm, skipoverlapuntilactualexit. No6daycensoring:
completepaththroughOct7, noforcedtimeexit. Missingpathunknownhaltsarm;
endpendingnotfakezero (theseactualselectedarmsallclosed). StopfirstOHLC,
adversegapcosts, currentvolumenotinbaseline, nextopennotconfirmationclose.
No risk-fundedcashsimulation/fill/orderbook/account proof. ReusedH1data,
newM15acquisitionnotforwardholdout; afterscreenindependentvalidationrequired.

Publicfetch firstReadTimeout, secondhard180sdeadline, thirdresumecachecompleted;
no credentials/account/networkbypass, boundedattempts/checkpoints. No parameters
changedafterinitialH1outcomes. 683isolatedPython testspass(7newtests).
No clouddeploy, strategyactivation, oldsignalsrestart, UI/cashmodification.

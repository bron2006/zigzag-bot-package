# MA10/20 + volume video interpretation, fixed before outcomes

Uploaded @io.usdt clip37.71s inspectedall5steps. Source: MA10 crosses MA20
up, highvolume, closeaboveMAs =>LONG; SLbelowlocalminimum, RR>=2. Frames
allowM5/M15intraday/H1/D1swing. SMA/EMA, highvolumethreshold, localminimum
and exitonrecross aren't specified. Explicit interpretation, NOTauthor'sexactbot.

Test Binance BTCUSDT/ETHUSDT SPOT longonly, actualexchangebasevolume, NOTFX
tickvolume/markklines. M15newpublichistory; H1existingpublicspotcache. Use
commonJan1..Oct7 2026closeddata, earlyJan–Jun/lateJul–Oct7. ExistingH1history
reused; M15newlyacquirednotindependentforwardtest. No privatekeys or orders.

MainSMA10/20, EMA10/20fixedsensitivity. Closedcross previousMA10<=MA20 and
currentMA10>MA20. Closeaboveboth. Volume>=1.5mean of20PRIORclosedbars,
no currentvolume inbaseline. StoplowestLowof10barsincludingconfirmation
minusoneprice tick=.01; nextbarOpen entry; fixed2priceR target (notnet2R).
No retest rule or extra patterns inserted. No forcedtimeexit/reverseentry.
Withoutvolume is negativecontrol, notsubstitute forauthor'svolumecondition.
Warmup40contiguousbars, resetgap. Gaps/pathmissingunknown; endhistorypending.
Use complete available path throughOct7, no artificial6dayholdingcap.
Amended beforefirstoutcome run: completecryptohistorydoesnotneedengineering
censoringusedinolderbrokercollector. Stop-firstambiguous,adversegaps.
One simulatedposition perasset/rule, overlappingcandidate skipped until actual
modeledexit; firstunknownhaltsthatarm untilend (don'tinventresolution).

Conditionalroundtripcost0.20%/0.30%entrynotional inclassumedfees+reserve,
notverifiedindividualBinanceaccounttariff. No fundedcash,slippage/orderbook/
fills/marginorconversionproof. NormalizednetR conditionalonly.
2assets x2timeframes x2MAtypes x2volumearms x2costs x2phases=64cells.
Fixed6000replicates10setup-dayblockbootstrap, familywise95%64cellcorrection.
Gate stresspositiveandCIlower>0BOTHphases,late>=100closed,nounknowns,
volumevariantmustexceedpairednovolumepermean(notcausalproofbyitself).
Anypositivecandidate mustgetfreshvalidation; no cloudstrategy/UI/cashchanges.

# Inverse fully-collateralized hedge PAPER approximation,2026-10-09

Owner explicitly allows research of actualexchangecrypto, not CFDmigration or
real money/API credentials. No order endpoints/account access/recurringworker.
Fixed BTCUSD_PERP/BTCUSDT andETHUSD_PERP/ETHUSDT, no otherassets/thresholdsearch.
Before pairedpriceacquisition/outcomes: interval2024-01-01..2026-10-07inclusive.
One independent hypothetical$1000 account perassetcase, NOT two fundedaccounts
or a$2000portfolio. Face900USD (9BTCcontracts100USD or90ETHcontracts10USD), rest
cashreserve; currentcontractfacepublicspec only, not historicaccountpermission.

Eachyearcase starts Jan1 01:00UTC, after onefullhour; ends lastavailablehour
23:00UTC preceding nextyear or08Oct2026. Skip Jan1 00funding, never retroactively
receive funding before modeledentry. Allpaired1hSpotOHLC andCOIN-MmarkOHLC exact
commonhourtimestamps. Entry uses markOpen, spotOpen — these are NOT actualfills;
no historicalBIDASK. Need a truefill/quote engine before any execution claim.
Collateral C=face/entryMark. Inverse shortBTC PNL=face*(1/currentMark-1/entryMark).
Markvalued combinedwealth=(C+PnLcoin)*spot+cash, not double-counting separate
longspot inventory AND samecoins used ascollateral. Basis effect explicitS/M.

Buy C plus entryfutures-fee coins suchthat postfee collateral C remainshedged.
Base assumedspotfee.10%perside andinversefuturefee.05%perside; stressdoubleboth.
Fee schedules NOT user's actualfees; entry spread/slippage absent, so cannot
call scenario executablePNL or claim costs complete. Onpositivefunding withdraw
and sellpaidcoins immediately; onnegative buyneededcoins fromcash; assumezero
latency/minnotional/withdrawrestriction andsame-timeconversionS/M. Convertfee
.10%ofcashflow (.20%stress). Do NOT retainfundingcoins as additionalBTCexposure.
Fundingtimestampfewms pastwholehour uses SpotOpenofthat1hbar aspriceproxy, NOT
observed contemporaneousquote. MissingmarkPrice at funding or gaps => yearcase
UNKNOWN, not0. 2026COINfunding gap30Jun08UTC alreadydetected; cannot report
complete2026hedgeprofit unless authoritative source explains/recovers thatrecord.

At hourlyOpen accountwealth computed fromMarkOpen/SpotOpen. Report initialcash,
minimumcash, lowestmargin/equitycondition at assumedmaintenance1/5/10%ofnotional,
actual observedhourlydrawdown, endliquidationfees, netcashflow/basis/fees separate.
Hourlyclose-only statistics NOT worstintrahourdrawdown or brokerliquidationaudit.
Unsupported current fee/leverage/eligibility/margin/custody assumptions explicit.
No training/OOSclaim (rates alreadyseen). No bootstrapedge/deploymentgate onthis.
If2024/25 fail aftercoststress, stopthisprofile; otherwise only qualifies for
next realisticexecution/operationalstudy, not automaticpaper/realworkerstart.
Sources Binance publiccoinMmarketdata andcontractFAQ, documented insearchreport.

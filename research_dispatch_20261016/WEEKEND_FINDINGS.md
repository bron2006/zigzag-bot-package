# Weekend hypothesis and independent diagnostics, 2026-10-16

Continued actual delegated research under owner's 'далі що?'. No scheduling or
permanent background-worker claim. One new BTC/ETH weekend LONG mechanism,
fixed before outcomes, paired with same-week weekday LONG and weekend SHORT.
No new exchange account/futures/funding business; Binance spot is only a price
proxy for possible future broker validation. Source methodology is not evidence
that this exact calendar trade should profit.

Jan2024..Oct7 2026 cache: exactly24264UTC H1bars/asset, strict native open/close
timestamp and OHLC validation, no duplicates/missing hour. Independent loader
reads original gzip/native JSON rather than trusting research-derived frames.
Native format/time semantics verified primary Binance market/klines docs:
https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/market
Current legacy file hashes do NOT prove original acquisition integrity, and
native OHLC are NOT executable historical bid/ask.

Friday19UTC decision, previous14H1TR/2ATRprotectivestop, full-hour delay to20UTC
entry, noTP, max48h toSunday20Open. Same-week Tuesday control own ATR, weekend
SHORT counterfactual. No thresholds varied after outcomes. All already-studied
history, NOT new OOS. No dollar-account/minimum-volume/margin claim.

Actual weekend observations52/52/40 perasset in2024/2025/2026 (144each,288total).
Zero unknown actual paths/controlcensor; one future FriOct9 calendar event per
asset is pending relative to cache, not an actual opened trade. Independent
audit includes weekday145/weekend144/short144=433closed perasset,866total;
4pending acrossbothassets/arms. All stop/gap/deadline prices/timestamps,ATRsource
causality,chargedhours,gross andcaseyearmeans match; gross discrepancies0.

Gross means bp2024/25/26BTC−12.3361/−.3705/−5.4079;
ETH+22.9525/+26.6361/+7.9223. Base20bpRT+20%annual proratedLONGcarry ETH
−5.9999/−1.7850/−21.3357;stress30bp BTC−51.2841/−38.4843/−44.6545,
ETH−15.9999/−11.7850/−31.3357. Conditional scenarios, NOT actualbrokerfees.
2026zero-costETHCI[−97.1180,+92.0636]bp includes0 evenbeforefriction. Allpaired
weekday/short excessCIsinclude0. BothgatesFAIL,notactivated;doNOTswitchto
posthocshort or claim every crypto/weekend implementation impossible.

CurrentOct14 BTCUSD/ETHUSD metadata shows NY-local maintenance breaks and
Friday3day swap settings; source contract values not historicalvalidation.
Proportional20%financing is sensitivity, NOT actualFriday3xswap/weekendcharging.
Per cTrader official docs, schedule intervals start SUNDAY00 in specifiedzone:
https://help.ctrader.com/open-api/model-messages/
Spot stops during a broker maintenance break are NOT known executable. These
venue/USDTUSD basis/fees limitations require real venue data before promotion.

## External live-calendar test failure found, not hidden

Full suite807 tests:806passed,1failed LiveCalendarParserSmokeTest against the
real tool.forex API. Standalone canary also fails. Root/agent bounded GETs at
Oct16~14:05..14:06UTC show штатнийfromOct15/toOct18 returnsHTTP200
{events:[],total:0}; shorterfromOct15/toOct17 returns4valid events/allTotal1457.
Emptyresponseis BEFOREparser. Repeatedemptyrangewithrequestno-cache stays
empty;responsesX-Vercel-CacheHIT/publicmax-age300/Age135. Observedrangespecific
upstreamresponse/cache; originbug/stalecache/providerpolicy rootNOTproven.
DoNOTlabelparserbroken,skipcanarytoforcegreen,orclaimprodhealthchecked.
No production news_filter/calendar/test change made. Existing30minfailclosed
code was inspected, NOT remotely verified to be active/currentlyblocking.

Eight new strategy tests and3nativeaudit testsPASS. Full external canary remains
a disclosed failure; separate local806testsubsetPASS,notfull807PASS. Thecanary
wasexplicitlyexcludedonlyfromthatverificationcommand,notdeleted/modified.
NoDB,
cloudhealth/deploy,Telegram/UI,models,cash,orders,GitHubpush or realfundchanges.

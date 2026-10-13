# XAUUSD H1 / M1 breaker — source definition incomplete

Source public TikTok @_crypto_hustler_/video/7597429143780871432, 94seconds.
Read native Russian ASR subtitles, not verified chart frames. Video download
403/unavailable; browser shows only Please wait. Never claim visual analysis.

Known source rules: goldXAUUSD. H1 candle with large body and small wicks,
mark its high/low AFTER close. Switch to M1. Breach first boundary, then
bullish low→high→lowerlow→higherhigh or bearish high→low→higherhigh→lowerlow
breaker structure; wait retest. Upper boundary breach leads to bearish breaker
and SHORT in shown example. Stop just beyond block, target2stop distances.

NOT yet specified adequately: numeric big-body/wick threshold, how to select
the H1 candle among many, M1 pivot confirmation, WHICH candle/price interval
is the breaker zone and WHICH edge gets limit-entry, stop padding, expiry.
Do NOT silently pick these values and call test the author's actual strategy.
Need source chart frames, ideally attached video around72–90seconds.

Update: correct uploadedvideo inspected2026-10-13. Visual blocker resolved;
numericselection/pivot/expiry conditions still absent. See TEST_PROTOCOL.md
for preregistered explicit interpretation and FINDINGS.md for boundedresults.
Originalnotesabove retained as acquisitionhistory, notcurrentvisualstatus.

Acquired actual demo cTrader XAUUSD M1, 2026-01-01..2026-10-12 (end13exclusive).
Allowlisted READ messages only; strict verifieddemo, no broker orders, refresh,
fallback symbol or shared live-app client. Isolated180sworker/210schild cap,
rate delay, immutable pages+hashmanifest, resumedcachesnotrewritten.
Local oldtokeninvalid; boundedREADONLYquery retrievespersistedactiveaccess,
no Supabasewrite/schema/configchange. No key/token logged or exportedaudits.

Data integrity audited before strategy coding: hashverify, fixed1e5OHLCdecode,
deduplicatedconflictsfail, clamprequestedwindow (brokerreturnsfull6000lastpage
evenearlierthanstart), no filledgaps. H1 requiresall60M1starts, incompleteexcluded.
This is acquisition/integrity evidence, NOT profitresults or a startedlivegold
test. CurrentNYobserver, oldflags, savedcash andUI unchanged.

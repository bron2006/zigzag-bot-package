# News continuation v1 — rejected

65 official BLS CPI/Employment Situation releases dated2024-01-01..2026-10-07,
each release header's actual date and08:30ET verified through official archives.
Local HTTP403 did not lead to guessed dates; used public official web retrieval.
Sources https://www.bls.gov/bls/news-release/empsit.htm and
https://www.bls.gov/bls/news-release/cpi.htm. Cancelled releases are absent;
November/December2025 andFebruary2026 postponed dates are retained as published.
FOMC excluded by the frozen protocol before seeing prices, not by returns.

EURUSD demo-only read allowlist fetched65 event windows, no orders/token refresh.
Rule frozen before price retrieval: follow first5-minute move >=1.5pre-eventATR14,
entry after1second, hold300seconds, first valid BID/ASK within5seconds, sides<=1s
old. All selected events have quote windows; early1 missing endpoint remainsunknown.
count100 trendbars can extend BEFORE requested lookback on this broker; rule selects
exact15 contiguous pre-event bars and exact release candle, not the entire response.
No quote paging truncation allowed; raw checkpoints immutable and hashed.

Early2024:24events,22selected,21known,12midpointwins/21=57.14%,95.45%coverage.
Observed-spread forex net mean+1.24286pip at illustrative .7pipcommission;
stressmean+.24286pip after additional1pip slippage,95%CI[-3.43333,+3.805].
Late2025–2026:41events,34selected/34known,100%coverage,12wins/34=35.29%.
Forex mean -4.85588pip inclspread/.7pipcommission,95%CI[-7.73875,-2.05566];
stressmean -5.85588pip,95%CI[-8.73875,-3.05566]. Already negative with commission
removed: gross observed-spread mean -4.15588pip. No executable fill/profit guarantee.
Binary midpoint proxy at assumed .80 payout: mean-.364706stakeunits,
95%CI[-.629412,-.047059]. NOT Binomo entry/settlement/payout observations.
Always-UP/DOWN baseline advantage gates fail. Fixed forex/binary gates BOTHFAILED.

Opposite-direction diagnostic late64.71% and stressmean+2.21471pip is NOT a new
approved strategy: choosing it after these returns would be post-hoc. Early
opposite stressmean-3.66667pip. Do not invert or deploy to manufacture a success.
Bootstrap4000 whole release dates (65 distinct dates), seed20261009. Limited
single-instrument/type sample; retrospective calendar knowledge, not prospectiveOOS.
No claim all news strategies fail: only this fixed first5min/next5min rule failed.

11newtests/102research tests pass. Independent separate bisect quote join and
manual ATR/eligibility/cost audit verified all65cachehashes and55knownoutcomes.
Original production model/scaler hashes remain93c526a9/c6aa64b1. No production
code/config changes, DBwrites, executors/restarts/deployments or real trades.
Supabase skill constrained token access to existing bounded read-only helper,
with no schema/RLS/auth modifications. VWAP remains retired.

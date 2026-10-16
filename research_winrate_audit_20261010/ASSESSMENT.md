# Read-only win-rate assessment, 2026-10-10

Request: analyze existing pair statistics and propose improvements/removals,
NOT implement/deploy/blacklist or change execution. DB snapshot taken at
2026-10-10T17:00:56.669309Z, repeatable-read READ ONLY transaction, 8s statement
and5slock limits, isolated child50s hard cap; rolled back, no schema imports.
Supabase and Supabase Postgres Best Practices instructions applied.

2980 signals in365days:2732 legacy unverified +55unknown +193measured.
30days248total;103wins/90losses=53.37%,55unknown=22.18%. No pending. Every
measured entry dated08Oct23:04:55–09Oct20:51:14UTC, effectively09OctKyiv,
one trading-day regime. 7d/30d measured samples identical, NOT a month of
reliable testing. Wilson95%46.33–60.27 assumes independence and is optimistic
for correlated same-day pairs; cannot claim stable profitable subgroup.
No ties or invalid measured prices. Exact local production aggregate functions
AST-extracted: totals/wins/losses match offline independent implementation.
At hypothetical fixed80%net payout, expectedunitstake=-0.03938. 90% gives
+0.01399,70% -0.09275; NOT actual Binomo PnL or cTrader spread-cost trading.
Binary80%break-even5/9=55.56%; directional winrate cannot establish CFDprofit.

Promising for MORE OBSERVATION ONLY: NZDJPY15/20=75%, CHFJPY19/29=65.52%,
USDMXN11/16=68.75%. None's individual Wilson lower bound exceeds55.56%,
even BEFORE multiplicity/day correlation corrections. Never promote to live.
Weak observation candidates: GBPCAD2/11=18.18%,GBPSGD0/5=0%,USDJPY2/7=28.57%,
AUDJPY13/29=44.83%,XAUUSD14/29=48.28%. Not enough per-cohort observations
for permanent exclusion under existing CLAUDE protocol(n>=200). CADJPY9/16
=56.25%,EURJPY6/11=54.55%,SGDJPY3/5=60% also inconclusive. EURSGD1/1=100%
has no selection value; EURUSD0measured/1unknown is NOT a losing pair.
XAGUSD6/10measured but19/29unknown(65.52%): first diagnose endpoint coverage,
not strategy verdict. Missingness mechanism unknown; never impute wins/losses.

190BUY vs3SELL. AlwaysBUY on SAME193endpoints would win102 vs model103;
model adds only one correct event(0.52pp), descriptive control not strategy.
Confidence80–84:63/125=50.4%,85–89:19/31=61.29%,75–79:21/37=56.76%; cannot
raise thresholds based on31selectedsignals or bypass existing matched-trade
checkpoint protocol. Pair×direction×session subgroups too small.

Historical actual Binomo207settled/253rows (105win/102loss,46errors), all DEMO,
12–21Aug2026, zero last30d trades, zero matched to new measured endpoints.
Recorded demo net=-18656.95 ACCOUNT CURRENCY units, NOT USD or audited account
statement. Old stake variations explain why winrate alone doesn't equalPnL.
Do not use old outcome generations to rank current model/pairs.

Verified code-level improvements (not applied):
1 web winrateRateClass uses>=50 green, misleading asprofitability. Label
direction accuracy, neutral when insufficient, separate actualprofit panel.
2 UI ranks top8 byresolved and labels resolved asnumberoftrades; resolved
includesunknown, so CADJPY22shown vs16measured andXAG29vs10. Show allpairs,
measured wins+losses count, unknownrate, horizon, date range, uncertainty.
3 executor uses get_pair_signal_outcome_stats(verified_only defaultsFalse),
while UI usesTrue. No actual30d discrepancy inthissnapshot because nolegacy
last30d, but contractual risk remains. Stake MIN_TRADES check usesresolved,
notdecided; CADJPY22resolved but16measured can falsely pass20threshold.
Insufficient evidence must never promote risk; payout thresholdmustactual.
4 entryreference inanalysis is latest candleClose, scanner preserves existing
price; exitreference uses retained broker-time bid/askmidpoint. It is a hybrid
candle-to-midpoint proxy, not publication-time executableentry. Version future
statistic using captured freshbid/ask+quote timestamp atsignalpublication,
keep modelreferenceprice separately, preserve old history as distinctcohort.
5 persist missing-endpoint reason/time/quotequality, actual endpoint timestamp
and bid/ask separately; do NOT widen targettimewindow to artificially repair
winrate. Resolver elapsed44–59sec afterdeadline is processingdelay, NOT proof
quotes sampled late: retained broker quotes are queried within5secwindow.
6 retain read-only shadow collection for weakpairs instead of deleting them;
no automatic flip directions, stakes boost, averaging, martingale or blacklist
based on one day. Fixed prospective preselected cohort validation needed.

No working code changes, apprestart, flags, real orders, networkbroker calls,
DBwrites, deployment, GitHubpush or watchlist mutations. Local diagnostics only.

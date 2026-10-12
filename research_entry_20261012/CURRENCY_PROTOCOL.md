# Fixed relative currency strength screen, frozen2026-10-12 before PNL

One genuinely different mechanism: rank CURRENCIES jointly, not each pair's
indicators. All26cachedFXpairs, synchronized completed M5 bars; require each
market's latest15bars contiguous and timestamps identical. No filling gaps or
dropping missing pairs to change graph composition. At signal close compute
log(C_now/C_12bars_ago): one-hour returns. Least-squares currency graph with
sumstrengths=0; connected graph mandatory. Strongest2currencies against weakest2,
take ONE available pair maximizing absolute fitted strength difference (ties
alphabetical). Global30min intent cooldown, independent of future entry/outcome.
Fixed one-hour lookback, no parameter search. No minimum profit-tuned threshold.
Existing .25ATRpullback+.75ATRinvalidation+.5ATRnochase+3barwait vs next-open
immediate control. ATR14 simpleTR, fifteen-minute expiry FROM actual entry.

Already-studied Aug25-Oct7cachedbrokerOHLC, RETROSPECTIVE, not fresh holdout.
NOT replication of BIS currency momentum horizons/universe/forward contracts.
Mid/bar direction paper80%payout with70%stress, flat$10, no actual fills/fees,
CFDprofitability, bankroll constraints or leverage claimed. ONEpair perintent
limits overlapping correlated FX bets in this diagnostic (maxwait15+hold15min).
Unknown paths never filled; strict input coverage and missing counts reported.
Immediate and pullback monthly/overall counts retained including losses. No pair
selection by historical winrate, no direction inversion after results.
200decided minimum and positive stress EACHmonth; pessimistic missing=loss,
daycluster bootstrap5000 seed20261012 lower with conservative accumulated169arm
correction (9model-entry+156transparent+2this+2directioncontrols). Actual complete
research history is larger; this correction is NOT a comprehensive statistical
guarantee. Passing warrants prospective validation ONLY, no production promotion.

# Normalized five-minute candidate v1 — frozen 2026-10-09

Owner explicitly authorized work. Research only: no production model replacement,
broker connection, token refresh, database writes, executor or deployment.

One pooled logistic classifier (C=1, lbfgs, max_iter=2000), with a training-only
StandardScaler. Fixed instruments EURUSD, GBPCHF, AUDJPY, existing M5 caches.
Eight price-independent causal features: returns 1/3/12 bars, candle body/range,
range/close, relative rolling volatility, distances from EMA20/EMA50 in volatility
units. Minimum 200 contiguous completed bars; reset features after missing bars.
Prediction at completed bar close; target next contiguous M5 close, exactly +300s.
Historical closes are proxies, NOT Binomo entry or settlement quotes.

Train before 2026-09-16 UTC, validation 16–22 September, final test from
23 September. Training/validation target timestamp must precede next boundary.
No shuffle, threshold search, model search, pair selection or iterative tuning.
Fixed confidence gate p>=0.55 or p<=0.45. Flat moves are refundable (zero payoff)
for hypothetical payout scenarios, separately reported and excluded from winrate.
Fixed stake=1, payout assumptions .70/.80/.90, no martingale or bankroll claim.
Compare always-UP, always-DOWN and preceding-candle direction on SAME samples.
Bootstrap UTC days pooled across symbols, 4000 resamples, seed20261009.

Minimum paper-candidate gate: final test >=200 decided signals across >=10 UTC
days, lower95% day-cluster payoff CI at payout .80 >0 AND lower95% paired
advantage over each baseline >0. Validation must also have positive mean payoff
at .80. Failure means rejected; do not relax gates after observing results.
Success authorizes neither real trading nor automatic deployment. This historical
interval has already been researched: retrospective chronological holdout, NOT
blind/prospective OOS. One period/three pairs do not establish generalization.

Source: https://scikit-learn.org/stable/common_pitfalls.html (train-only pipeline).

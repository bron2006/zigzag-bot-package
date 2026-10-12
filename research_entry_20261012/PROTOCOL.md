# Fixed entry comparison v1, 2026-10-12

Frozen before calculating this comparison. Local research only; no production
strategy mutation, database writes, orders, model retraining or old-balance reset.
Reuse cached broker EURUSD/GBPCHF/AUDJPY M5 bars from model-contract diagnostic.
These data have ALREADY been investigated: retrospective, not an unseen holdout.
Use current production feature function on trailing300 COMPLETED bars (>=250),
unchanged model/scaler. Single M5 leg ONLY, score>75 SELL/<25 BUY, integer score.
Not a replication of full live two-timeframe/news/drift filtering. Direction
semantics cannot be proven from model metadata alone. No picking best mapping.
At most one common intent every30min per instrument; no overlapping opportunities.
Every qualifying intent is included before checking future price availability.
ATR14 simple mean TR from latest completed14bars; require uninterrupted300bar
feature window. No interpolation across market/data gaps.

Three fixed arms: next M5 open (control), open after one M5 wait (delay control),
pullback-confirm. Signal time=completed bar end. Pullback .25ATR against direction;
subsequent completed candle must move in signal direction and beyond previous
close, still not past original anchor. Invalidation .75ATR against direction,
no chase .5ATR in direction. Maximum3 subsequent completed bars; next open entry.
Gap outside invalidation/no-chase zone cancels. Closes only, no assumed intrabar
touch/fill sequence. Unknown data is never counted as strategy skip or loss.
Settlement fifteen minutes FROM ENTRY, final third held bar close.

Hypothetical binary80% net payout, flat$10 stakes, exact-price equality refund.
NOT actual broker payout/fees/slippage or CFD return. Display unit profit per
common intent (skips0, unknown bounded[-1,+.8]), per-trade accuracy and coverage,
all instruments and monthly segments, no post-result parameter optimization.
No compounding, bankroll limits or executable balance claimed. Promotion requires
separate prospective data; this diagnostic alone cannot authorize deployment.

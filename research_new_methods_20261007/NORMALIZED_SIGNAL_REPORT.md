# Normalized candidate v1: rejected for deployment

Implemented and trained an isolated normalized five-minute logistic candidate.
9980 nonflat training samples. Later validation: 27/48 correct (56.25%). Final
chronological holdout: 47/81 correct (58.02%), 83 selected including two assumed
flat refunds, 10 UTC days. At assumed payout .80, mean payoff .04337 stake units,
day-cluster95% CI [-.1175,+.3519]. At .70 mean is negative (-.01325 units).
81 selected BUY and2 SELL; paired advantage over always-UP CI [0,+.1286],
over always-DOWN [-.0497,+.792]. No established advantage over both baselines.
Minimum200 decided test samples not met. Frozen gate FAILED. Do not lower
threshold, choose a winning pair or overwrite production based on this result.

This is historical cTrader close direction, not Binomo settlement; payout and
flat-refund policies are assumptions. No broker-price divergence, execution
delay or actual payout measurements are available. Data was previously researched,
so it is NOT blind prospective validation. Training-only scaling follows
https://scikit-learn.org/stable/common_pitfalls.html. Eight normalized features,
causal prefix invariance, gap reset and split-target purge are executable tests.
Original production model/scaler hashes unchanged. No orders, DB writes,
executor starts, cloud updates or restarts. Candidate is saved only in ignored
local research artifact with production_allowed=false and status=rejected.

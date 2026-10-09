# Frozen model contract diagnostic, 2026-10-09

No retraining, orders, token refresh, deployment, or production setting changes.
Original model/scaler and analysis._prepare_features are reused unchanged.
The old 2025 heldout is NOT a new validation dataset. Use broker M5 history
2026-08-25 08:00 UTC to 2026-10-07 16:00 UTC, after the documented training data.
This interval was already studied for VWAP: this is retrospective, NOT prospective OOS.

Fixed four arms, before calculation: EURUSD M15 (original instrument/timeframe),
EURUSD M5 (timeframe transfer), GBPCHF M5 (similar price scale), AUDJPY M5
(different price scale). No pair selection or threshold optimization after results.
M15 derives only from three consecutive complete UTC-aligned M5 bars.
Features use the exact current 300-bar rolling window (minimum 250 at startup).
Only completed bars are used. Common target: close at +15 minutes after the
prediction bar closes. No interpolation through missing bars/weekends.

Fixed thresholds: integer score >75 or <25. Evaluate documented original
class1=UP mapping and current inverted mapping on the SAME observations,
not selecting the winner for deployment. Report all-bar accuracy, thresholded
accuracy, always-UP/DOWN baselines, day-cluster bootstrap intervals, ties and
unknown future endpoints. Compare feature range with original first11040 rows.
These are classifier diagnostics, NOT the complete current two-timeframe,
news/session/cooldown/drift filter strategy and NOT executable PNL.
Bars lack historical ASK/spread/slippage: no profit claim or execution gate.
An above50 rate without beating direction baselines is not evidence of edge.

# Frozen model diagnostic — completed 2026-10-09

Historical broker quotes 2026-08-25 to 2026-10-07, after documented training.
Retrospective classifier diagnostic, not prospective OOS or full live strategy.
All four arms use completed bars, exact current rolling features, unchanged
model/scaler, fixed score thresholds and a common15-minute endpoint.
No quotes were synthesized across gaps. No orders or token refreshes.

| Arm | Decided threshold signals | Original class1=UP | Current inverted | Always-UP / DOWN on same observations |
|---|---:|---:|---:|---:|
| EURUSD M15 |404|49.01%|50.99%|49.01% /50.99%|
| EURUSD M5 |1713|49.04%|50.96%|48.63% /51.37%|
| GBPCHF M5 |126|57.94%|42.06%|58.73% /41.27%|
| AUDJPY M5 |3315|51.01%|48.99%|49.41% /50.59%|

Original mapping day-cluster95% intervals: EURUSD M15[43.69,54.55]%,
EURUSD M5[46.09,52.25]%, GBPCHF[47.11,68.94]%, AUDJPY[48.84,53.25]%.
Paired excess over always-UP intervals include0 in ALL four arms.
No supported model advantage; do not choose a pair/mapping after inspecting
these results, or advertise57.94% GBPCHF without its58.73% simple baseline.

Feature-range violations relative to original11040 training rows:
EURUSD M15:4.13%, EURUSD M5:61.62%, GBPCHF M5:49.82%, AUDJPY M5:100%.
EURUSD within the original timeframe/price scale still does not show an edge.
Thus feature-domain mismatch is a real risk but does not by itself explain
away the model's weak results. Reverting the timeframe is not a demonstrated fix.

Important limitations:
- Raw historical bars provide no historical ASK/spread/commission/fill data.
  There is no executable PNL/net profitability conclusion.
- Live bot also uses M1/M5 or M5/M15 confirmation, calendar, drift, cooldown,
  and session filters. Those are NOT replayed in this classifier diagnostic.
- M5 observations overlap15-minute targets. Bootstrap resamples UTC days,
  not independent trades; cross-day dependence may still remain.
- Different timeframes have different warmup and sampling frequency.
  These are not paired arms at identical timestamps: no causal estimate of
  the effect of changing timeframe is claimed.
- Inputs were already used in VWAP research. No fresh prospective validation.
- Current feature computation is reused on each rolling window, rather than
  assuming the unknown historical preprocessing pipeline is identical.

Decision: no model replacement or live BUY/SELL switch justified here.
Stop treating a higher headline rate than50% as sufficient validation.
Any next candidate must first beat direction baselines on a frozen time-split,
then pass historical execution-cost checks; do not deploy based on this screen.
Five new anti-leakage/gap/mapping tests passed;82 total research tests passed.
Model93c526a9... and scalerc6aa64b1... hashes unchanged after inference.

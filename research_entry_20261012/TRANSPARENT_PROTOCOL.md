# Fixed transparent-direction screen v1, 2026-10-12

Frozen BEFORE this screen. All cached FX M5 histories in vwap_replay_m5, sorted
symbol order (exclude fetch_status, no post-result pair selection). Already
investigated Aug25-Oct7 broker data, retrospective NOT independent holdout.
No model, training, parameter search, direction inversion, database/network calls
or orders. Additional screen counts toward cumulative research selection, not
a fresh statistical discovery. Previous24-family screen also tested breakouts
with different exits: this new fixed15minute test is NOT an independent family.

Completed M5 bars only. EMA50, slope5bars, prior20bar high/low excluding current,
ATR14 simple TR mean. Buy when close breaks prior high, above rising EMA50,
body close-open>=.25ATR; symmetric short. Gaps reset70bar warmup and indicators.
Use all eligible intents with30minute common cooldown, fixed BEFORE future path
inspection. No symbol normalization artifacts: scaled prices give same decisions.
Two arms: immediate next open control, previously fixed pullback_confirm (.25ATR,
invalidation.75ATR, no-chase.5ATR, max3completedbars, next open). Fixed15minutes
FROM ENTRY. No simulation of bid/ask fills, CFD TP/SL, margin or compounding.
Flat$10, hypothetical80% payout and70% stress; exact equality refund; unknown
data stays unknown, bound at loss/win, skipped has zero. Per-symbol and months
reported for ALL arms. Do not pool into one bankroll or rank by winrate alone.

Cheap rejection screen: >=200decided, unknown fraction<=5%, stress PNL>0 in EACH
observed monthly segment, and95% one-sided family-adjusted day-cluster bootstrap
lower mean per common intent>0 at70% payout under ALL unknowns treated as losses.
5000resamples, seed20261012, correction across ALL symbol/policy arms. Correlation,
small month samples and repeated prior research still preclude proof/promotion.
If gate passes it only warrants prospective validation, NEVER cloud activation.

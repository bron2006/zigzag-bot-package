# Frozen owner-defined NY range reclaim v1 — 2026-10-12

Observation only: EURUSD, GBPUSD, BTCUSD, ETHUSD. No real orders and no
changes to saved paper-account cash. Not a validated profitable strategy.

Range: literal 00:00–04:00 America/New_York, including timezone/DST changes.
Require all M5 bars; range high/low include wicks. After range completion,
first M5 CLOSE strictly below low arms LONG; strictly above high arms SHORT.
A later M5 CLOSE strictly back above low / below high confirms the respective
direction. Equality and wicks alone do not confirm. No opposite-edge filter.
Stop is the extreme of the entire breakout movement through the return bar.
One first completed setup per pair/NY date. No next-day setup confirmation.

Model entry at the following M5 open; gap through stop invalidates entry.
Target exactly two price stop distances from modeled entry. No forced time
exit: wait for stop/target, possibly overnight. Missing path is unknown, not
zero PnL. Ambiguous OHLC stop/target bars use stop first; adverse gaps count.

Conditional costs: FX 2/4 pips round trip; crypto 0.10%/0.20% of entry notional.
No actual fills, bid/ask, swaps, sizing, margin or executable-account proof.
2R is before costs. USD5 risk-unit illustrations are NOT account balances.
Historical results (if produced) use reused data, not untouched holdout.

Live rule activation is stored independently of the older three controls.
Pre-activation setups must not be inserted as new prospective trades.
The existing three failed/unvalidated control rules are unchanged.

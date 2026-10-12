# Initial fixed-rule falsification — 2026-10-12

Cached cTrader M5: 2024-01-01 through 2026-10-07, inclusive. Same historical
prices reused in earlier research: these are retrospective, not a fresh holdout.
EURUSD 206736 bars / 652 setups; GBPUSD 206653 bars / 648 setups.
One setup per NY date, independent observations; not a funded portfolio.

At 2-pip conditional round-trip cost, 2026 closed outcomes:

* EURUSD: 167 closed, 53 net-positive, profit factor 0.560, mean -0.298R;
  12 additional setups unknown and excluded from returns.
* GBPUSD: 173 closed, 41 net-positive, profit factor 0.398, mean -0.459R;
  10 additional setups unknown and excluded from returns.

Both earlier 2024–2025 portions also negative after assumed costs. Closed-only
10-observation-day block bootstrap 95% intervals remain below zero in each
pair/phase/cost arm. They do not repair missing outcomes, reused-history bias,
unmodeled swaps or simultaneous positions. Crypto not historically screened.

This exact definition is NOT evidence of a profitable strategy. Do not enable
real orders or funded paper entries based on this test. Live NY rule is an
explicit observational diagnostic to inspect actual range/reclaim sequences.
No optimized filters, changed dates or rescued parameters were added.

Path inspection bounded to six calendar days, matching collector coverage;
unresolved paths become unknown, not forced closes or zero PnL.

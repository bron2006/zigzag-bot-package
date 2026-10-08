# Partial-holding control, fixed before this comparison

This is a follow-up retrospective falsification check, not a blind holdout.
Original SMA200 rules, costs, prices and results remain unchanged.

Calibration: 2020-01-01 through 2023-12-31. Evaluation: 2024-01-01
through 2026-09-30. Each asset is calibrated separately, base cost 0.1% per side.

Two passive controls hold an initial fraction of the asset, leave the rest
in non-interest-bearing cash, never rebalance and liquidate at the end.
Fraction E = early trend time-in-position. Fraction V = early daily log-return
volatility of trend divided by full buy-and-hold volatility, clipped to [0,1].
These are initial allocations, NOT exact future exposure or risk matches:
the asset weight drifts and later volatility can differ. Report that limitation.
Use the same frozen fractions with 0.3% stress costs. No leverage or shorts.

Compare total return, annualized return, close-to-close drawdown and volatility.
Paired moving-block bootstrap: 30 calendar-day blocks, 10,000 replications,
seed 20261007. Estimate annualized mean daily log-return difference between
trend and each partial control on the late block. Same resampled dates for
all assets and controls. Four base-cost comparisons use simultaneous
Bonferroni 95% coverage (individual 98.75% intervals). Stress is descriptive.
This conditional historical-path uncertainty does not establish future profits.

Do not promote to trading on descriptive positive returns. This check supports
further signal research only if both controls are beaten on both assets with
positive lower simultaneous interval bounds, positive stress returns and
shallower drawdown than each partial control. Failure means advantage remains
unproven, not that every possible trend rule is disproven.

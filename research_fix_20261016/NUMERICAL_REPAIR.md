# Numerical repair after initial outcomes, 2026-10-16

Coordinator's independent audit found a binary floating-point boundary error
in the BUY control for EURUSD base entry1788189000: a derived stop differed
from an exact quoted touch by approximately2e-17, changing stop/deadline.
The initial local audit verified actual chosen exits, NOT all control exits;
therefore its earlier successful report did not establish control correctness.

No strategy parameters or gates change. Frozen PROTOCOL preserved. Both actual
and all counterfactual control paths now use research_dispatch_20261016/
price_replay.py: Decimal prices and derived distance quantized to12decimals.
This removes floating residue far below input quote precision; it is NOT an
executable broker tick-size snapping model. stop-first/gap/limit/missing rules
are unchanged. Recompute results, confidence intervals and conditional cash.
Independent audit now replays ALL actual AND three control outcomes using
quantized Decimal distance and compares saved paired excess values. No old
shared simulator/artifact/runtime touched. This is transparently a numerical
repair discovered AFTER outcomes, not a newly preregistered strategy.

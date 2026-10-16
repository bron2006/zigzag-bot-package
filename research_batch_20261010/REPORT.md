# Completed offline batch, 2026-10-10

24 predefined rule configurations x USTEC/EURUSD/GBPUSD/USDJPY = 96 candidates;
3 controls per market = 12 controls. ORB5/15/30 and several other rules are
related: not 96 statistically independent strategies. No parameter search.
All rules retained, including losses, empty samples and skipped sizes.
Common stop1.5M5ATR14, target2R, session-end-flat. Conclusions apply to THESE
adaptations/shared exits, not all possible implementations of these families.

Protocol SHA377483b41cdfc07d57a586ea360397727cc9d0cbc8b45ffc845a32a915ac8bbe
fixed before batch PnL. Entire history2024-07.10.2026 is retrospective;
previously available data is not a new independent/prospective holdout.
Full-session coverage USTEC688/688, EURUSD715/723, GBPUSD714/723,
USDJPY714/723. No interpolation. Holidays/early closes excluded for USTEC;
FX weekdays with missing sessions counted. DST-aware London/NY windows.

53068 modeled candidate trades plus8487 controls =61555 total. Results:
46/96 have positive gross2026 sumR before costs;
7/96 have positive2026 rounded net at conditional base costs;
1/96 positive at conditional stress costs;
3/96 positive in every yearly segment at base costs;
0/96 positive in every yearly segment at stress costs;
0/96 have positive multiplicity-adjusted bootstrap lower expectancy bound;
0/96 pass the complete cheap gate. Coverage passes96, sample count73.

Largest2026 stress net: USTEC gap_fade, independent1000USD projection,
+27.76USD in2024, -23.86USD in2025, +81.64USD in2026 toOct7.
2026PF1.168,109taken,16minimum-size skips; balanceDD6.57%, sampledadverse7.31%.
Fixed1000 dailyUSD mean0.3617; unadjusted95%CI[-0.5467,+1.2913],
family-wise approximate one-sided lower=-1.0883. Not a validated winner.
Dollar outcomes conditional on current min/step, price-to-USD conversion,
5xnotional cap and ALL-IN hypothetical costs (FX2/4pips,USTEC2/5indexpoints).
Actual historical bid/ask, slippage, fees, account margin unverified. Real
equity/tick drawdowns and liquidation cannot be inferred. Stop gaps can
exceed1% sizing budget. No martingale/no real orders/no forward worker.

Core limitation uncovered: many short M5 signals have weak gross advantage
that disappears under all-in friction. This is NOT proof that every bot,
intraday strategy or other timeframe is unprofitable. Nor does a gross
winner or selected best2026 result justify deploying it.

Verification:11new synthetic testsPASS (indicator-prefix causality, reset
on gaps, next-bar selection/future perturbation, pip/USDJPY units, stop-first,
adverse gaps, conservative TP gaps, minimum rounding, notional/risk caps,
bootstrap reproducibility). Separate Decimal ledgers1296 match yearly
rounded/fractional balances and counts; primitiveOHLC replay61555 paths.
All recorded input-page hashes and frozen protocol match. Source/indicators
shared; no external independent oracle for all24signal rules. All modeled
entries additionally checked against poisoned future bars by the audit.

Decision: no deployment or promotion from this batch. Results archived locally
for next research; working bot, VWAP, tasks, cloud, DB, tokens unchanged.
No GitHub push. Do not send user files/links/tables. Next family research must
be separately predefined and disclose accumulated selection/multiple testing,
not silently optimize this batch or declare exhausted all possible strategies.

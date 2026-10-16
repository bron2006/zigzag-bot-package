# Position sizing overlays: risk reduced, edge not established

One shared $1000 EURUSD/GBPUSD account, Jan2025..Oct7 2026, no annual resets.
NOT the previous separate $1000-per-asset illustrations. Four fixed policies,
no parameter optimization; frozen selected opportunities and previously studied
history, NOT untouched out-of-sample. No live activation or account mutations.

| Policy | Base 2pip end USD | Stress 4pip end USD | Stress trades/skips | Stress closed DD |
|---|---:|---:|---:|---:|
| .5% per trade | 991.33 | 965.03 | 78/0 | 4.49% |
| .5% aggregate risk cap | 987.74 | 965.02 | 72/6 | 4.42% |
| halve risk after 2% drawdown, shared cap | 991.67 | 979.98 | 46/32 | 2.83% |
| .25% per trade, shared cap | 1004.33 | 994.59 | 22/56 | 1.09% |

Base conservative traded30/skipped48; stress22/skipped56. Strong apparent
protection is partly abstention due to minimum1000-unit broker size, not proof
of identifying better trades. Portfolio overlap is conservatively treated as
shared risk regardless of direction; no estimated correlation/hedge offsets.
Baseline max reserved risk .9445% base/.7958% stress; shared policies <=.5%
at entry. Gaps can exceed budget; no guarantee or mark-to-market DD claim.

All policy 2026 net confidence intervals span zero, none has strictly positive
lower paired improvement bound. Conditional 10day block bootstrap,10000 draws,
16-interval correction; adaptive cash path NOT re-fitted within bootstrap.
Do not promote the best-looking base policy using this same examined sample.

Independent Decimal checks: 467 funded simulated trades across eight arms,
cash/end balances, lot steps, aggregate notional5x and reserved risk constraints
match. Original240 scenario exit replays/input/model hash checks also pass.
Eight targeted unit tests cover future-outcome isolation, exit-before-entry,
shared caps, size reduction, minimum-size refusal and cash arithmetic.

Conclusion: implemented working research risk overlay, useful protection in
this historical sample; it does not turn the rejected entry strategy into a
validated profitable one. Production strategy, funds and real orders unchanged.

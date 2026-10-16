# Risk overlay comparison, frozen before overlay results

2026-10-15. Same previously studied EURUSD/GBPUSD selected closed trades;
no new signals, threshold fitting, or retrospective winner selection. This is
NOT fresh out-of-sample evidence. Existing opportunity eligibility was already
screened against a fixed $1000/.5% profile; overlay cannot recover its rejects.

One shared $1000 account, January 2025 through October 7, 2026, no annual reset.
2025 diagnostic and 2026 evaluation both reported. Asset alphabetic order at
equal entry timestamp, deterministic not best-outcome ordering. At entry only
already CLOSED P&L updates balance/peak. Settle exits before equal-time entries.
Open positions reserve stop loss plus cost. No future P&L available to sizing.

Four fixed policies: baseline .5% per trade, no aggregate cap; shared .5% per
trade with .5% total reserved loss cap; drawdown same shared cap but per-trade
risk .25% when closed-balance drawdown >=2%, otherwise .5%; conservative .25%
per trade with .5% aggregate cap. No martingale or score-based sizing: no
validated quality estimate exists. Wide stops reduce units; round down to broker
step, below minimum means skip, never force minimum. Total open notional <=5x
current closed balance, illustrative ceiling NOT a broker margin model.

Same conditional 2/4 pip round-trip assumptions, current Oct14 volume terms.
No top-ups/interest/mark-to-market/liquidations/slippage realism claim. Adverse
gaps may exceed reserved loss; these are intended risk budgets, not guarantees.
Outputs cash, trades, skip reasons, annual ends, closed-balance drawdown and
max reserved risk. 2026 daily cash and paired difference CI: 10-calendar-day
moving blocks,10000 draws,seed20261015,Bonferroni 16 intervals
(4policies*2costs*2metrics; quantile tails .05/32).
CI conditional on realized sizing path, NOT bootstrap resimulation of adaptive
policy. No activation based on this reused small sample, regardless of ranking.

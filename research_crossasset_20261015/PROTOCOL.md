# Cross-asset cheap signal screen, frozen before outcomes, 2026-10-15

Two new mechanisms, NOT another optimization of rejected single-chart rules.
Offline only; no imports of application config/models, credentials, DB, orders,
cloud changes, paper cash reset or workers. This is a predictive event study,
NOT a trading simulator: fixed horizons, no executable stops, fills or account.
If predictive edge fails here, do not build an executor. If it passes, a separate
same-broker bid/ask simulation WITH protective stops is mandatory before promotion.

Input existing Binance SPOT BTCUSDT/ETHUSDT H1 cache, Jan2024..Oct7 2026.
Manifest must be complete, identical aligned hour axes, no missing/duplicate bars,
positive finite valid OHLC. Record current SHA256s; legacy manifests lack original
hashes: present hashes cannot retrospectively prove original acquisition integrity.
Already studied history, NOT fresh or blind out-of-sample. Spot short returns are
ONLY price proxies for a possible cTrader CFD pair, not executable spot shorts.
USD/USDT basis, cTrader price differences, historic fees and financing unverified.

1. Ratio reversion: log(BTCclose/ETHclose) vs mean/population SD of PRIOR168
closed H1 ratios, excluding current. abs(z)>=2 => short expensive/long cheap.
Equal initial dollar legs (.5 long, .5 short of total gross notional), fixed
units per observation, not continuously rebalanced, no beta-neutrality claim.
2. Leader-lag: completed BTC H1 close/open return abs>=1%, and completed ETH
H1 abs return < half abs BTC return => ETH direction of BTC. Single ETH leg.
Not a reproduction of an author's exact rule; thresholds are our frozen choices.

Both wait ONE full hour after signal close, then next H1 Open price proxy.
Ratio horizon24h; leader-lag6h. Exit Open at horizon, not close before horizon.
One observation at a time per arm. Cooldown to planned exit, independent of
outcome. End-window insufficient coverage pending, not fake zero or a forced
close. All hypotheses/controls retain same entry timestamps. No threshold sweep.

Three cost cases: zero gross; base20bp; stress30bp ROUNDTRIP per total initial
gross notional, i.e. both weighted legs included, not charged only once per pair.
Positive long financing additionally20% annual * horizon/(365*24), weighted by
long leg .5 for pair or1 for long ETH; short financing assumed0. These are
conditional sensitivity assumptions, NOT measured historical account costs.
No fundings, exchange futures or new accounts required for the intended CFD idea.
Negative tail risk/margin/liquidation/intrahour excursions NOT established here.

Report mean bp, count, win fraction, summed independent bp (NOT balance/PnL),
max loss observation, net-positive-to-negative ratio; gross break-even cost.
Four entry phases2024,2025,2026H1,2026H2(toOct7), no postselection split changes.
Same-event opposite, always long ratio/BTC-leading and always short controls.
10-calendar-day circular bootstrap,10000 resamples, fixed seed20261015;
64-cell conservative familywise95% intervals for this batch only. NOT global
correction for all prior research nor a guarantee at finite bootstrap tails.
Gate: stress mean positive ALL four phases, >=100 closed2026 observations and
>=30 late observations; late adjusted lower mean>0 and paired lower improvement
over ALL3 controls>0; pending must be disclosed but cannot be counted as wins.
All arm results, including failures, retained. No live promotion on this gate.

Primary background, not evidence these exact rules work:
https://www.nber.org/papers/w7032 (original equity pairs, not crypto validation)
https://www.sciencedirect.com/science/article/pii/S0378437120305641
(changing crypto lead/lag relationships, not guaranteed tradable alpha)
https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md

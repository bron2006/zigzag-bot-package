# Frozen batch v1, before this batch's PnL

Independent adaptations, not replicas or claims about sold cBots. Offline only.
24 predefined signal rules x four cached broker markets = 96 candidates.
ORB 5/15/30 are related configurations, NOT 3 independent discoveries.
USTEC cash09:30-16NY, official holidays/early closes excluded; FX08-16London,
weekdays, DST aware. Period2024-01-01 to2026-10-07. All session M5 bars required.
No interpolation. Continuous M5 indicators reset after any timestamp gap:
SMA TR14, EMA9/21, EMA12/26+signal9,
BB20 populationSD2, simple rolling RSI2 (not Wilder), stochastic14.
All rules require60 completed consecutive M5 bars, including pre-session
history. Session range patterns still use only the current session bars.
All signal closes known at decision; entry NEXT Open. Signals at least15min
before session end. One intent/trade/day, no retry, martingale, averaging.
Previous-session features use last complete session only with <=5calendar-day
gap; longer-lookback NR7/DualThrust require last7/4 complete sessions with
no >5day gap. Missing sessions disclosed; sparse-session-gap effects retained.

Signal definitions (first qualifying close only):
1 orb5: close above first1bar high/below low.
2 orb15: above first3bar high/below low.
3 orb30: above first6bar high/below low.
4 failed_orb15: first close outside first3bar range, then close back inside,
fade original direction. One excursion tracked, even if never re-enters.
5 retest_orb15: same first breakout, then touch broken boundary while close
remains beyond it; follow direction. Cancel if close re-enters range.
6 gap_follow: sessionOpen-prevSessionClose >=0.25prevRange absolute,
first eligible close at/after first30min still on gap side of prevClose,
follow gap direction.
7 gap_fade: same qualifying event, opposite direction.
8 prior_range: close above previous sessionHigh/belowLow.
9 nr7: previous range is minimum of previous7ranges; prior_range trigger.
10 ema_cross: EMA9 crosses EMA21; require >=60 completed bars.
11 ema_pullback: EMA9>21 and currentLow<=EMA9, currentClose>EMA9 and C>O,
mirror short; EMA separation >=0.25M5ATR14.
12 donchian20: close outside PREVIOUS20bar high/low (current excluded).
13 bb_reentry: prior close beyond priorBB20/2SD, now closes inside currentBB,
fade side. CurrentBB known at close.
14 rsi2: priorRSI<10 then currentRSI>=10 long; priorRSI>90 then<=90 short.
15 macd: EMA12-EMA26 crosses its EMA9 signal.
16 stochastic: priorK<20/current>=20 long; priorK>80/current<=80 short.
17 inside_break: previousbar inside bar before it; current close outside
motherbar high/low, follow.
18 compression: previous12bar range <=0.5 previous60bar range; current
close outside previous12bar high/low.
19 morning_follow: only first120min close; abs(close-open)>=0.25prevRange,
follow direction.
20 morning_fade: same timestamp/event, opposite direction.
21 afternoon_follow: only first270min close; preceding60min netClose change
>=2M5ATR14 absolute; follow direction.
22 dual_thrust: sessionOpen +/-0.5*max(HH-LC,HC-LL) of last4full sessions,
follow first close outside.
23 open_reclaim: first eligible close >=0.5ATR14 from sessionOpen sets side;
first later close crossing to opposite side of Open follows new direction.
24 three_impulse: three consecutive same-sign non-doji candles, net change
from firstOpen>=2ATR14; follow direction.

Controls: always long, always short, date-seeded random direction, all entering
first60min close/nextOpen. Same risk/exits/costs, not added as discoveries.

Shared stop = entry - side*1.5ATR14 at signal; target = entry+side*2risk.
Stop and target checked entry bar; if both touched STOP FIRST. Stop gaps fill
adverse Open, favourable TP gaps fill target (no improvement). Otherwise EOD.
No trailing/overnight positions; OHLC bid/ask ambiguity remains unverified.
Conditional total RT costs: USTEC2/5 INDEX POINTS, FX2/4 PIPS (JPYpip0.01,
otherpip0.0001). These assumed ALL-IN friction amounts include commissions,
spread and slippage, NOT measured historical execution or guaranteed fees.
Current metadata min/step/max used conditionally for past dates.

Independent1000USD per market/rule/year. Maximum1%risk including friction.
USD quote PnL = units*priceChange; JPY convert at conditional exitprice.
Quantity=min(riskbudget/(stopDistance+cost)inUSD,5xUSDnotionalcap,brokermax).
Round DOWN to broker step, skip below minimum; no forcing min-size. 5xcap
illustrative NOT verified margin. Risk may be LESS than1% due to cap/rounding.
USTEC assumed1unit=1USD/point; FX base units. Historical accountterms unknown.
Report ideal fractional and rounded size separately. Closed balance and
sampled OHLC adverse-range DD, not tick-equity or liquidation proof.

2024-2025 exploration, 2026 RETROSPECTIVE comparison, NOT unseen/prospective
OOS (underlying history was already available/partially inspected). No
parameter optimization or selecting a portfolio on 2026. Every candidate
reported, including negative and zero-trade cases. No late threshold edits.
Family-wise approximate one-sided block-bootstrap lower bound: 20000 circular
5session block resamples, seed20261010, alpha0.05/96. Bootstrap is NOT an exact
false-positive guarantee. Rounded fixed1000USD trade sizing supplies daily
USD expectancy samples including no-trade/size-skipped sessions as zero;
missing sessions omitted. Same resampling indices across candidates.
Cheap gate: >=95%known2026sessions, >=100taken stress2026trades, positive
stress rounded account each year, adjusted lower dailyUSD bound>0. Additional
diagnostics PF, drawdown, unadjusted CI, without3bestdays, long-only controls.
Even a cheap-gate pass is NOT production approval: independent prospective
period, bid/ask execution, fees/margin and robustness still mandatory.
No funding, no restartedVWAP, no DB/network/runtime/orders in this batch.

Primary background (adaptation only):
https://www.quantconnect.com/docs/v2/writing-algorithms/strategy-library
https://www.quantconnect.com/docs/v2/writing-algorithms/key-concepts/behavioral-finance
https://concretumgroup.substack.com/p/a-profitable-day-trading-strategy

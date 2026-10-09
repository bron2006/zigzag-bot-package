# News continuation v1 — frozen before price retrieval, 2026-10-09

One rule, EURUSD only. Event universe: all published US BLS Employment Situation
and CPI archive releases dated 2024-01-01 through 2026-10-07. Use actual archive
release date, not reference month or an assumed first Friday. Cancelled/unpublished
releases are not events. Verify 08:30 ET in each release header; unknown/other time
is missing-calendar data, NOT guessed. America/New_York to UTC including DST.
No economic actual/forecast/surprise values used. FOMC not included in this first
bounded test: keep two uniform release types/time and one instrument, no selection
by observed price results. Their official archives are available; local HTTP403
requires official pages via web retrieval, not an invented calendar.

Pre-event volatility: arithmetic mean true range of last14 complete M5 bars, using
15 consecutive bars ending at T. First impulse: Close(T..T+300) minus Close(T-300..T).
Signal only if abs(impulse)>=1.5 * pre-event ATR and impulse !=0. Direction follows
impulse; exactly one observation per release. Feature preparation sees no bars
after T+300. Confirmation/decision T+300, entry earliest valid broker bid/ask snapshot
at T+301, max5s late; exit at ACTUAL entry timestamp+300s, max5s late. Sides updated
within1s; discard crossed/nonpositive/nonfinite quotes. Missing endpoint unknown,
never use later price or zero payoff. No martingale, stop/target optimization.

First screen M5 endpoint direction (entry first impulse close, exit next close)
is explicitly a proxy, not executable PNL. For ALL selected events retrieve BID/ASK
endpoint windows. If quote history unavailable, report coverage; do not substitute
M5 prices for a claim of executed profit. Historical requests read-only demo-only
allowlist; no order/refresh APIs, bounded killable child, immutable raw checkpoints.

Forex: long ASK entry/BID exit, short BID entry/ASK exit. Observed spread included.
Fixed illustrative roundtrip commission .7 pip (EURUSD pip=.0001), stress additional
1 pip unfavorable slippage. Not user's confirmed broker tariff; no position sizing,
portfolio PNL or TP/SL simulated. Binary: separately use midpoint direction with
assumed .70/.80/.90 payout, fixed stake1, flat assumed refund. NOT Binomo quotes
or settlement and not transferable without prospective venue verification.

Early2024, later2025–2026, fixed calendar split. No threshold/holding-period/pair
search, no post-hoc reversal strategy if continuation fails. Baselines same events:
always UP/DOWN and opposite direction (diagnostic only). Bootstrap release dates,
4000 draws/seed20261009. At least30 later known selected independent releases and
>=90% endpoint coverage before considering a paper candidate. Require positive
early mean, later lower95% mean forex-net CI >0 at stress, and paired advantage
over both UP/DOWN lower95%CI >0; binary gate evaluated separately at .80 payout.
No automatic deployment, real orders or removal of current news safety filter.
Retrospective chronological study, not blind prospective OOS; archive schedules
may have been revised and do not prove the bot knew the dates ahead of time.

Sources: https://www.bls.gov/bls/news-release/empsit.htm
https://www.bls.gov/bls/news-release/cpi.htm

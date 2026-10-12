# Continuous prospective data observations, not trade execution

Owner asks why no continuous testing exists. Start independent resident
cTrader read-only collector, sixty-second non-overlapping cycles, persistent
/data/forward_structure_v1.sqlite3. Old model/scanners/expiry test/paper entries
remain OFF; old999.37USD ledger unchanged. No new account deposits or real orders.

Four fixed symbols EURUSD,GBPUSD,BTCUSD,ETHUSD; USD-normalized risk illustration
only, no broker size/margin/account simulation. Three frozen structure rules
from PROTOCOL.md. Forex rules failed historical gates and are NEGATIVE CONTROLS,
not revived trading candidates. Crypto rules are an UNVALIDATED new extension,
not historical equity, spot/futures funding or claimed profitable strategy.

Each pair/rule first intent perUTCday INDEPENDENTLY (not pooled offline earliest
pair portfolio). Same H1 definitions; forex decisionhours09..15UTC/flat16UTC;
crypto01..23UTC/flatnext00UTC. No timer-driven forced trades, parameter search,
winner selection, martingale or change to mainbalance. 24complete contiguous
H1warmup and14true-range ATR; H1contains exactly12completeM5bars. Histories reset
after gaps. Firstintradaysetup can predateactivation: thatday not replaced by
another setup. Deliberate firstday exclusion, not permission to backfill winners.

Only setup timestamps>=first persisted activation time. Initial six-day cache
for warmup and sourceverification only, not fake forward observations. First
successive requests both may retrieve past CLOSED bars: modeled nextM5Open
is not an actual logged pre-entry decision or executable fill. This is a frozen
prospective OHLC study of data collected after activation, NOT proof of live
entrytiming, BID/ASK availability, slippage, fees or netbrokerprofit. Source
requests exclude current/incompletebar with30second completiongrace. No strategy
BUY/SELL notifications; no old Telegramalerts restarted.

M5 paths stop-first if ambiguous, adverse opengap/targetatlimit, sessionflat
only once completeendbar received; incomplete session pending, missing path
UNKNOWN never0profit. Missingentry after1hour unknown, missingend after1hour
unknown; downtimeolderthan6daycollectorwindow unknown ratherthan made-upfill.
Terminal observations not rewritten. Sealedbar revision rejects packet and
visible sourceerror (no silent overwrite). Duplicates/restart idempotent.

Base/stress assumed all-in roundtrip FX2/4pips, crypto0.10%/0.20% entrynotional.
Normalized netR and netR*USD5 illustration, NOT units, lots or balance addition.
No fulluncertainty/portfolio/causal execution superiority claim. Future promotion
requires separate evidence/strategyapproval, not justpositive forward subtotal.

Dashboard separates active data study from saved inactiveaccount. All-time
status counts; latest60scenario observations in detailedview (not allhistory).
Entire rawprice/observation journal persists; no files sent toowner. Source
fetchstate and lastcandle timestamps visible so waiting/no setups is not hidden
as fake activity. Polling/errors do not require owner to point themout.

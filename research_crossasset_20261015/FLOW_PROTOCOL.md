# Separate executed-flow predictive screen, frozen before this batch's outcomes

Existing Binance BTCUSDT/ETHUSDT SPOT M15 cache2026Jan1..Oct7. Not live broker
bidask, not order book imbalance, not true footprint/delta by price-level.
Raw standard kline[5] basevolume and [9] takerbuybasevolume: imbalance=2*buy/v-1.
Require v>=2*mean PRIOR20volumes and abs(imbalance)>=.30. Direction imbalance
sign, main FOLLOW; same-event opposite diagnostic, not a selectable replacement.
One complete M15 delay after known close, entryOpen index+2, fixed1hour horizon
(4bars), exitOpen. One planned observation at a time. End incomplete=pending.
This is a cheap predictive filter WITHOUT stop simulation; not execution advice.
Allinputscompletecontiguous/hashchecked, buyvolume[0,total] mandatory.

Base20bp/stress30bp hypothetical RT plus20%annual long carry for possible CFD
proxy, short0; gross also reported. NOT actual fees, funding or an exchange-short
implementation. No account, margin, compounded-return, broker-fill claims.
Early2026Jan-Jun / lateJul-Oct7 previously-studied history, no unseen OOS claim.
Same-event opposite/alwayslong/alwaysshort controls. 10calendar-day bootstrap
10000 reps seed20261015 conservative64-cell95%CI. Gatepositive stressbothhalves,
>=100closedlate and late adjustedmeanlower>0, paired improvementlower>0vsALL
controls. No threshold tuning after outcomes; bothassets/allresults retained.
No production changes, no order endpoints, new accounts or DB interaction.

Official raw field definitions:
https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md

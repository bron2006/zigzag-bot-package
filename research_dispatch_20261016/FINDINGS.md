# Three-agent research batch, completed 2026-10-16

Human explicitly requested agents. Three actual collaboration agents were
launched: read-only inventory, London fixing reversal, fixed weekday drift.
They are turn-scoped workers, NOT persistent scheduled agents. No heartbeat,
automation, scheduled task, cloud worker, real trading or saved-cash change.

Inventory reconfirmed prior 96-rule broad batch and later rejected families;
new two hypotheses are not EMA/timeframe tweaks. Still previously studied
price history, not a fresh or independent out-of-sample test. Same historical
conditional cost/volume assumptions and CFD mid/bar execution limitations.

## Completed outcomes

London16fixfade, separate1000USD/pair Jan2025..Oct7 2026: EURUSD914.98base /
875.708stress,GBPUSD939.537base/886.79stress. Known2025/26EUR50/45,GBP61/48;
no unknowns/min-size skips. Funded gross also negative, not only a cost issue.
All gatesfail; no activation. Official LSEG establishes the calendar anchor,
NOT that this exact fade strategy earns money or CFD candles measure WMR flow:
https://www.lseg.com/en/ftse-russell/benchmarks/wmr-fx-benchmarks

Calendar weekday sign trained2024 only, frozen2025/26, same London morning
window. 2025stressEUR252closed/-61.716R,GBP255/-78.642R. 2026knownprefix116
closed each; bothactual firstunknownJun15 at07:05UTC. Haltpreserved; cutoffCI
beforeunknown day, NOTzero-fillJun..Oct. Jan2025..lastknownJun12 2026prefix:
EUR786.145357base/710.617143stress,GBP762.289643/726.756071. TheseareNOT
Oct7balances. 4unknownscenariooutcomes=2pairs*2costs,not4independentfeedholes.

## Numerical audit repair, after initial outcomes

Root independent audit reconstructed controls as well as actuals. Found a
binary-float touching-level discrepancy EURUSD base buycontrol entry1788189000,
distance.00041000000000002146: float and exactDecimal disagreed on stop versus
deadline, changing paired excess. Initial per-agent audits covered actuals,
not all controls: this limitation was acknowledged, not hidden/tolerance-waved.

Added isolated price_replay.py: Decimal derived prices/distance normalized to
12places, far finer than inputquote resolution, NOT broker tick snapping or
proof of executable prices. Both new candidate AND control paths switched and
entire results recomputed; frozenstrategy protocols unchanged. Amendments in
each candidate explicitly after-outcome numerical repairs, not new blind tests.
Oldsharedhigher_timeframes.py and older result artifacts NOT silently changed.
Prior artifacts using float comparisons may need boundary-audit before reuse;
no assertion every prior conclusion reverses or all historical gates remain
numerically identical without rerun.

Both candidates remain rejected; final funded balances materially unchanged.
Root audit: fix632actual+1896controls+408fundedcash; calendar1478actual+
4430knowncontrols+1461fundedcash. Four calendar control paths censored, explicit
None rather than fabricated values; unknown actual halts the arm. Independent
Decimal netR errors0 under declared12place convention. Exitreasons/timestamps,
fundedquantities/rounding/minskips/cash,annualcounts/sums,input/protocol/original
model hashes checked. Agent-specific audits retained too.

## Bounded repeatability

batch.py default only verifies existing outputs. Explicit --run starts exactly
two allowlisted local research scripts in parallel, each hard timeout180secs;
timeout kills/waits child and is NOT recorded as candidate trading loss.
No loop/schedule/auto-promotion. Reports distinguish completedresearch from
candidatepass and completecash from knownprefix. Cannot hide one losing pair,
use staleprotocol, truthystring gate, or reuse oldresult after failedprocess.
Source hashes record current verification, not proof of original acquisition.

No deployment, model overwrite, Telegram/UI/DB/order mutation or GitHub push.
Final verification: 796 isolated project tests pass, including11fix,8calendar,
6bounded-dispatch and5numerical-replay tests. gitdiffcheckclean. Test passing
verifies software mechanics, NOT market edge.

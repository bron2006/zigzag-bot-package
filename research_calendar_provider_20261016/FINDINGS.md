# Calendar provider diagnosis, 2026-10-16

Read-only diagnostic, NOT a trading fallback or permission to unblock trades.
No changes to news_filter.py, runtime, cloud, or existing live canary.

## Earlier observed incident

Three bounded GETs earlier in this session showed:

- from2026-10-15,to2026-10-18: HTTP200,events[],total0; missing allTotal.
- Same from,to2026-10-17: HTTP200,4validdatedevents,total4,allTotal1457.
- Wide range plus request Cache-Control:no-cache: still empty.

Both range responses were X-Vercel-Cache:HIT, public,max-age300. Empty response
Age135, server Date14:05:28GMT; narrow responseAge93,Date14:06:10GMT.
This is an observed range inconsistency BEFORE parsing, not proof of parser
failure. A client no-cache header did not bypass the cached response. We did
not establish whether stale cache, origin transient error, endpoint policy,
backend inconsistency or another provider condition originally created it.

## New bounded probe: recovered

Observed2026-10-16T14:23:39.091603Z (17:23Kyiv). Fixed four ranges, no retries,
each GET timeout8s, killable child process with hard parent deadline36s.
Actual four GET durations2.282/.906/3.391/.765seconds, totalunder8seconds.
Public endpoint only; safe allowlist responseheaders, no cookies/auth secrets.
Full public source JSON and safeheaders retained in result.json.

| from | to | HTTP | Raw events | Existing parser output |
|---|---|---:|---:|---:|
|2026-10-15|2026-10-18|200|4|4|
|2026-10-15|2026-10-17|200|4|4|
|2026-10-15|2026-10-16|200|4|4|
|2026-10-16|2026-10-18|200|1|1|

Allfour X-Vercel-Cache:MISS,Age0,Cache-Controlpublic,max-age300. Contained-range
consistency contradictions0. Rawvaliddatedevents survive parsing in allranges.
The same wide requested range now returns data. Therefore the earlier fault
was temporary; root cause remains UNPROVEN. We did NOT change query ranges
to find a convenient nonempty response or assert every quiet range is wrong.

## Parser separation and tests

AST-select ONLY existing _parse_calendar_time,_parse_calendar_events and the
literal importance mapping from news_filter.py. No import of runtime/config,
state,reactor,DB; no substitute production parser. Source SHA256:
d043f9144d43fe65d43f9edf57957f5677eedeb5681d1732e4e0b9e0d50f27a1.
Eight offline testsPASS: current parserfixture; emptywide/knownnarrow
contradiction; consistentcontainedrange; malformedpayload; invaliditems;
transporttimeout; hardparenttimeout; secretresponseheaderexcluded.
The malformed/timeout states remain diagnostic errors, never GO/zero-risk.

## Potential fixes: not applied

1. Add runtime data-quality distinction between provider empty data and parser
   drops. Improves diagnosis; does not supply missing events. Requires scoped
   runtime tests, zero-event/failclosed policy unchanged unless approved.
2. Check contained ranges as an integrity alarm, not a silent trading fallback.
   Detects contradictory results when a subset has known events; increases
   provider requests and is inconclusive when allranges are empty. Endpoint
   inclusive/exclusive day semantics need explicit contract before reuse.
3. Independent second provider with date/currency/importance contract. Can
   reduce single-provider dependence but coverage/licensing/latency/cost and
   discrepancy policy need validation. No second provider integrated here.
4. Known-good cached events with explicit freshness/staleness and failclosed
   guard. Helps temporary outages but cannot invent future unseen releases.

NOT recommended: shorten range until something appears; blanket retry with
cachebuster; disable livecanary; treat HTTP200empty as guaranteed no-news;
claim source failure proves parser broken; erase earlier failed test result.
Current diagnostic recovery does not prove cloud runtime status; no live
runtime inspection or deploy occurred in this task.

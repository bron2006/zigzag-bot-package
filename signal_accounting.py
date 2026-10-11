"""Read-only fixed-stake scenario, NOT broker settlement or an executable ledger."""
import math
from collections import Counter


def summarize(rows, evidence, *, valuation='strict'):
    if valuation not in {'strict', 'asof60'}:
        raise ValueError('invalid_valuation')
    counts = Counter()
    reasons = Counter()
    recent = []
    pair_counts = {}
    publication_counts = Counter()
    asof_counts = Counter()
    new = [r for r in rows if r.id in evidence]
    for row in new:
        audit = evidence[row.id]
        asof = audit.get('asof_audit')
        if asof:
            asof_counts['checked'] += 1
            quote = (asof.get('history') or {}).get('endpoint')
            asof_counts['available' if quote else 'unavailable'] += 1
            if quote and row.outcome == 'unknown':
                asof_counts['original_unknown_with_price'] += 1
            if quote and row.exit_price is not None and quote['mid'] != row.exit_price:
                asof_counts['different_price'] += 1
        status = row.outcome
        exit_price = row.exit_price
        endpoint_ts = (audit.get('endpoint') or {}).get('ts')
        valuation_reason = None
        if audit.get("reason") == "publication_cancelled_db_delay":
            status = "cancelled"
        if valuation == 'asof60' and status not in {'pending','cancelled'}:
            quote = ((asof or {}).get('history') or {}).get('endpoint')
            exit_price = quote.get('mid') if isinstance(quote, dict) else None
            endpoint_ts = quote.get('ts') if isinstance(quote, dict) else None
            status = 'asof_timed' if quote else ('unknown' if asof else 'pending')
            valuation_reason = None if quote else ('asof_no_fresh_sides' if asof else 'asof_check_pending')
        publication = audit.get('publication')
        publication_state = publication.get('state') if isinstance(publication, dict) else 'legacy_unconfirmed'
        publication_counts[publication_state] += 1
        publication_reason = None
        if publication and publication_state != 'confirmed' and status != 'cancelled':
            if publication_state == 'failed':
                status, publication_reason = 'cancelled', 'publication_failed'
            elif status != 'pending':
                status, publication_reason = 'unknown', 'publication_unconfirmed'
        if status.endswith("_timed"):
            entry, exit_ = row.entry_price, exit_price
            if not all(isinstance(p, (int, float)) and math.isfinite(p) and p > 0 for p in (entry, exit_)):
                status = "unknown"
            elif exit_ == entry:
                status = "refund"  # explicitly chosen PAPER rule, not broker policy
            else:
                status = "win" if (exit_ > entry) == (row.verdict == "BUY") else "loss"
        if status not in ("win", "loss", "refund", "pending", "unknown", "cancelled"):
            status = "unknown"
        counts[status] += 1
        pair_counts.setdefault(row.pair, Counter())[status] += 1
        reason = publication_reason or valuation_reason or (audit.get('reason') if valuation == 'strict' else None) or ("endpoint_unavailable" if status == "unknown" else None)
        if reason:
            reasons[reason] += 1
        recent.append(dict(id=row.id, pair=row.pair, direction=row.verdict,
                           entry_ts=row.entry_ts.isoformat(), entry=row.entry_price,
                           exit=exit_price, status=status, reason=reason,
                           endpoint_ts=endpoint_ts))
    pnl = counts["win"] * 8 - counts["loss"] * 10
    missing = counts["pending"] + counts["unknown"]
    return dict(source="cTrader", cohort="asof60_v1" if valuation == 'asof60' else "live_mid_v1", total=len(new),
                valuation=valuation,
                counts=dict(counts), missing_reasons=dict(reasons), publication_audit=dict(publication_counts),
                asof_comparison=dict(policy='asof60_shadow_v1', max_side_age_seconds=60,
                                     affects_balance=valuation == 'asof60', counts=dict(asof_counts)),
                by_pair=[dict(pair=pair, counts=dict(c), total=sum(c.values()),
                              win_rate=round(100*c["win"]/(c["win"]+c["loss"]), 1)
                              if c["win"]+c["loss"] else None)
                         for pair, c in sorted(pair_counts.items())],
                recent=sorted(recent, key=lambda r: (r["entry_ts"], r["id"]), reverse=True)[:50],
                scenario=dict(initial=1000, stake=10, net_payout=0.8,
                              measured_pnl=pnl, measured_balance=1000+pnl,
                              balance_lower=1000+pnl-10*missing,
                              balance_upper=1000+pnl+8*missing,
                              complete=missing == 0, refund_rule="exact_equal_price",
                              executable=False, bankroll_limits_simulated=False),
                legacy_total=len(rows)-len(new),
                first_entry=min((r.entry_ts.isoformat() for r in new), default=None),
                last_entry=max((r.entry_ts.isoformat() for r in new), default=None))

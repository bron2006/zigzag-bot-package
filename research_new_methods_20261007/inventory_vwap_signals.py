"""Offline extraction of logged intentions, NOT filled trades or PnL."""
from datetime import datetime
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SIGNAL = re.compile(r'VWAP \[READ-ONLY\]: would enter (\S+) LIMIT=([-\d.]+) SL=([-\d.]+) volume=(\d+)')
TIMESTAMP = re.compile(r'(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})')


def main():
    records, missing_timestamp, scanned = [], 0, 0
    for path in sorted((ROOT/'logs').glob('vwap_executor_*.log')):
        scanned += 1
        # Fields extracted are ASCII even when Ukrainian text is CP1251.
        with path.open(encoding='cp1251', errors='replace') as stream:
            for line_number, line in enumerate(stream, 1):
                match = SIGNAL.search(line)
                if not match:
                    continue
                timestamp = TIMESTAMP.search(line)
                if not timestamp:
                    missing_timestamp += 1
                    continue
                wall_time = datetime.fromisoformat(timestamp.group(1)).isoformat()
                records.append(dict(local_wall_time=wall_time, timezone_unverified=True,
                                    symbol=match.group(1), limit_price=float(match.group(2)),
                                    stop_price=float(match.group(3)), volume=int(match.group(4)),
                                    source=path.name, line=line_number))
    times = sorted(r['local_wall_time'] for r in records)
    days = sorted({t[:10] for t in times})
    summary = dict(files_scanned=scanned, logged_intentions=len(records),
                   first_local_wall_time=times[0] if times else None,
                   last_local_wall_time=times[-1] if times else None,
                   days_with_intentions=len(days), days=days,
                   symbols=sorted({r['symbol'] for r in records}),
                   lines_without_timestamp=missing_timestamp,
                   not_deduplicated_not_trades=True,
                   no_signal_on_a_day_does_not_prove_bot_uptime=True)
    output = Path(__file__).with_name('vwap_intentions_inventory.json')
    output.write_text(json.dumps(dict(summary=summary, intentions=records), indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()

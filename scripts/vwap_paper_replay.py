"""Replay normalized signal/target/quote/gap/advance JSONL through LIVE engine.

No config/broker/network imports. Output must be a new non-production file.
Example: python scripts/vwap_paper_replay.py events.jsonl --output replay.sqlite3
"""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from vwap_paper import PaperJournal,read_summary

def replay_events(events,output):
    output=Path(output)
    production=Path(__file__).resolve().parents[1]/'logs'/'vwap_paper.sqlite3'
    if output.resolve()==production.resolve() or output.exists():
        raise ValueError('Replay output must be new and outside production journal')
    journal=PaperJournal(output)
    previous=float('-inf')
    try:
        for item in events:
            kind,payload=item['kind'],item['payload']
            if kind not in ('signal','target','quote','gap','advance','halt'):
                raise ValueError('Unsupported replay event')
            ts=payload['ts']
            if ts<previous:
                raise ValueError('Replay events must be chronological')
            previous=ts
            getattr(journal,kind)(**payload)
    finally:
        journal.close()
    return read_summary(output)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('events',type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    with args.events.open(encoding='utf-8') as stream:
        events=(json.loads(line) for line in stream if line.strip())
        print(json.dumps(replay_events(events,args.output),indent=2,allow_nan=False))

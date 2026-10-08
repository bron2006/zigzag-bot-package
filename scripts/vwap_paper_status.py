"""Read-only status of the local paper journal; no bot/config imports."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from vwap_paper import read_summary

if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Локальний паперовий журнал VWAP')
    parser.add_argument('--path',type=Path,default=Path(__file__).resolve().parents[1]/'logs'/'vwap_paper.sqlite3')
    parser.add_argument('--details',action='store_true')
    args=parser.parse_args()
    summary=read_summary(args.path)
    if not args.details:
        summary.pop('records',None)
    print(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False))

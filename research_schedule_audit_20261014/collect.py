"""Backup resident research DB, retrieve data-only evidence and audit locally."""
import base64
import json
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parent
sys.path.insert(0,str(ROOT))

REMOTE=r'''
import sqlite3,json,time
from pathlib import Path
source=sqlite3.connect('file:/data/forward_structure_v1.sqlite3?mode=ro',uri=True,timeout=5)
source.execute('PRAGMA query_only=ON')
backup=Path('/data/audit-forward-20261014-before-closure.sqlite3')
if not backup.exists():
    dest=sqlite3.connect(str(backup));source.backup(dest,pages=64);dest.close()
source.execute('BEGIN')
rows=source.execute('SELECT payload FROM observations ORDER BY pair,day,scenario').fetchall()
bars={p:[json.loads(r[0]) for r in source.execute('SELECT payload FROM bars WHERE pair=? ORDER BY ts',(p,))] for p in ('EURUSD','GBPUSD','BTCUSD','ETHUSD')}
print(json.dumps(dict(now=time.time(),backup=str(backup),backup_bytes=backup.stat().st_size,observations=[json.loads(r[0]) for r in rows],bars=bars)))
source.close()
'''


def main():
    command='python -c "exec(__import__(\'base64\').b64decode(\''+base64.b64encode(REMOTE.encode()).decode()+'\'))"'
    result=subprocess.run(['fly','ssh','console','--app','zigzag-bot-package','--command',command],capture_output=True,text=True,timeout=60)
    if result.returncode:raise RuntimeError('Research snapshot retrieval failed')
    data=json.loads(next(line for line in result.stdout.splitlines() if line.startswith('{')))
    (HERE/'snapshot.json').write_text(json.dumps(data),encoding='utf-8')
    specs={s['name']:s['specification'] for s in json.loads((HERE/'metadata.json').read_text())['symbols']}
    from forward_structure_research import outcome
    from ny_h4_reclaim import detect,RULE
    intents={p:{i['ts']:i for i in detect(bars)['intents']} for p,bars in data['bars'].items()}
    audited=[]
    for old in data['observations']:
        if old['intent']['rule']!=RULE:continue
        pair=old['pair'];intent=old['intent'];detected=intents[pair][intent['ts']]
        assert all(detected[k]==intent[k] for k in ('ts','side','stop','range_start','range_end','range_high','range_low'))
        new=outcome(intent,data['bars'][pair],data['now'],old['scenario'],crypto=pair in ('BTCUSD','ETHUSD'),schedule=specs[pair])
        if old['status']=='closed':
            assert all(old[k]==new[k] for k in ('entry','stop','target','exit','reason','net_R'))
        audited.append(dict(pair=pair,scenario=old['scenario'],ts=intent['ts'],old_status=old['status'],new=new))
    report=dict(backup=data['backup'],audited=audited,all_existing_closed_preserved=True,all_signals_reproduced=True,
                source_fill_side_not_verified=True,costs_still_assumed=True,no_cash_changes=True)
    (HERE/'audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()

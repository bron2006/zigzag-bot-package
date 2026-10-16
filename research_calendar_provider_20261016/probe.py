"""Read-only provider diagnostic. No trading decision, imports or fallback."""
import ast
from datetime import datetime, timezone, date
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent;ROOT=HERE.parent
BASE='https://tool.forex/api/calendar'
RANGES=[('2026-10-15','2026-10-18'),('2026-10-15','2026-10-17'),
        ('2026-10-15','2026-10-16'),('2026-10-16','2026-10-18')]
SAFE_HEADERS={'date','age','cache-control','content-type','server','x-vercel-cache','vary','via','cf-cache-status'}

def load_existing_parser():
    """Compile ONLY two existing pure functions and literal mapping, no import."""
    source=(ROOT/'news_filter.py').read_bytes().decode('utf-8');tree=ast.parse(source)
    selected=[]
    for node in tree.body:
        if isinstance(node,ast.FunctionDef) and node.name in ('_parse_calendar_time','_parse_calendar_events'):selected.append(node)
        elif isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='_CALENDAR_IMPORTANCE_TO_IMPACT' for t in node.targets):
            ast.literal_eval(node.value);selected.append(node)
    if len(selected)!=3:raise ValueError('Pure parser source selection changed')
    namespace={'datetime':datetime,'timezone':timezone}
    exec(compile(ast.Module(body=selected,type_ignores=[]),'existing_news_filter_pure_functions','exec'),namespace)
    return namespace['_parse_calendar_events'],hashlib.sha256(source.encode()).hexdigest()

def classify(payload,parser):
    if not isinstance(payload,dict) or not isinstance(payload.get('events'),list):
        return dict(status='malformed_payload',raw_count=None,parsed_count=None,events=[])
    raw=payload['events']
    try:parsed=parser(raw)
    except Exception as exc:
        return dict(status='parser_exception',raw_count=len(raw),parsed_count=None,events=[],error_type=type(exc).__name__)
    events=[dict(currency=e['currency'],name=e['name'],date=e['time_utc'].isoformat()) for e in parsed]
    return dict(status='empty_source' if not raw else 'parsed' if len(parsed)==len(raw) else 'partially_parsed',
                raw_count=len(raw),parsed_count=len(parsed),events=events)

def fetch_one(begin,end,parser,transport=None):
    if transport is None:
        import requests
        transport=requests.get
    started=time.monotonic()
    try:
        response=transport(BASE,params={'from':begin,'to':end},
            headers={'User-Agent':'Mozilla/5.0 ZigZagBot/1.0'},timeout=8)
        safe={k:v for k,v in response.headers.items() if k.lower() in SAFE_HEADERS}
        out=dict(begin=begin,end=end,http_status=response.status_code,headers=safe)
        if response.status_code!=200:return dict(**out,status='http_error',elapsed_seconds=time.monotonic()-started)
        try:payload=response.json()
        except ValueError:return dict(**out,status='malformed_json',elapsed_seconds=time.monotonic()-started)
        return dict(**out,source_json=payload,**classify(payload,parser),elapsed_seconds=time.monotonic()-started)
    except Exception as exc:
        # Do not log exception text: a transport might embed credentials/URL.
        return dict(begin=begin,end=end,status='transport_error',error_type=type(exc).__name__,elapsed_seconds=time.monotonic()-started)

def check_consistency(rows):
    contradictions=[]
    valid=[r for r in rows if r.get('http_status')==200 and r.get('parsed_count') is not None]
    for big in valid:
        known={(e['currency'],e['name'],e['date']) for e in big['events']}
        for small in valid:
            if big is small or not (big['begin']<=small['begin'] and big['end']>=small['end']):continue
            # Compare events observed inside the smaller requested day bounds.
            events=[e for e in small['events'] if small['begin']<=date.fromisoformat(e['date'][:10]).isoformat()<=small['end']]
            missing=[e for e in events if (e['currency'],e['name'],e['date']) not in known]
            if missing:contradictions.append(dict(big=[big['begin'],big['end']],small=[small['begin'],small['end']],missing_count=len(missing),missing_events=missing))
    return contradictions

def child():
    parser,digest=load_existing_parser();rows=[fetch_one(a,b,parser) for a,b in RANGES]
    return dict(observed_utc=datetime.now(timezone.utc).isoformat(),parser_source_sha256=digest,
                requests=rows,contradictions=check_consistency(rows),diagnostic_only=True)

def bounded_child(command,deadline=36):
    try:
        completed=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',timeout=deadline,check=False)
    except subprocess.TimeoutExpired:
        return dict(status='parent_deadline',deadline_seconds=deadline,diagnostic_only=True)
    if completed.returncode:return dict(status='child_error',returncode=completed.returncode,diagnostic_only=True)
    try:return json.loads(completed.stdout)
    except ValueError:return dict(status='child_malformed_output',diagnostic_only=True)

def main():
    if '--child' in sys.argv:print(json.dumps(child()));return
    report=bounded_child([sys.executable,str(Path(__file__).resolve()),'--child'])
    (HERE/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    view={k:v for k,v in report.items() if k!='requests'}
    view['requests']=[{k:v for k,v in row.items() if k not in ('source_json','events')} for row in report.get('requests',[])]
    print(json.dumps(view),flush=True)

if __name__=='__main__':main()

"""Bounded local research batch; no scheduling, trading or production imports.

Default validates existing reports. --run explicitly reruns both fixed scripts
in parallel with a hard child timeout; completing a batch does not start another.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
JOBS=('research_fix_20261016','research_alternative_20261016')


def validate(report, protocol_hash):
    if report.get('protocol_sha256')!=protocol_hash:
        raise ValueError('Protocol changed or report belongs to another protocol')
    if not isinstance(report.get('gate'),bool):
        raise ValueError('Missing explicit candidate pass/fail gate')
    pairs=report.get('arms',report.get('pairs'))
    if 'arms' in report and 'pairs' in report:
        raise ValueError('Ambiguous competing pair collections')
    if not isinstance(pairs,dict) or set(pairs)!={'EURUSD','GBPUSD'}:
        raise ValueError('Expected both frozen pair reports, not a selected winner')
    return report['gate']


def job(name, run=False, timeout=180):
    folder=ROOT/name
    if name not in JOBS or not folder.is_dir():
        raise ValueError('Unrecognized/missing research job')
    script=folder/'run.py';protocol=folder/'PROTOCOL.md';result=folder/'result.json'
    before=hashlib.sha256(protocol.read_bytes()).hexdigest()
    code_hash=hashlib.sha256(script.read_bytes()).hexdigest()
    status=dict(job=name,completed=False,candidate_passed=None,execution_requested=run,
                protocol_sha256=before,source_sha256_at_verification=code_hash)
    if run:
        env=dict(os.environ,DATABASE_URL='sqlite:///:memory:',AUTOTRADE_ENABLED='false',
                 BINOMO_EXECUTOR_ENABLED='false',BINOMO_ACCOUNT_MODE='demo')
        child=subprocess.Popen([sys.executable,str(script)],cwd=ROOT,env=env,
                               stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
                               encoding='utf-8',errors='replace')
        try:
            stdout,stderr=child.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            child.kill();child.communicate()
            return dict(status,error='hard_timeout_child_stopped')
        status.update(exit_code=child.returncode,stdout_characters=len(stdout),stderr_characters=len(stderr))
        if child.returncode:
            return dict(status,error='research_process_failed_not_candidate_loss')
    if not result.is_file():
        return dict(status,error='missing_result_not_zero_profit')
    if hashlib.sha256(protocol.read_bytes()).hexdigest()!=before or hashlib.sha256(script.read_bytes()).hexdigest()!=code_hash:
        return dict(status,error='source_or_protocol_changed_during_verification')
    try:
        report=json.loads(result.read_text('utf-8'))
        passed=validate(report,before)
        pairs=report.get('arms',report.get('pairs'))
        unknown=sum(r['status']!='closed' for pair in pairs.values()
                    for arm in pair['scenarios'].values() for r in arm['rows'])
        status.update(unknown_scenario_outcomes=unknown,full_period_cash_available=unknown==0)
        for artifact,digest in report.get('original_hashes',{}).items():
            if artifact not in ('lgbm_model.pkl','lgbm_scaler.pkl'):
                raise ValueError('Unexpected model artifact target')
            if hashlib.sha256((ROOT/artifact).read_bytes()).hexdigest()!=digest:
                raise ValueError('Original model changed')
    except (ValueError,KeyError,TypeError) as exc:
        return dict(status,error=str(exc))
    return dict(status,completed=True,candidate_passed=passed,
                result_sha256=hashlib.sha256(result.read_bytes()).hexdigest())


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',action='store_true')
    args=parser.parse_args()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda name:job(name,run=args.run),JOBS))
    output=dict(jobs=results,all_completed=all(r['completed'] for r in results),
                any_candidate_passed=any(r['candidate_passed'] is True for r in results),
                persistent_background_worker=False,live_trading=False)
    print(json.dumps(output,ensure_ascii=False))
    if not output['all_completed']:raise SystemExit(1)


if __name__=='__main__':main()

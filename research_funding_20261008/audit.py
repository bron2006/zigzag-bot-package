"""Independent cash-flow equations; no simulator/network imports."""
from datetime import datetime,timezone
import json
import math
from pathlib import Path

FOLDER=Path(__file__).resolve().parent


def audit():
    raw={s:json.loads((FOLDER/(s+'_raw.json')).read_text()) for s in ('BTCUSDT','ETHUSDT')}
    histories={s:json.loads((FOLDER.parent/'research_new_methods_20261007'/'public_daily'/(s+'_1d.json')).read_text())['rows'] for s in raw}
    cash_checks=0
    relative_checks=0
    largest=0.
    funding=json.loads((FOLDER/'results_v1.json').read_text())
    for asset in funding['results']:
        symbol=asset['symbol']
        spot={r[0]:r for r in histories[symbol]}
        for scenario,blocks in asset['scenarios'].items():
            sf,ff=(.0015,.001) if scenario=='base' else (.003,.002)
            for block in blocks.values():
                nav=1000.
                for saved in block['months']:
                    bars=month_bars(raw[symbol],saved['month'])
                    start,end=bars[0][0],bars[-1][0]
                    so,sc=float(spot[start][1]),float(spot[end][4])
                    fo,fc=float(bars[0][1]),float(bars[-1][4])
                    qty=nav*.5/so
                    credit=qty*funding_sum(raw[symbol],start,end)
                    value=nav-qty*so-qty*so*sf-qty*fo*ff+qty*sc*(1-sf)+qty*(fo-fc)-qty*fc*ff+credit
                    difference=abs(value-saved['end_nav'])
                    if difference>1e-8:raise AssertionError('Funding cash audit mismatch')
                    largest=max(largest,difference);cash_checks+=1;nav=value
    relative=json.loads((FOLDER/'relative_results_v1.json').read_text())
    for scenario,blocks in relative['scenarios'].items():
        fee=.001 if scenario=='base' else .002
        for block in blocks.values():
            for model in block['models'].values():
                nav=1000.
                for saved in model['months']:
                    values=[]
                    if not saved['direction']:values=[nav]
                    else:
                        for symbol,d in [('BTCUSDT',saved['direction']),('ETHUSDT',-saved['direction'])]:
                            bars=month_bars(raw[symbol],saved['month'])
                            opening,closing=float(bars[0][1]),float(bars[-1][4])
                            qty=nav*.5/opening
                            flows=-d*qty*funding_sum(raw[symbol],bars[0][0],bars[-1][0])
                            values.append(nav*.5+d*qty*(closing-opening)+flows-qty*(opening+closing)*fee)
                            relative_checks+=1
                    end=math.fsum(values)
                    difference=abs(end-saved['end_nav'])
                    if difference>1e-8:raise AssertionError('Relative cash audit mismatch')
                    largest=max(largest,difference);nav=end
    return dict(passed=True,funding_month_checks=cash_checks,relative_leg_checks=relative_checks,max_difference=largest)


def month_bars(raw,month):
    return [r for r in raw['future'] if datetime.fromtimestamp(r[0]/1000,timezone.utc).strftime('%Y-%m')==month]


def funding_sum(raw,start,last_day):
    return math.fsum(float(r['markPrice'])*float(r['fundingRate']) for r in raw['rates'] if start<int(r['fundingTime'])<last_day+86400000)


if __name__=='__main__':print(json.dumps(audit()))

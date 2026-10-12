"""Independent Decimal journal invariants, no broker/production imports."""
from decimal import Decimal
import json
from pathlib import Path


def main():
    report=json.loads(Path(__file__).with_name('result.json').read_text(encoding='utf-8'))
    costs={'base':Decimal('.0002'),'stress':Decimal('.0004')}
    total=0
    for arm in report['arms']:
        cash=Decimal('1000.00');days=set();last=-1
        for row in arm['journal']:
            assert row['day'] not in days
            days.add(row['day'])
            assert row['entry_ts']>last and row['exit_ts']>row['entry_ts']
            last=row['exit_ts']
            units=Decimal(str(row['units']));entry=Decimal(str(row['entry']))
            distance=Decimal(row['side'])*(entry-Decimal(str(row['stop'])))
            assert units>=1000 and units%1000==0
            assert units*(distance+costs[arm['scenario']])<=cash*Decimal('.005')+Decimal('.00000001')
            assert units*entry<=cash*5+Decimal('.00000001')
            expected=(units*(Decimal(row['side'])*(Decimal(str(row['exit']))-entry)-costs[arm['scenario']])).quantize(Decimal('.01'))
            assert expected==Decimal(row['net_usd'])
            cash+=expected
            assert cash==Decimal(row['balance_usd'])
            total+=1
        assert cash==Decimal(arm['balance']) and cash-1000==Decimal(arm['net'])
    assert not report['production_active'] and not report['proven_edge']
    print(json.dumps(dict(checked_records=total,arms=len(report['arms']),money_exact=True,gates=report['gates'],production_active=False)))


if __name__=='__main__':main()

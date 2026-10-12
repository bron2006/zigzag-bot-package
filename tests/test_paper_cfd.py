import unittest
from datetime import date
from decimal import Decimal
from paper_cfd import size_position,simulate_stop_trade,net_usd


def bar(ts=0,o=100,h=101,l=99,c=100):
    return dict(ts=ts,Open=o,High=h,Low=l,Close=c)


class PaperCFDTest(unittest.TestCase):
    def test_sequential_ledger_never_overlaps_positions(self):
        from research_entry_20261012.cfd_compare import account
        data=[bar(i*300) for i in range(78)]
        data[2]=bar(600,h=104)
        intents=[dict(direction=1,atr=2) for _ in data]
        result=account(data,intents,[(date(2026,10,12),[b['ts'] for b in data])],
                       'immediate',.5,dict(minVolume=10,stepVolume=10,maxVolume=10000))
        self.assertEqual(len(result['journal']),2)
        first,second=result['journal']
        self.assertGreaterEqual(second['entry_ts'],first['exit_ts'])
        self.assertEqual(result['balance_usd'],'1004.00')

    def test_cancelled_waiting_setup_still_reserves_time(self):
        from research_entry_20261012.cfd_compare import account
        data=[bar(i*300,o=99.9,h=100,l=99.8,c=99.9) for i in range(78)]
        data[0]=bar(o=100,h=100.1,l=99.9,c=100)
        result=account(data,[dict(direction=1,atr=1) for _ in data],
                       [(date(2026,10,12),[b['ts'] for b in data])],'pullback_confirm',0,
                       dict(minVolume=10,stepVolume=10,maxVolume=10000))
        self.assertEqual(len(result['journal']),0)
        self.assertEqual(result['reasons']['confirmation_timeout'],24)

    def test_risk_sizing_includes_cost_and_rounds_down(self):
        units=size_position(1000,100,2,.5,minimum=.1,step=.1,maximum=100)
        self.assertEqual(units,2)
        self.assertLessEqual(units*(2+.5),5)
        self.assertEqual(size_position(100,100,20,1,minimum=1,step=1,maximum=100),0)

    def test_notional_cap_and_currency_conversion_fail_closed(self):
        units=size_position(1000,20000,1,0,minimum=.1,step=.1,maximum=250)
        self.assertEqual(units,.2)
        with self.assertRaises(ValueError):
            size_position(1000,100,2,0,minimum=1,step=1,maximum=100,quote_currency='JPY')

    def test_stop_first_when_both_levels_touched(self):
        trade=simulate_stop_trade([bar(h=104,l=97)],0,1,2)
        self.assertEqual(trade['exit'],98)
        self.assertTrue(trade['ambiguous'])

    def test_adverse_gap_exceeds_planned_stop(self):
        trade=simulate_stop_trade([bar(),bar(300,o=95,h=96,l=94,c=95)],0,1,2)
        self.assertEqual(trade['reason'],'stop_gap')
        self.assertEqual(trade['gross_points'],-5)

    def test_target_has_no_favorable_gap_bonus(self):
        trade=simulate_stop_trade([bar(),bar(300,o=110,h=111,l=109,c=110)],0,1,2)
        self.assertEqual(trade['exit'],103)

    def test_not_closed_just_because_fifteen_minutes_elapsed(self):
        data=[bar(i*300) for i in range(10)]+[bar(3000,h=104)]
        trade=simulate_stop_trade(data,0,1,2)
        self.assertEqual(trade['reason'],'target')
        self.assertGreater(trade['exit_ts'],900)

    def test_gap_is_unknown_not_invented_loss(self):
        self.assertEqual(simulate_stop_trade([bar(),bar(600)],0,1,2)['status'],'unknown')

    def test_short_symmetry_session_end_and_money(self):
        a=simulate_stop_trade([bar(h=104,l=99)],0,1,2)
        b=simulate_stop_trade([bar(h=101,l=96)],0,-1,2)
        self.assertEqual(a['gross_points'],b['gross_points'])
        self.assertEqual(simulate_stop_trade([bar()],0,1,2)['reason'],'session_end')
        self.assertEqual(net_usd(.2,10,2),Decimal('1.60'))

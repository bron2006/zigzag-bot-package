import copy
import unittest
from entry_rules import choose_entry, settle


def bars(closes, opens=None):
    opens = opens or [closes[0]]+closes[:-1]
    return [dict(ts=i*300, Open=o, Close=c) for i,(o,c) in enumerate(zip(opens,closes))]


class EntryRuleTest(unittest.TestCase):
    def test_immediate_is_next_open_not_signal_close(self):
        data=bars([100,101,102,103], [99,100.5,101,102])
        entry=choose_entry(data,0,1,1,'immediate')
        self.assertEqual(entry['price'],100.5)
        result=settle(data,entry,1)
        self.assertEqual(result['expiry_ts'],1200)
        self.assertEqual(result['status'],'win')

    def test_pullback_requires_subsequent_confirmation_then_next_open(self):
        data=bars([100,99.6,99.8,100,101,102])
        entry=choose_entry(data,0,1,1,'pullback_confirm')
        self.assertEqual(entry['index'],3)
        self.assertEqual(entry['price'],99.8)
        self.assertEqual(settle(data,entry,1)['expiry_ts'],1800)

    def test_buy_sell_symmetry(self):
        data=bars([100,99.6,99.8,100,101,102])
        reflected=[dict(ts=b['ts'],Open=200-b['Open'],Close=200-b['Close']) for b in data]
        a=choose_entry(data,0,1,1,'pullback_confirm')
        b=choose_entry(reflected,0,-1,1,'pullback_confirm')
        self.assertEqual(a['index'],b['index'])
        self.assertEqual(settle(data,a,1)['unit_pnl'],settle(reflected,b,-1)['unit_pnl'])

    def test_no_future_leak(self):
        data=bars([100,99.6,99.8,100,101,102])
        original=choose_entry(data,0,1,1,'pullback_confirm')
        poisoned=copy.deepcopy(data)
        for bar in poisoned[3:]: bar['Close']=100000
        self.assertEqual(original,choose_entry(poisoned,0,1,1,'pullback_confirm'))

    def test_invalidation_chase_timeout_and_open_gap(self):
        for values,reason in [([100,99.2],'idea_invalidated'),([100,100.6],'price_ran_away'),
                              ([100,99.9,99.9,99.9],'confirmation_timeout')]:
            self.assertEqual(choose_entry(bars(values),0,1,1,'pullback_confirm')['reason'],reason)
        data=bars([100,99.6,99.8,100],[100,100,99.6,102])
        self.assertEqual(choose_entry(data,0,1,1,'pullback_confirm')['reason'],'gap_outside_entry_zone')

    def test_gap_never_counts_as_skip_or_loss(self):
        data=bars([100,99.6,99.8,100])
        data[1]['ts']=600
        for policy in ('immediate','delay_one_bar','pullback_confirm'):
            self.assertEqual(choose_entry(data,0,1,1,policy)['status'],'unknown')

    def test_missing_future_and_exact_equal_refund(self):
        self.assertEqual(choose_entry(bars([100]),0,1,1,'immediate')['status'],'unresolved')
        data=bars([100,100,100,100])
        self.assertEqual(settle(data,choose_entry(data,0,1,1,'immediate'),1)['status'],'refund')
        self.assertEqual(settle(data[:2],choose_entry(data,0,1,1,'immediate'),1)['status'],'unknown')

    def test_bad_parameters(self):
        for atr in (0,-1,float('nan')):
            with self.assertRaises(ValueError): choose_entry(bars([100]),0,1,atr,'immediate')

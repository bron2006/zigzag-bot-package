import unittest
from research_crossasset_20261015.screen import signals, outcome, ci
from research_crossasset_20261015.index_screen import simulate as index_simulate
from research_crossasset_20261015.flow_screen import signals as flow_signals, outcome as flow_outcome


def bars(n=220):
    return [dict(ts=1704067200+i*3600, Open=100., Close=100.+(i%3)*.01) for i in range(n)]


class CrossAssetScreenTests(unittest.TestCase):
    def test_leader_closed_signal_waits_full_hour(self):
        b, e = bars(), bars()
        b[10]['Close'] = 102
        found = signals(b, e, 'leader_lag')
        self.assertEqual(found[0]['entry_index'], 12)
        self.assertEqual(found[0]['exit_index'], 18)
        self.assertEqual(found[0]['ts'], b[10]['ts']+7200)

    def test_eth_already_followed_not_lag(self):
        b, e = bars(), bars()
        b[10]['Close'], e[10]['Close'] = 102, 101.5
        self.assertEqual(signals(b, e, 'leader_lag'), [])

    def test_ratio_uses_prior_and_fades_expensive(self):
        b, e = bars(), bars()
        for i in range(168): b[i]['Close'] += (i%2)*.02
        b[168]['Close'] = 104
        first = signals(b, e, 'ratio_reversion')[0]
        self.assertEqual(first['signal_index'], 168)
        self.assertEqual(first['side'], -1)
        self.assertEqual(first['entry_index'], 170)

    def test_future_poison_does_not_change_known_signals(self):
        b, e = bars(), bars()
        for i in range(168): b[i]['Close'] += (i%2)*.02
        b[168]['Close'] = 104
        for arm in ('ratio_reversion', 'leader_lag'):
            before = [r for r in signals(b, e, arm) if r['signal_index'] < 180]
            changed = [dict(r, Close=1000000.) if i>=180 else r for i,r in enumerate(b)]
            after = [r for r in signals(changed, e, arm) if r['signal_index'] < 180]
            self.assertEqual(before, after)

    def test_planned_cooldown_not_future_outcome(self):
        b, e = bars(), bars()
        for i in range(10, 30): b[i]['Close'] = 102
        found = signals(b, e, 'leader_lag')
        self.assertTrue(all(a['exit_index']<=z['entry_index'] for a,z in zip(found,found[1:])))

    def test_fixed_initial_units_weighted_pair_and_financing(self):
        b,e = bars(30),bars(30)
        b[24]['Open'],e[24]['Open'] = 110,120
        intent = dict(entry_index=0,exit_index=24,horizon=24)
        result = outcome(intent,b,e,'ratio_reversion',-1,.003)
        self.assertAlmostEqual(result['gross'], .05)
        self.assertAlmostEqual(result['net'], .05-.003-.20*24/(365*24)*.5)

    def test_short_single_no_long_charge_and_pending_not_zero(self):
        b,e = bars(30),bars(30)
        intent = dict(entry_index=0,exit_index=6,horizon=6)
        r = outcome(intent,b,e,'leader_lag',-1,.003)
        self.assertEqual(r['carry'],0)
        self.assertAlmostEqual(r['net'],-.003)
        intent['exit_index']=30
        self.assertEqual(outcome(intent,b,e,'leader_lag',1,.003),dict(status='pending'))

    def test_unsynchronized_inputs_rejected(self):
        b,e = bars(),bars()
        e[10]['ts']+=1
        with self.assertRaises(ValueError):signals(b,e,'leader_lag')

    def test_bootstrap_repeatable_constant(self):
        self.assertEqual(ci([.01,.01],[0,5],20),ci([.01,.01],[0,5],20))
        self.assertAlmostEqual(ci([.01,.01],[0,5],20)[0],100)

    def test_index_entry_bar_stop(self):
        p=[dict(ts=i*300,Open=100.,High=101.,Low=99.,Close=100.) for i in range(27)]
        p[15]['Low']=95
        self.assertEqual(index_simulate(p[:15],p[15:],1)['gross_points'],-4)
        p[15]['Low']=99;p[15]['High']=105
        self.assertEqual(index_simulate(p[:15],p[15:],-1)['gross_points'],-4)

    def test_index_adverse_gap_no_cap_and_no_future_stop_distance(self):
        p=[dict(ts=i*300,Open=100.,High=101.,Low=99.,Close=100.) for i in range(27)]
        p[16].update(Open=90.,Low=89.,High=91.,Close=90.)
        r=index_simulate(p[:15],p[15:],1)
        self.assertEqual(r['gross_points'],-10)
        self.assertEqual(r['reason'],'stop_gap')
        self.assertEqual(r['risk_points'],4)

    def test_index_missing_bar_not_fake_close(self):
        p=[dict(ts=i*300,Open=100.,High=101.,Low=99.,Close=100.) for i in range(27)]
        self.assertEqual(index_simulate(p[:15],p[16:],1),dict(status='unknown'))

    def test_flow_prior_volume_delay_and_cooldown(self):
        p=[dict(ts=i*900,Open=100.,Close=100.,Volume=100.,Buy=50.) for i in range(40)]
        for i in range(20,30):p[i].update(Volume=300.,Buy=240.)
        found=flow_signals(p)
        self.assertEqual(found[0],dict(ts=20*900+1800,entry_index=22,exit_index=26,side=1))
        self.assertTrue(all(a['exit_index']<=b['entry_index'] for a,b in zip(found,found[1:])))

    def test_flow_future_poison_and_sell_direction(self):
        p=[dict(ts=i*900,Open=100.,Close=100.,Volume=100.,Buy=50.) for i in range(40)]
        p[20].update(Volume=300.,Buy=60.)
        first=flow_signals(p)[0]
        self.assertEqual(first['side'],-1)
        for r in p[25:]:r.update(Volume=100000.,Buy=100000.)
        self.assertEqual(first,flow_signals(p)[0])

    def test_flow_uses_open_at_full_horizon_and_pending(self):
        p=[dict(Open=100.) for i in range(30)];p[26]['Open']=110
        intent=dict(entry_index=22,exit_index=26)
        r=flow_outcome(intent,p,1,.003)
        self.assertAlmostEqual(r['net'],.1-.003-.2/(365*24))
        self.assertEqual(flow_outcome(intent,p[:26],1,.003),dict(status='pending'))


if __name__=='__main__': unittest.main()

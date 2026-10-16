import unittest
from datetime import date,datetime,timezone
from research_alternative_20261016.run import slot,fit_directions,prior_atr,replay,block_ci

class CalendarResearchTests(unittest.TestCase):
    def test_ci_never_uses_after_censoring(self):
        start=int(datetime(2025,1,1,tzinfo=timezone.utc).timestamp())
        early=dict(decision_ts=start+86400,status='closed',net_R=1.)
        late=dict(decision_ts=start+30*86400,status='closed',net_R=1e9)
        self.assertEqual(block_ci([early],'net_R',2025,start+20*86400),
                         block_ci([early,late],'net_R',2025,start+20*86400))

    def test_dst_and_delay(self):
        winter,entry=slot(date(2025,1,6));summer,_=slot(date(2025,7,7))
        self.assertEqual(entry-winter,300)
        self.assertEqual(datetime.fromtimestamp(winter,timezone.utc).hour,8)
        self.assertEqual(datetime.fromtimestamp(summer,timezone.utc).hour,7)

    def test_train_future_is_ignored(self):
        future=slot(date(2025,1,6))[1]
        path={future+i*300:dict(Open=1.,Close=2.) for i in range(48)}
        self.assertTrue(all(v['side']==0 and v['n']==0 for v in fit_directions(path).values()))

    def test_incomplete_training_day_not_zero_return(self):
        t=slot(date(2024,1,2))[1]
        path={t+i*300:dict(Open=1.,Close=1.001) for i in range(48)}
        self.assertEqual(fit_directions(path)['1']['n'],1)
        del path[t+300]
        self.assertEqual(fit_directions(path)['1']['n'],0)

    def test_minimum_training_and_no_future_price(self):
        self.assertIsNone(prior_atr([],100000))
        bars=[dict(ts=i*3600,High=1.102,Low=1.1,Close=1.101) for i in range(16)]
        atr=prior_atr(bars,15*3600)
        bars[-1].update(High=10.,Low=.1)
        self.assertAlmostEqual(atr,.002)
        self.assertAlmostEqual(prior_atr(bars,15*3600),atr)
        self.assertIsNone(prior_atr(bars,30*3600))

    def test_unknown_entry_halts_not_flat(self):
        vol=dict(minVolume=1000.,stepVolume=1000.,maxVolume=1e8)
        intent=dict(entry_ts=100000,decision_ts=99700,side=1,stop_distance=.002,signal_close=1.1,month='2025-01')
        rows,skips=replay([intent,dict(intent,entry_ts=200000)],{},vol,.0004)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['status'],'unknown')
        self.assertEqual(rows[0]['reason'],'missing_entry')

    def test_minimum_size_not_forced(self):
        vol=dict(minVolume=1000.,stepVolume=1000.,maxVolume=1e8)
        intent=dict(entry_ts=100000,decision_ts=99700,side=1,stop_distance=.1,signal_close=1.1,month='2025-01')
        rows,skips=replay([intent],{},vol,.0004)
        self.assertEqual(rows,[]);self.assertEqual(skips['decision_minimum_size'],1)

    def test_stop_first_and_identical_opportunities(self):
        vol=dict(minVolume=1000.,stepVolume=1000.,maxVolume=1e8)
        intent=dict(entry_ts=100000,decision_ts=99700,side=1,stop_distance=.002,signal_close=1.1,month='2025-01')
        bt={100000:dict(Open=1.1,High=1.105,Low=1.097,Close=1.1)}
        a,_=replay([intent],bt,vol,.0002);b,_=replay([intent],bt,vol,.0004)
        self.assertEqual(a[0]['reason'],'stop');self.assertTrue(a[0]['ambiguous'])
        self.assertEqual(a[0]['entry_ts'],b[0]['entry_ts']);self.assertAlmostEqual(b[0]['net_R'],-1.)

if __name__=='__main__':unittest.main()

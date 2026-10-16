import unittest
from decimal import Decimal as D
from research_weekend_20261016.run import atr_at,simulate,costed,observations,block_ci,START,HOUR,WEEK

def bar(op='100',high='101',low='99',close='100'):
    return dict(zip(('Open','High','Low','Close'),map(D,(op,high,low,close))))

class WeekendResearchTests(unittest.TestCase):
    def test_atr_only_completed_bars_and_previous_close(self):
        bt={i*HOUR:bar() for i in range(18)}
        before=atr_at(bt,15*HOUR)
        self.assertEqual(before,D(2))
        bt[15*HOUR]=bar(high='1000',low='1')
        self.assertEqual(atr_at(bt,15*HOUR),before)
        del bt[0]
        self.assertIsNone(atr_at(bt,15*HOUR))

    def test_entry_bar_stop(self):
        out=simulate({0:bar(low='97')},0,1,D(2),end=100*HOUR)
        self.assertEqual(out['status'],'closed');self.assertEqual(out['exit'],98.)
        self.assertEqual(out['charged_hours'],1);self.assertEqual(out['reason'],'stop')

    def test_adverse_gap_not_stop_price(self):
        out=simulate({0:bar(),HOUR:bar(op='95',high='96',low='94',close='95')},0,1,D(2),end=100*HOUR)
        self.assertEqual(out['exit'],95.);self.assertEqual(out['charged_hours'],1)
        self.assertEqual(out['reason'],'gap_stop')

    def test_deadline_actual_open_not_last_close(self):
        bt={i*HOUR:bar() for i in range(49)};bt[48*HOUR]=bar(op='105',high='106',low='104',close='105')
        out=simulate(bt,0,1,D(10),end=100*HOUR)
        self.assertEqual(out['exit'],105.);self.assertEqual(out['charged_hours'],48)
        self.assertAlmostEqual(out['gross'],.05)

    def test_pending_not_forced_and_missing_not_zero(self):
        bt={i*HOUR:bar() for i in range(24)}
        self.assertEqual(simulate(bt,0,1,D(10),end=24*HOUR)['status'],'pending')
        self.assertEqual(simulate(bt,0,1,D(10),end=100*HOUR)['status'],'unknown')
        self.assertEqual(simulate({},0,1,D(10),end=100*HOUR)['reason'],'missing_entry')

    def test_costs_initial_notional_and_actual_hours(self):
        base=dict(status='closed',side=1,charged_hours=24,gross=.01)
        out=costed(base,'stress')
        self.assertAlmostEqual(out['net'],.01-.003-.2*24/(365*24))
        self.assertEqual(costed(dict(base,side=-1),'stress')['financing'],0.)
        self.assertEqual(costed(base,'gross')['net'],.01)

    def test_delay_own_weekday_atr_and_unknown_halt(self):
        bt={START+i*HOUR:bar() for i in range(3*7*24)}
        fri=START+4*86400+20*HOUR
        del bt[fri+3*HOUR]
        rows=observations(bt,START+3*WEEK)
        self.assertEqual(rows[0]['arms']['weekend']['status'],'unknown')
        self.assertEqual(rows[1]['arms']['weekend']['status'],'halted')
        self.assertEqual(rows[0]['arms']['weekend']['decision_ts'],fri-HOUR)
        self.assertEqual(rows[0]['arms']['weekend']['atr_last_ts']+HOUR,fri-HOUR)
        self.assertNotEqual(rows[0]['arms']['weekday']['atr_last_ts'],rows[0]['arms']['weekend']['atr_last_ts'])

    def test_bootstrap_missing_not_zero_returns(self):
        rows=[dict(week=i*WEEK) for i in range(30)]
        self.assertEqual(block_ci(rows,{0:.01}),[100.,100.])

if __name__=='__main__':unittest.main()

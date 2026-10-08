import unittest
from datetime import datetime, timezone
from vwap_attribution import event_index, hindsight

class AttributionTests(unittest.TestCase):
    def rows(self):
        start=int(datetime(2026,9,1,8,tzinfo=timezone.utc).timestamp())
        return [dict(ts=start+i*300,Low=102.,High=103.,Close=102.,lower=100.,vwap=101.) for i in range(96)]
    def test_early_first_touch_excludes_original_day(self):
        rows=self.rows(); rows[20]['Low']=99.; rows[50]['Low']=99.
        self.assertIsNone(event_index(rows,False))
        self.assertEqual(event_index(rows,True),50)
    def test_1155_bar_known_at_1200_is_eligible(self):
        rows=self.rows(); rows[47]['Low']=99.
        self.assertEqual(event_index(rows,True),47)
        self.assertEqual(event_index(rows,False),47)
    def test_warmup_and_missing_band(self):
        rows=self.rows(); rows[5]['Low']=99.; rows[50]['Low']=99.; rows[50]['lower']=float('nan')
        self.assertIsNone(event_index(rows,False))
    def test_legacy_does_not_exit_on_event_bar(self):
        rows=self.rows(); rows[50]['Low']=97.; rows[50]['High']=105.
        result=hindsight(rows,50,100.,99.,.1)
        self.assertEqual(result['outcome'],'SESSION_END')
    def test_legacy_same_bar_stop_first(self):
        rows=self.rows(); rows[51]['Low']=98.; rows[51]['High']=105.
        self.assertEqual(hindsight(rows,50,100.,99.,.1)['outcome'],'STOP')

if __name__=='__main__':
    unittest.main()

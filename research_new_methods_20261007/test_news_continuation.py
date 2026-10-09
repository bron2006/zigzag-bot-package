import unittest
from news_event_calendar import events
from news_continuation import signal,snapshot,outcome,summarize,ci


def bars():
    result=[]
    for ts in range(13500,18000,300):
        result.append({'utcTimestampInMinutes':ts//60,'low':99900,
                       'deltaOpen':100,'deltaClose':100,'deltaHigh':200})
    result.append({'utcTimestampInMinutes':300,'low':99900,
                   'deltaOpen':100,'deltaClose':500,'deltaHigh':600})
    return result


class NewsContinuationTest(unittest.TestCase):
    def test_dst_and_actual_publication_dates(self):
        rows={e['id']:e for e in events()}
        self.assertEqual(rows['2024-01-05_empsit']['release_utc'],'2024-01-05T13:30:00+00:00')
        self.assertEqual(rows['2026-09-04_empsit']['release_utc'],'2026-09-04T12:30:00+00:00')
        self.assertIn('2026-02-11_empsit',rows) # Wednesday, not invented firstFriday.
        self.assertNotIn('2025-10-03_empsit',rows) # Cancelled publication.
        self.assertEqual(len(rows),65)

    def test_first_impulse_after_release_not_before(self):
        result=signal(bars(),18000)
        self.assertEqual(result['status'],'selected')
        self.assertEqual(result['direction'],1)
        self.assertEqual(result['decision_ts'],18300)
        self.assertAlmostEqual(result['atr'],.002)

    def test_future_candle_cannot_change_signal(self):
        first=signal(bars(),18000)
        future=bars()+[{'utcTimestampInMinutes':305,'low':100,
                       'deltaOpen':0,'deltaClose':0,'deltaHigh':0}]
        self.assertEqual(signal(future,18000),first)

    def test_missing_past_bar_not_interpolated(self):
        self.assertEqual(signal(bars()[1:],18000)['status'],'missing_bars')

    def test_weak_impulse_waits(self):
        raw=bars();raw[-1]['deltaClose']=150
        self.assertEqual(signal(raw,18000)['status'],'weak_impulse')

    def test_joined_quote_causal_age_and_window(self):
        quotes={'BID':[{'timestamp_ms':999,'price':1.}],
                'ASK':[{'timestamp_ms':1001,'price':1.001}]}
        result=snapshot(quotes,1000)
        self.assertEqual(result['timestamp_ms'],1001)
        quotes['BID'][0]['timestamp_ms']=0
        self.assertIsNone(snapshot(quotes,1000))
        quotes['BID'][0]['timestamp_ms']=7000
        quotes['ASK'][0]['timestamp_ms']=7000
        self.assertIsNone(snapshot(quotes,1000))

    def test_crossed_quote_and_nonfinite_rejected(self):
        quotes={'BID':[{'timestamp_ms':1000,'price':2.}],
                'ASK':[{'timestamp_ms':1000,'price':1.}]}
        self.assertIsNone(snapshot(quotes,1000))
        quotes['ASK'][0]['price']=float('nan')
        with self.assertRaises(ValueError):
            snapshot(quotes,1000)

    def test_forex_spread_cost_and_binary_are_separate(self):
        entry={'bid':1.,'ask':1.0002,'timestamp_ms':1000}
        end={'bid':1.0005,'ask':1.0007,'timestamp_ms':301000}
        long=outcome(1,entry,end);short=outcome(-1,entry,end)
        self.assertAlmostEqual(long['forex_net_pips'],2.3)
        self.assertAlmostEqual(long['forex_stress_pips'],1.3)
        self.assertAlmostEqual(short['forex_net_pips'],-7.7)
        self.assertEqual(long['midpoint_direction'],1)
        self.assertEqual(short['midpoint_direction'],-1)

    def test_missing_quotes_are_unknown_not_loss(self):
        self.assertEqual(outcome(1,None,None)['status'],'missing_endpoint')
        summary=summarize([{'status':'missing_endpoint','selected':True}])
        self.assertEqual(summary['coverage'],0.)
        self.assertNotIn('midpoint_winrate',summary)

    def test_bootstrap_no_data_is_not_edge(self):
        self.assertIsNone(ci([]));self.assertIsNone(ci([1.]))
        self.assertEqual(ci([1.,1.,1.]),[1.,1.])

    def test_late_endpoint_cannot_masquerade_as_five_minutes(self):
        entry={'bid':1.,'ask':1.0002,'timestamp_ms':1000}
        late={'bid':1.,'ask':1.0002,'timestamp_ms':500000}
        with self.assertRaises(ValueError):
            outcome(1,entry,late)


if __name__=='__main__':
    unittest.main()

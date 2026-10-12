import copy
import unittest
from session_momentum import evaluate


class SessionMomentumTest(unittest.TestCase):
    def test_signal_has_no_future_leak(self):
        times=list(range(0,23400,300))
        data={t:dict(Open=100,Close=101) for t in times}
        a=evaluate(data,times,100)
        altered=copy.deepcopy(data)
        for t in times[6:]: altered[t]=dict(Open=200,Close=190)
        b=evaluate(altered,times,100)
        self.assertEqual(a['direction'],b['direction'])
        self.assertEqual(a['signal_ts'],1800)
        self.assertEqual(a['entry_ts'],21600)
        self.assertEqual(a['expiry_ts'],23400)

    def test_missing_future_is_unknown_not_skipped(self):
        times=list(range(0,23400,300))
        data={t:dict(Open=100,Close=101) for t in times[:6]}
        result=evaluate(data,times,100)
        self.assertEqual(result['status'],'unknown')
        self.assertEqual(result['direction'],1)

    def test_previous_close_missing_and_flat_signal(self):
        times=list(range(0,23400,300))
        data={t:dict(Open=100,Close=100) for t in times}
        self.assertEqual(evaluate(data,times,None)['status'],'unknown')
        self.assertEqual(evaluate(data,times,100)['status'],'skipped')

    def test_short_signal(self):
        times=list(range(0,23400,300))
        data={t:dict(Open=100,Close=99) for t in times}
        self.assertEqual(evaluate(data,times,101)['direction'],-1)

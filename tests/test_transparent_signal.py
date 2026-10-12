import copy
import math
import unittest
from transparent_signal import generate, RULES


def sample():
    out=[]
    for i in range(80):
        o=100+i*.1
        out.append(dict(ts=i*300,Open=o,High=o+.18,Low=o-.05,Close=o+.1))
    return out


class TransparentSignalTest(unittest.TestCase):
    def test_reentry_and_trend_pullback_emit_real_setups(self):
        def from_closes(closes):
            return [dict(ts=i*300,Open=closes[max(0,i-1)],
                         High=max(closes[max(0,i-1)],c)+.05,
                         Low=min(closes[max(0,i-1)],c)-.05,Close=c)
                    for i,c in enumerate(closes)]
        cycle=from_closes([100+i*.03+.8*math.sin(i*.5) for i in range(150)])
        self.assertEqual(generate(cycle,'trend_pullback')[75]['direction'],1)
        shock=[100+.1*math.sin(i) for i in range(85)]
        shock[80],shock[81]=97,99
        data=from_closes(shock)
        self.assertEqual(generate(data,'band_reentry')[81]['direction'],1)
        for rule,series in [('trend_pullback',cycle),('band_reentry',data)]:
            reflected=[dict(ts=b['ts'],Open=300-b['Open'],High=300-b['Low'],
                            Low=300-b['High'],Close=300-b['Close']) for b in series]
            self.assertEqual([i['direction'] for i in generate(series,rule)],
                             [-i['direction'] for i in generate(reflected,rule)])

    def test_prior_level_excludes_current_high(self):
        data=sample()
        result=generate(data)
        self.assertEqual(result[-1]['direction'],1)
        self.assertLess(result[-1]['level'],data[-1]['Close'])
        self.assertEqual(result[-1]['ts'],24000)

    def test_future_changes_cannot_change_prefix(self):
        data=sample()
        first=generate(data[:75])
        changed=copy.deepcopy(data)
        for b in changed[75:]:
            for key in ('Open','High','Low','Close'): b[key]*=10
        self.assertEqual(first,generate(changed)[:75])
        for rule in RULES:
            self.assertEqual(generate(data[:75],rule),generate(changed,rule)[:75])

    def test_direction_symmetry_and_scale_invariance(self):
        data=sample()
        reflected=[dict(ts=b['ts'],Open=300-b['Open'],High=300-b['Low'],
                        Low=300-b['High'],Close=300-b['Close']) for b in data]
        scaled=[{k:v*100 if k!='ts' else v for k,v in b.items()} for b in data]
        base=generate(data)
        self.assertEqual([i['direction'] for i in base],[-i['direction'] for i in generate(reflected)])
        self.assertEqual([i['direction'] for i in base],[i['direction'] for i in generate(scaled)])
        for rule in RULES:
            self.assertEqual([i['direction'] for i in generate(data,rule)],
                             [-i['direction'] for i in generate(reflected,rule)])
            self.assertEqual([i['direction'] for i in generate(data,rule)],
                             [i['direction'] for i in generate(scaled,rule)])

    def test_gap_resets_warmup(self):
        data=sample()
        for b in data[72:]: b['ts']+=300
        result=generate(data)
        self.assertEqual(result[71]['direction'],1)
        self.assertTrue(all(i['reason']=='warmup' for i in result[72:]))

    def test_invalid_history_rejected(self):
        data=sample()
        data[-1]['ts']=data[-2]['ts']
        with self.assertRaises(ValueError): generate(data)
        data=sample()
        data[-1]['High']=1
        with self.assertRaises(ValueError): generate(data)

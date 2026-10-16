import unittest
from datetime import datetime,timezone
from research_trend_pullback_20261015.strategy import detect
from research_trend_pullback_20261015.run import replay,wf


START=int(datetime(2025,1,6,tzinfo=timezone.utc).timestamp())


def setup():
    h4=[dict(ts=START+4*3600,Close=1.12,EMA50=1.11,EMA200=1.10,ADX=25.)]
    h1=[dict(ts=START+8*3600,Open=1.111,High=1.112,Low=1.109,Close=1.110,EMA20=1.1105,ATR=.001),
        dict(ts=START+9*3600,Open=1.110,High=1.114,Low=1.110,Close=1.113,EMA20=1.1105,ATR=.001)]
    return h1,h4


class TrendPullbackTests(unittest.TestCase):
    def test_long_closed_break_and_structural_stop(self):
        h1,h4=setup();r=detect(h1,h4)[0]
        self.assertEqual(r['side'],1);self.assertAlmostEqual(r['stop'],1.1089)
        self.assertEqual(r['entry_ts'],START+10*3600+300)
        self.assertLessEqual(r['context_closed_ts'],r['decision_ts'])

    def test_wick_not_confirmation(self):
        h1,h4=setup();h1[-1]['Close']=1.1115
        self.assertEqual(detect(h1,h4),[])

    def test_future_h4_not_used_and_future_poison_no_change(self):
        h1,h4=setup();r=detect(h1,h4)
        future=dict(h4[0],ts=START+8*3600,Close=.1,EMA50=2.,EMA200=3.)
        self.assertEqual(detect(h1,h4+[future]),r)
        self.assertEqual(detect(h1,[future]),[])

    def test_short_mirror(self):
        h1,h4=setup()
        for b in h1:
            b.update(Open=2.22-b['Open'],Close=2.22-b['Close'],High=2.22-b['Low'],Low=2.22-b['High'],EMA20=2.22-b['EMA20'])
        for b in h4:
            for k in ('Close','EMA50','EMA200'):b[k]=2.22-b[k]
        r=detect(h1,h4)[0];self.assertEqual(r['side'],-1)
        self.assertAlmostEqual(r['stop'],2.22-1.1089)

    def test_gap_or_stale_context_no_signal(self):
        h1,h4=setup();h1[0]['ts']-=3600
        self.assertEqual(detect(h1,h4),[])
        h1,h4=setup();h4[0]['ts']-=86400
        self.assertEqual(detect(h1,h4),[])

    def test_adx_filter_and_order_contract(self):
        h1,h4=setup();h4[0]['ADX']=19.
        self.assertEqual(detect(h1,h4),[])
        with self.assertRaises(ValueError):detect(h1,h4+h4)

    def test_one_open_position_base_stress_share_intents(self):
        h1,h4=setup();intent=detect(h1,h4)[0]
        bt={intent['entry_ts']+i*300:dict(ts=intent['entry_ts']+i*300,Open=1.112,High=1.1125,Low=1.1115,Close=1.112) for i in range(60)}
        second=dict(intent,entry_ts=intent['entry_ts']+3600,decision_ts=intent['decision_ts']+3600)
        vol=dict(minVolume=1000.,stepVolume=1000.,maxVolume=100000000.)
        a,sa=replay([intent,second],bt,vol,.0002);b,sb=replay([intent,second],bt,vol,.0004)
        self.assertEqual((len(a),len(b)),(1,1));self.assertEqual(sa,sb)
        self.assertEqual(sa.get('position_open'),1)
        self.assertEqual(a[0]['entry_ts'],b[0]['entry_ts'])

    def test_entry_gap_risk_rechecked_without_forcing_minimum(self):
        h1,h4=setup();intent=detect(h1,h4)[0]
        bt={intent['entry_ts']:dict(ts=intent['entry_ts'],Open=1.13,High=1.14,Low=1.12,Close=1.13)}
        vol=dict(minVolume=1000.,stepVolume=1000.,maxVolume=100000000.)
        r,s=replay([intent],bt,vol,.0004)
        self.assertEqual(r,[]);self.assertEqual(s['entry_gap_minimum_size'],1)

    def test_unknown_entry_halts_not_fake_flat(self):
        h1,h4=setup();intent=detect(h1,h4)[0]
        vol=dict(minVolume=1000.,stepVolume=1000.,maxVolume=100000000.)
        rows,_=replay([intent,dict(intent,entry_ts=intent['entry_ts']+3600)],{},vol,.0004)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['status'],'unknown')

    def test_non_usd_quote_loader_rejects_before_access(self):
        with self.assertRaises(ValueError):wf.load('USDJPY')


if __name__=='__main__':unittest.main()

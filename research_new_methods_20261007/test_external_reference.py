import unittest
import statistics
import numpy as np
import pandas as pd
from external_reference import weights,calculate,parse_block,describe


def fixture():
    rng=np.random.default_rng(50)
    index=pd.bdate_range('2020-01-01',periods=220)
    returns=pd.DataFrame(rng.normal(.003,.005,(220,8)),index=index)
    factors=pd.DataFrame({'RF':.0001,'Mkt-RF':.001},index=index)
    return returns,factors


class ExternalReferenceTest(unittest.TestCase):
    def test_future_mutation_cannot_change_past_weights(self):
        r,_=fixture();changed=r.copy();changed.iloc[150:]=-.03
        pd.testing.assert_frame_equal(weights(r).iloc[:150],weights(changed).iloc[:150])

    def test_weights_lag_before_return(self):
        r,f=fixture();w=weights(r);out=calculate(r,f,w)
        i=100
        expected=float((w.iloc[i-1]*r.iloc[i]).sum()+(1-w.iloc[i-1].sum())*f.RF.iloc[i])
        self.assertAlmostEqual(out.strategy.iloc[i],expected)
        changed=w.copy();changed.iloc[i]=0
        self.assertAlmostEqual(calculate(r,f,changed).strategy.iloc[i],expected)

    def test_asset_and_aggregate_caps_and_no_short(self):
        r,_=fixture();w=weights(r)
        self.assertTrue((w>=0).all().all());self.assertTrue((w<=.2+1e-12).all().all())
        self.assertTrue((w.sum(axis=1)<=2+1e-12).all())

    def test_no_warmup_position(self):
        r,_=fixture();self.assertEqual(float(weights(r).iloc[:40].sum().sum()),0.)

    def test_cash_and_borrowing_arithmetic(self):
        r,f=fixture();w=r*0
        np.testing.assert_allclose(calculate(r,f,w).strategy,f.RF)
        w[:]=.25 # synthetic 2x reference exposures, not a trading instruction
        out=calculate(r,f,w)
        np.testing.assert_allclose(out.strategy.iloc[1:],(.25*r.sum(axis=1)-f.RF).iloc[1:])

    def test_missing_codes_and_first_block_only(self):
        text='metadata\n,A,B\n20200102,1,-99.99\n20200103,-999,2\n\nOther block\n,A,B\n20200102,8,9\n'
        frame=parse_block(text,2)
        self.assertEqual(len(frame),2);self.assertAlmostEqual(frame.iloc[0,0],.01)
        self.assertTrue(np.isnan(frame.iloc[0,1]));self.assertTrue(np.isnan(frame.iloc[1,0]))

    def test_duplicate_dates_rejected(self):
        with self.assertRaises(ValueError):parse_block(',A\n20200102,1\n20200102,2\n',1)

    def test_double_carriage_return_keeps_header_and_all_days(self):
        frame=parse_block('metadata\r\r\n,A\r\r\n20200102,1\r\r\n20200103,2\r\r\nEND',1)
        self.assertEqual(list(frame.columns),['A']);self.assertEqual(len(frame),2)
        self.assertAlmostEqual(frame.iloc[0,0],.01)

    def test_turnover_accounts_for_drift(self):
        r,f=fixture();w=r*0+.1;out=calculate(r,f,w)
        i=90;held=w.iloc[i-1];drift=held*(1+r.iloc[i])/(1+out.strategy.iloc[i])
        self.assertAlmostEqual(out.one_side_turnover.iloc[i],float((w.iloc[i]-drift).abs().sum()))

    def test_summary_no_deposit_return_claim(self):
        r,f=fixture();summary=describe(calculate(r,f,weights(r)))
        self.assertEqual(summary['observed_days'],220)
        self.assertIn('max_close_drawdown',summary['strategy'])

    def test_independent_scalar_rebuild_all_fixture_weights(self):
        r,_=fixture();expected=np.zeros(r.shape);raw=r.to_numpy()
        price=np.cumprod(1+raw,axis=0);changes=np.abs(np.diff(price,axis=0))
        ema20=price.copy();ema40=price.copy()
        for t in range(1,len(r)):
            ema20[t]=ema20[t-1]+2/21*(price[t]-ema20[t-1])
            ema40[t]=ema40[t-1]+2/41*(price[t]-ema40[t-1])
        state=[False]*r.shape[1];trails=[float('nan')]*r.shape[1]
        for t in range(40,len(r)):
            for j in range(r.shape[1]):
                old_upper=min(max(price[t-20:t,j]),ema20[t-1,j]+2.8*sum(changes[t-21:t-1,j])/20)
                old_lower=max(min(price[t-40:t,j]),ema40[t-1,j]-2.8*sum(changes[t-41:t-1,j])/40) if t>40 else max(min(price[:t,j]),ema40[t-1,j]-2.8*sum(changes[:t-1,j])/39)
                lower=max(min(price[t-39:t+1,j]),ema40[t,j]-2.8*sum(changes[t-40:t,j])/40)
                if not state[j]:
                    state[j]=bool(price[t,j]>=old_upper and old_upper>old_lower)
                    trails[j]=lower if state[j] else float('nan')
                else:
                    trails[j]=max(trails[j],lower)
                    state[j]=bool(price[t,j]>trails[j])
                if state[j]:expected[t,j]=min(.20,.02/statistics.pstdev(raw[t-19:t+1,j])/r.shape[1])
            if sum(expected[t])>2:expected[t]*=2/sum(expected[t])
        np.testing.assert_allclose(weights(r),expected,rtol=1e-10,atol=1e-11)


if __name__=='__main__':unittest.main()

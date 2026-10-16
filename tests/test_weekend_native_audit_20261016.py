import unittest
from research_dispatch_20261016.weekend_audit import decode


class NativeHourlyCacheTests(unittest.TestCase):
    def candle(self):
        return [0,'100','102','99','101','1',3599999,'100',1,'0.5','50','0']

    def test_native_prices_and_hour_close(self):
        row=decode(self.candle())
        self.assertEqual(str(row['High']),'102')
        self.assertEqual(row['ts'],0)

    def test_wrong_interval_or_alignment_rejected(self):
        for i,value in ((0,1),(6,299999)):
            row=self.candle();row[i]=value
            with self.assertRaises(ValueError):decode(row)

    def test_invalid_ohlc_or_nonfinite_rejected(self):
        for i,value in ((2,'98'),(3,'103'),(1,'NaN'),(4,'0')):
            row=self.candle();row[i]=value
            with self.assertRaises(ValueError):decode(row)


if __name__=='__main__':unittest.main()

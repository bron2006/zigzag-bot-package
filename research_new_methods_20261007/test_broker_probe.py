import unittest
from broker_feasibility import validate_request, m
from validate_broker_probe import decode_bar, inspect_history


class BrokerProbeTests(unittest.TestCase):
    def test_orders_rejected(self):
        for request in (m.ProtoOANewOrderReq(), m.ProtoOAClosePositionReq(), m.ProtoOAAmendOrderReq()):
            with self.assertRaises(ValueError):
                validate_request(request)

    def test_refresh_and_logout_rejected(self):
        for request in (m.ProtoOARefreshTokenReq(), m.ProtoOAAccountLogoutReq()):
            with self.assertRaises(ValueError):
                validate_request(request)

    def test_market_data_allowed(self):
        validate_request(m.ProtoOAGetTrendbarsReq())
        validate_request(m.ProtoOASymbolByIdReq())

    def test_fixed_protocol_price_scale(self):
        bar = dict(low='400000000', deltaOpen='100000', deltaHigh='200000', deltaClose='150000', utcTimestampInMinutes=1000)
        self.assertEqual(decode_bar(bar)['Close'], 4001.5)

    def test_impossible_high_rejected(self):
        with self.assertRaises(ValueError):
            decode_bar(dict(low=100, deltaOpen=50, deltaHigh=20, utcTimestampInMinutes=1000))

    def test_duplicate_timestamps_rejected(self):
        bar = dict(low=100000, deltaHigh=1, utcTimestampInMinutes=1000)
        with self.assertRaises(ValueError):
            inspect_history(dict(name='test', raw_trendbars=[bar, bar], specification={}))

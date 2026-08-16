import unittest

import config


class ClassifyInstrumentClassTest(unittest.TestCase):
    """AUDIT FIX (2026-08-15, high): entry-drift blocking used to apply one
    flat threshold to every instrument analysis.py scans - forex, crypto,
    commodities, stocks - despite wildly different typical volatility.
    These cover the classification these per-class thresholds are keyed
    on."""

    def test_crypto_pair_is_classified_as_crypto(self):
        self.assertEqual(config.classify_instrument_class("BTC/USD"), "crypto")

    def test_commodity_pair_is_classified_as_commodities(self):
        self.assertEqual(config.classify_instrument_class("XAU/USD"), "commodities")

    def test_stock_ticker_is_classified_as_stocks(self):
        self.assertEqual(config.classify_instrument_class("US30"), "stocks")

    def test_forex_pair_falls_back_to_forex(self):
        self.assertEqual(config.classify_instrument_class("AUD/JPY"), "forex")

    def test_unrecognized_pair_defaults_to_forex_not_an_error(self):
        # Forex is the deliberate catch-all/default - matches how
        # FOREX_SESSIONS already works as the catch-all currency-pair
        # source elsewhere in this codebase (e.g. scanner.py).
        self.assertEqual(config.classify_instrument_class("SOMETHING_UNKNOWN"), "forex")

    def test_classification_is_normalization_agnostic(self):
        # Slashes, case, whitespace shouldn't matter - normalize_symbol_key
        # already strips all of that.
        self.assertEqual(config.classify_instrument_class("btc/usd"), "crypto")
        self.assertEqual(config.classify_instrument_class("BTCUSD"), "crypto")


class EntryDriftPercentForPairTest(unittest.TestCase):
    def test_each_class_gets_its_own_configured_threshold(self):
        self.assertEqual(config.entry_drift_percent_for_pair("AUD/JPY"), config.MAX_ENTRY_DRIFT_PERCENT_FOREX)
        self.assertEqual(config.entry_drift_percent_for_pair("BTC/USD"), config.MAX_ENTRY_DRIFT_PERCENT_CRYPTO)
        self.assertEqual(config.entry_drift_percent_for_pair("XAU/USD"), config.MAX_ENTRY_DRIFT_PERCENT_COMMODITIES)
        self.assertEqual(config.entry_drift_percent_for_pair("US30"), config.MAX_ENTRY_DRIFT_PERCENT_STOCKS)

    def test_crypto_threshold_is_wider_than_forex(self):
        # The whole point of the fix: crypto's naturally larger short-term
        # moves must not get the same tight forex threshold.
        self.assertGreater(config.MAX_ENTRY_DRIFT_PERCENT_CRYPTO, config.MAX_ENTRY_DRIFT_PERCENT_FOREX)


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch

import alpha_opportunity_hunter as h

class AlphaOpportunityHunterTests(unittest.TestCase):
    def test_clamp(self):
        self.assertEqual(h.clamp(-1), 0)
        self.assertEqual(h.clamp(150), 100)
        self.assertEqual(h.clamp(55), 55)

    def test_discovery_filters_non_usdt_and_low_volume(self):
        payload = {"data": [
            {"symbol": "BTCUSDT", "lastPr": "100000", "quoteVolume": "9000000"},
            {"symbol": "ETHUSDT", "lastPr": "3000", "quoteVolume": "2000000"},
            {"symbol": "FOOUSDC", "lastPr": "1", "quoteVolume": "9000000"},
            {"symbol": "LOWUSDT", "lastPr": "1", "quoteVolume": "10"},
        ]}
        with patch.object(h, "get", return_value=payload):
            result = h.discover_symbols()
        self.assertEqual(result, ["BTCUSDT", "ETHUSDT"])

    def test_missing_price_is_rejected(self):
        payload = {"data": [{"symbol": "BTCUSDT", "lastPr": "0", "quoteVolume": "9000000"}]}
        with patch.object(h, "get", return_value=payload):
            self.assertEqual(h.discover_symbols(), [])

if __name__ == "__main__":
    unittest.main()

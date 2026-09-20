import unittest
from early_reversal_engine import evaluate_setup, infer_direction


def rows(prices, volume=100):
    return [[i * 900, str(p), str(p + 1), str(p - 1), str(p), str(volume)]
            for i, p in enumerate(prices)]


def rows_ohlc(prices, volume=100):
    return [[i * 300, str(o), str(h), str(l), str(c), str(volume)]
            for i, (o, h, l, c) in enumerate(prices)]


class EarlyReversalEngineTests(unittest.TestCase):
    def _long_fixture(self):
        prices15 = [110.0 - i * 0.45 for i in range(36)]
        prices15 += [94.2, 94.1, 94.25, 94.15]
        candles5 = [(94.2, 94.5, 93.9, 94.1)] * 20
        candles5[-1] = (94.0, 94.9, 93.5, 94.7)
        return rows(prices15), rows_ohlc(candles5)

    def _short_fixture(self):
        prices15 = [90.0 + i * 0.45 for i in range(36)]
        prices15 += [105.8, 105.9, 105.75, 105.85]
        candles5 = [(105.8, 106.1, 105.5, 105.9)] * 20
        candles5[-1] = (106.0, 106.5, 105.1, 105.3)
        return rows(prices15), rows_ohlc(candles5)

    def test_long_reversal(self):
        rows15, rows5 = self._long_fixture()
        setup = evaluate_setup(rows15, rows5, "LONG")
        self.assertTrue(setup["eligible"], setup)
        self.assertEqual(setup["location_15m"], 1.0)
        self.assertGreaterEqual(setup["exhaustion_15m"], 0.5)
        self.assertGreaterEqual(setup["reversal_trigger_5m"], 0.75)
        self.assertEqual(infer_direction(rows15, rows5), "LONG")

    def test_short_reversal(self):
        rows15, rows5 = self._short_fixture()
        setup = evaluate_setup(rows15, rows5, "SHORT")
        self.assertTrue(setup["eligible"], setup)
        self.assertEqual(setup["location_15m"], 1.0)
        self.assertGreaterEqual(setup["exhaustion_15m"], 0.5)
        self.assertGreaterEqual(setup["reversal_trigger_5m"], 0.75)
        self.assertEqual(infer_direction(rows15, rows5), "SHORT")

    def test_extended_move_without_reversal_trigger_is_rejected(self):
        rows15 = rows([100.0 - i * 0.45 for i in range(40)])
        rows5 = rows_ohlc([(82.0, 82.4, 81.6, 82.0)] * 20)
        setup = evaluate_setup(rows15, rows5, "LONG")
        self.assertFalse(setup["eligible"])
        self.assertIn("reversal", setup["reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

import unittest
from early_reversal_engine import evaluate_setup, infer_direction


def rows(prices, volume=100):
    return [[i * 900, str(p), str(p + 1), str(p - 1), str(p), str(volume)]
            for i, p in enumerate(prices)]


def rows_ohlc(prices, volume=100):
    return [[i * 300, str(o), str(h), str(l), str(c), str(volume)]
            for i, (o, h, l, c) in enumerate(prices)]


class EarlyReversalTests(unittest.TestCase):
    def _long_fixture(self):
        # 15m: sustained decline into the lower range, then a tight base.
        prices15 = [110.0 - i * 0.45 for i in range(36)]
        prices15 += [94.2, 94.1, 94.25, 94.15]
        # 5m: liquidity sweep and close back above the prior low.
        candles5 = [(94.2, 94.5, 93.9, 94.1)] * 19
        candles5[-1] = (94.0, 94.9, 93.5, 94.7)
        return rows(prices15), rows_ohlc(candles5)

    def _short_fixture(self):
        prices15 = [90.0 + i * 0.45 for i in range(36)]
        prices15 += [105.8, 105.9, 105.75, 105.85]
        candles5 = [(105.8, 106.1, 105.5, 105.9)] * 19
        candles5[-1] = (106.0, 106.5, 105.1, 105.3)
        return rows(prices15), rows_ohlc(candles5)

    def test_long_early_reversal_fixture_is_eligible(self):
        setup = evaluate_setup(*self._long_fixture(), "LONG")
        self.assertTrue(setup["eligible"])
        self.assertEqual(setup["location_15m"], 1.0)
        self.assertGreaterEqual(setup["exhaustion_15m"], 0.5)
        self.assertGreaterEqual(setup["reversal_trigger_5m"], 0.75)
        self.assertEqual(infer_direction(*self._long_fixture()), "LONG")

    def test_short_early_reversal_fixture_is_eligible(self):
        setup = evaluate_setup(*self._short_fixture(), "SHORT")
        self.assertTrue(setup["eligible"])
        self.assertEqual(setup["location_15m"], 1.0)
        self.assertGreaterEqual(setup["exhaustion_15m"], 0.5)
        self.assertGreaterEqual(setup["reversal_trigger_5m"], 0.75)
        self.assertEqual(infer_direction(*self._short_fixture()), "SHORT")

    def test_no_reversal_does_not_trigger(self):
        prices15 = [100 + i * 0.5 for i in range(40)]
        candles5 = [(115, 116, 114, 115)] * 20
        setup = evaluate_setup(rows(prices15), rows_ohlc(candles5), "LONG")
        self.assertFalse(setup["eligible"])
        self.assertIn("reversal zone", setup["reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

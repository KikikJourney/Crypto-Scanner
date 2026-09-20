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
        prices15 = [110.0 - i * 0.45 for i in range(28)]
        prices15 += [97.2, 97.1, 97.25, 97.15]
        # 5m: liquidity sweep and close back above the prior low.
        candles5 = [(97.2, 97.5, 96.9, 97.1)] * 19
        candles5[-1] = (97.0, 97.9, 96.5, 97.7)
        return rows(prices15), rows_ohlc(candles5)

    def _short_fixture(self):
        prices15 = [90.0 + i * 0.45 for i in range(28)]
        prices15 += [102.8, 102.9, 102.75, 102.85]
        candles5 = [(102.8, 103.1, 102.5, 102.9)] * 19
        candles5[-1] = (103.0, 103.5, 102.1, 102.3)
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

import unittest

from alpha_hunter import build_plan


def candle(ts, price, volume=100.0, span=0.2):
    return [ts, price - 0.05, price + span, price - span, price, volume]


class AlphaHunterTests(unittest.TestCase):
    def test_long_opportunity_in_volatile_low_range(self):
        rows15 = []
        for i in range(160):
            p = 110.0 - i * 0.08
            rows15.append(candle(i * 900000, p, 1000.0, 0.18))
        # Keep the final 15m location low but recovering.
        rows15[-1] = candle(159 * 900000, 97.5, 1800.0, 0.30)

        rows5 = []
        for i in range(75):
            p = 98.0 + max(0, i - 68) * 0.18
            rows5.append(candle(i * 300000, p, 100.0, 0.40))
        rows5[-5] = candle(70 * 300000, 98.0, 100.0, 0.45)
        rows5[-4] = candle(71 * 300000, 98.2, 100.0, 0.45)
        rows5[-3] = candle(72 * 300000, 98.4, 100.0, 0.45)
        rows5[-2] = candle(73 * 300000, 98.6, 100.0, 0.45)
        rows5[-1] = candle(74 * 300000, 99.0, 110.0, 0.50)

        plan = build_plan(rows15, rows5)
        self.assertIn(plan["status"], {"ALPHA LONG", "ALPHA SHORT"})
        self.assertEqual(plan["direction"], "LONG")
        self.assertGreaterEqual(plan["reward_r"], 2.0)
        self.assertLessEqual(plan["reward_r"], 6.0)
        self.assertLessEqual(plan["entry_distance_atr"], 1.5)

    def test_dead_market_is_rejected(self):
        rows15 = [candle(i * 900000, 100.0, 1000.0, 0.02) for i in range(160)]
        rows5 = [candle(i * 300000, 100.0, 100.0, 0.01) for i in range(75)]
        plan = build_plan(rows15, rows5)
        self.assertEqual(plan["status"], "WAIT")
        self.assertIn("volatility", plan["reason"])


if __name__ == "__main__":
    unittest.main()

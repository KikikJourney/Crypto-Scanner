import unittest

from tp_geometry import calibrate_tp, MIN_TARGET_R, MAX_TARGET_R


def candle(i, close, low, high, volume=100.0):
    return [i, 0.0, high, low, close, volume]


class TpGeometryTests(unittest.TestCase):
    def test_long_target_is_concrete_and_within_2_to_8_r(self):
        rows15 = [candle(i, 100 + i * 0.02, 99 + i * 0.02, 101 + i * 0.02) for i in range(80)]
        rows5 = [candle(i, 100 + i * 0.01, 99.5 + i * 0.01, 100.5 + i * 0.01) for i in range(80)]
        result = calibrate_tp(
            rows15, rows5, "LONG", 100.0, 99.5,
            {"order_flow_score": 0.9, "whale_score": 0.8, "flow_conviction": 0.9}
        )
        self.assertIsNotNone(result)
        self.assertGreaterEqual(result["reward_r"], MIN_TARGET_R)
        self.assertLessEqual(result["reward_r"], MAX_TARGET_R)
        self.assertGreater(result["target"], 100.0)
        self.assertIn(result["target_source"], {"15m_pivot", "15m_range_boundary", "5m_pivot", "5m_range_projection"})

    def test_short_target_is_below_entry(self):
        rows15 = [candle(i, 100 - i * 0.02, 99 - i * 0.02, 101 - i * 0.02) for i in range(80)]
        rows5 = [candle(i, 100 - i * 0.01, 99.5 - i * 0.01, 100.5 - i * 0.01) for i in range(80)]
        result = calibrate_tp(
            rows15, rows5, "SHORT", 100.0, 100.5,
            {"order_flow_score": 0.8, "flow_conviction": 0.8}
        )
        self.assertIsNotNone(result)
        self.assertLess(result["target"], 100.0)
        self.assertGreaterEqual(result["reward_r"], MIN_TARGET_R)
        self.assertLessEqual(result["reward_r"], MAX_TARGET_R)

    def test_no_tp_when_no_supported_price_geometry(self):
        rows = [candle(i, 100.0, 99.99, 100.01) for i in range(20)]
        self.assertIsNone(calibrate_tp(rows, rows, "LONG", 100.0, 99.5, {}))


if __name__ == "__main__":
    unittest.main(verbosity=2)

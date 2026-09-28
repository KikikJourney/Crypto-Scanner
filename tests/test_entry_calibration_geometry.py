import unittest

from entry_calibration import calibrate_entry
from entry_geometry import build_entry_geometry


def rows_ohlc(prices):
    return [[i * 300, str(o), str(h), str(l), str(c), "100"]
            for i, (o, h, l, c) in enumerate(prices)]


class EntryCalibrationGeometryTests(unittest.TestCase):
    def test_calibration_uses_100_closed_candle_extreme_without_stop_or_tp(self):
        rows = rows_ohlc([(100, 101, 99, 100)] * 99 + [(100, 102, 95, 101)])
        result = calibrate_entry(rows, "LONG", 1.0)
        self.assertEqual(result["anchor"], 95.0)
        self.assertGreater(result["entry"], 95.0)
        self.assertNotIn("stop", result)
        self.assertNotIn("target", result)
        self.assertEqual(result["lookback_candles"], 100)

    def test_short_calibration_uses_highest_100_candle_extreme(self):
        rows = rows_ohlc([(100, 101, 99, 100)] * 99 + [(100, 105, 98, 104)])
        result = calibrate_entry(rows, "SHORT", 1.0)
        self.assertEqual(result["anchor"], 105.0)
        self.assertLess(result["entry"], 105.0)
        self.assertNotIn("stop", result)
        self.assertNotIn("target", result)

    def test_geometry_is_derived_from_final_entry(self):
        plan = build_entry_geometry("LONG", 100.0)
        self.assertAlmostEqual(plan["entry"], 100.0)
        self.assertAlmostEqual(plan["stop"], 99.5, places=8)
        self.assertAlmostEqual(plan["tp1"], 101.5, places=8)
        self.assertAlmostEqual(plan["tp2"], 103.0, places=8)
        self.assertAlmostEqual(plan["tp3"], 106.0, places=8)
        self.assertEqual(plan["tp1_margin_pct"], 30.0)
        self.assertEqual(plan["tp2_margin_pct"], 60.0)
        self.assertEqual(plan["tp3_margin_pct"], 120.0)

    def test_structural_stop_is_only_accepted_inside_risk_cap(self):
        plan = build_entry_geometry("LONG", 100.0, structural_stop=99.9)
        self.assertAlmostEqual(plan["stop"], 99.5)
        self.assertAlmostEqual(plan["structural_stop"], 99.9)
        self.assertEqual(plan["stop_margin_pct"], 10.0)

    def test_structural_stop_outside_risk_cap_falls_back_to_margin_geometry(self):
        plan = build_entry_geometry("LONG", 100.0, structural_stop=95.0)
        self.assertAlmostEqual(plan["stop"], 99.5, places=8)
        self.assertEqual(plan["stop_margin_pct"], 10.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

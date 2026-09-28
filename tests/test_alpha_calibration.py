import unittest

from alpha_calibration import calibrate_alpha


class AlphaCalibrationTests(unittest.TestCase):
    def test_long_bottom_profile_rewards_contrarian_derivatives(self):
        result = calibrate_alpha("LONG", {
            "trend_score": 0.65,
            "order_flow_score": 0.75,
            "oi_change_pct": -1.2,
            "price_change_pct": -1.0,
            "funding_rate": -0.001,
            "long_short_ratio": 0.65,
            "atr_pct": 1.1,
            "range_position": 0.08,
            "structure_score": 0.70,
            "liquidity_sweep_score": 0.90,
            "volume_ratio": 1.8,
            "entry_timing_score": 0.92,
        })
        self.assertGreater(result["quality_score"], 60.0)
        self.assertGreater(result["timing_score"], 70.0)
        self.assertEqual(result["calibration_status"], "FULL")

    def test_short_top_profile_rewards_contrarian_derivatives(self):
        result = calibrate_alpha("SHORT", {
            "trend_score": 0.70,
            "order_flow_score": 0.25,
            "oi_change_pct": -1.0,
            "price_change_pct": 1.2,
            "funding_rate": 0.001,
            "long_short_ratio": 1.45,
            "atr_pct": 1.0,
            "range_position": 0.92,
            "structure_score": 0.75,
            "liquidity_sweep_score": 0.90,
            "volume_ratio": 1.7,
            "entry_timing_score": 0.94,
        })
        self.assertGreater(result["quality_score"], 60.0)
        self.assertGreater(result["timing_score"], 70.0)

    def test_missing_derivatives_are_reported_not_zeroed(self):
        result = calibrate_alpha("LONG", {
            "location_score": 0.9,
            "entry_timing_score": 0.9,
            "liquidity_sweep_score": 0.8,
            "volume_ratio": 1.5,
            "atr_pct": 1.0,
            "trend_score": 0.7,
        })
        self.assertEqual(result["calibration_status"], "PARTIAL")
        self.assertLess(result["data_completeness"], 1.0)
        self.assertIsNone(result["components"]["open_interest"])


if __name__ == "__main__":
    unittest.main()

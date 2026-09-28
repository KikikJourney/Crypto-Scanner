import unittest
from unittest.mock import patch

import alpha_hunter
from alpha_hunter import build_plan, build_discovery_plan


def candle(ts, price, volume=100.0, span=0.2):
    return [ts, price - 0.05, price + span, price - span, price, volume]


class AlphaHunterTests(unittest.TestCase):
    def test_opportunity_in_volatile_low_range(self):
        rows15 = []
        for i in range(160):
            p = 110.0 - i * 0.08
            rows15.append(candle(i * 900000, p, 1000.0, 0.18))
        # Keep the final 15m location low but recovering.
        rows15[-1] = candle(159 * 900000, 97.5, 1800.0, 0.30)

        rows5 = []
        for i in range(100):
            p = 98.0 + max(0, i - 95) * 0.18
            rows5.append(candle(i * 300000, p, 100.0, 0.40))
        rows5[-5] = candle(95 * 300000, 98.0, 100.0, 0.45)
        rows5[-4] = candle(96 * 300000, 98.2, 100.0, 0.45)
        rows5[-3] = candle(97 * 300000, 98.4, 100.0, 0.45)
        rows5[-2] = candle(98 * 300000, 98.6, 100.0, 0.45)
        rows5[-1] = candle(99 * 300000, 99.0, 110.0, 0.02)

        calibrated = {"anchor": 98.6, "buffer": 0.2, "entry": 98.8, "current_price": 99.0, "distance_atr": 0.25}
        with patch.object(alpha_hunter, "calibrate_entry", return_value=calibrated):
            plan = build_plan(rows15, rows5)
        self.assertIn(plan["status"], {"ALPHA LONG", "ALPHA SHORT"})
        self.assertIn(plan["direction"], {"LONG", "SHORT"})
        self.assertGreaterEqual(plan["reward_r"], 3.0)
        self.assertLessEqual(plan["reward_r"], 8.0)
        self.assertLessEqual(plan["entry_distance_atr"], 0.9)

    def test_geometry_repair_keeps_opportunity_alive(self):
        rows15 = []
        for i in range(160):
            p = 110.0 - i * 0.08
            rows15.append(candle(i * 900000, p, 1000.0, 0.18))
        rows15[-1] = candle(159 * 900000, 97.5, 1800.0, 0.30)

        rows5 = []
        for i in range(100):
            p = 98.0 + max(0, i - 68) * 0.18
            rows5.append(candle(i * 300000, p, 100.0, 0.40))
        rows5[-1] = candle(99 * 300000, 99.0, 110.0, 0.02)

        calibrated = {"anchor": 98.6, "buffer": 0.2, "entry": 98.8, "current_price": 99.0, "distance_atr": 0.25}
        with patch.object(alpha_hunter, "calibrate_entry", return_value=calibrated):
            with patch.object(alpha_hunter, "_select_tp_margin_pct", return_value=None):
                plan = build_plan(rows15, rows5)

        self.assertIn(plan["status"], {"ALPHA LONG", "ALPHA SHORT"})
        self.assertIn("geometry_repaired_to_canonical_tp", plan["reason"])

    def test_discovery_keeps_far_entry_as_watch(self):
        rows15 = []
        for i in range(160):
            p = 110.0 - i * 0.08
            rows15.append(candle(i * 900000, p, 1000.0, 0.18))
        rows15[-1] = candle(159 * 900000, 97.5, 1800.0, 0.30)

        rows5 = []
        for i in range(100):
            p = 98.0 + max(0, i - 68) * 0.18
            rows5.append(candle(i * 300000, p, 100.0, 0.40))
        rows5[-1] = candle(99 * 300000, 99.0, 110.0, 0.02)

        far_calibration = {
            "anchor": 90.0, "buffer": 0.25, "entry": 90.25,
            "current_price": 99.0, "distance_atr": 10.0,
        }
        with patch.object(alpha_hunter, "calibrate_entry", return_value=far_calibration):
            plan = build_discovery_plan(rows15, rows5)

        self.assertIn(plan["status"], {"ALPHA WATCH LONG", "ALPHA WATCH SHORT"})
        self.assertFalse(plan["execution_ready"])
        self.assertGreater(plan["entry_distance_atr"], 0.9)
        self.assertIn("execution zone", plan["watch_reason"])

    def test_alpha_passes_mtf_and_flow_context_to_timing_calibration(self):
        rows15 = [candle(i * 900000, 110.0 - i * 0.05, 1000.0, 0.30) for i in range(160)]
        rows15[-1] = candle(159 * 900000, 97.5, 1800.0, 0.30)
        rows5 = [candle(i * 300000, 98.0 + max(0, i - 68) * 0.18, 100.0, 0.40) for i in range(100)]
        rows5[-1] = candle(99 * 300000, 99.0, 110.0, 0.02)
        calibrated = {
            "anchor": 98.6, "buffer": 0.2, "entry": 98.8,
            "current_price": 99.0, "distance_atr": 0.25,
            "timing_score": 0.8, "volume_ratio_5m": 1.4,
            "volume_regime": "expansion", "flow_score": 0.9,
            "sweep_score": 1.0, "regime_score_15m": 0.8,
            "calibration_inputs": "100x5m + 15m regime/location + volume regime + order-flow/liquidity",
        }
        context = {"order_flow_score": 0.9, "whale_score": 0.8, "liquidation_score": 0.7, "flow_conviction": 0.85}
        with patch.object(alpha_hunter, "calibrate_entry", return_value=calibrated) as mocked:
            plan = build_plan(rows15, rows5, context=context)
        self.assertIn(plan["status"], {"ALPHA LONG", "ALPHA SHORT"})
        kwargs = mocked.call_args.kwargs
        self.assertIs(kwargs["rows_15m"], rows15)
        self.assertEqual(kwargs["context"], context)
        self.assertEqual(plan["timing_score"], 0.8)
        self.assertEqual(plan["flow_score"], 0.9)
        self.assertIn("100x5m", plan["calibration_inputs"])


    def test_directional_timing_zone_matches_execution_side(self):
        long_inside = alpha_hunter._entry_timing_state(100.10, 100.0, 1.0, "LONG")
        long_below = alpha_hunter._entry_timing_state(99.90, 100.0, 1.0, "LONG")
        short_inside = alpha_hunter._entry_timing_state(99.90, 100.0, 1.0, "SHORT")
        short_above = alpha_hunter._entry_timing_state(100.10, 100.0, 1.0, "SHORT")
        self.assertTrue(long_inside["execution_ready"])
        self.assertFalse(long_below["execution_ready"])
        self.assertTrue(short_inside["execution_ready"])
        self.assertFalse(short_above["execution_ready"])

    def test_timing_state_is_independent_of_geometry(self):
        near = alpha_hunter._entry_timing_state(100.0, 99.8, 1.0)
        far = alpha_hunter._entry_timing_state(100.0, 95.0, 1.0)
        self.assertTrue(near["execution_ready"])
        self.assertFalse(far["execution_ready"])
        self.assertAlmostEqual(near["distance_atr"], 0.2)
        self.assertAlmostEqual(far["distance_atr"], 5.0)

    def test_final_target_is_capped_at_8r(self):
        rows15 = []
        for i in range(160):
            p = 110.0 - i * 0.08
            rows15.append(candle(i * 900000, p, 1000.0, 0.18))
        rows15[-1] = candle(159 * 900000, 97.5, 1800.0, 0.30)

        rows5 = []
        for i in range(100):
            p = 98.0 + max(0, i - 68) * 0.18
            rows5.append(candle(i * 300000, p, 100.0, 0.40))
        rows5[-1] = candle(99 * 300000, 99.0, 110.0, 0.02)

        oversized = (200.0, 200.0, 200.0, 200.0)
        calibrated = {"anchor": 98.6, "buffer": 0.2, "entry": 98.8, "current_price": 99.0, "distance_atr": 0.25}
        with patch.object(alpha_hunter, "calibrate_entry", return_value=calibrated):
            with patch.object(
                alpha_hunter,
                "_select_tp_margin_pct",
                return_value=(120.0, 1.0, 100.0),
            ), patch.object(
                alpha_hunter,
                "_opposing_structure_target",
                return_value=oversized[0],
            ):
                plan = build_plan(rows15, rows5)

        self.assertIn(plan["status"], {"ALPHA LONG", "ALPHA SHORT"})
        self.assertLessEqual(plan["reward_r"], 8.0)

    def test_dead_market_is_rejected(self):
        rows15 = [candle(i * 900000, 100.0, 1000.0, 0.02) for i in range(160)]
        rows5 = [candle(i * 300000, 100.0, 100.0, 0.01) for i in range(100)]
        plan = build_plan(rows15, rows5)
        self.assertEqual(plan["status"], "WAIT")
        self.assertIn("volatility", plan["reason"])


if __name__ == "__main__":
    unittest.main()
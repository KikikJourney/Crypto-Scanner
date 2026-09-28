import unittest

from entry_calibration import calibrate_entry
from entry_geometry import build_entry_geometry
from margin_risk_model import (
    DEFAULT_LEVERAGE,
    DEFAULT_MARGIN_USDT,
    MAX_MARGIN_LOSS_PCT,
    TP1_MARGIN_PCT,
    TP2_MARGIN_PCT,
    TP3_MARGIN_PCT,
)


def candle(i, close=11.0, low=10.8, high=11.2, volume=100.0):
    return [i, close, high, low, close, volume]


class EntryCalibrationGeometryContractTests(unittest.TestCase):
    def test_canonical_geometry_contract_long(self):
        plan = build_entry_geometry("LONG", 100.0)
        self.assertEqual(DEFAULT_MARGIN_USDT, 10.0)
        self.assertEqual(DEFAULT_LEVERAGE, 20.0)
        self.assertEqual(MAX_MARGIN_LOSS_PCT, 10.0)
        self.assertEqual(plan["margin_usdt"], 10.0)
        self.assertEqual(plan["leverage"], 20.0)
        self.assertAlmostEqual(plan["stop"], 99.5, places=8)
        self.assertAlmostEqual(plan["tp1"], 101.5, places=8)
        self.assertAlmostEqual(plan["tp2"], 103.0, places=8)
        self.assertAlmostEqual(plan["tp3"], 106.0, places=8)
        self.assertEqual(plan["tp1_margin_pct"], TP1_MARGIN_PCT)
        self.assertEqual(plan["tp2_margin_pct"], TP2_MARGIN_PCT)
        self.assertEqual(plan["tp3_margin_pct"], TP3_MARGIN_PCT)

    def test_canonical_geometry_contract_short(self):
        plan = build_entry_geometry("SHORT", 100.0, selected_tp_margin_pct=120.0)
        self.assertAlmostEqual(plan["stop"], 100.5, places=8)
        self.assertAlmostEqual(plan["tp1"], 98.5, places=8)
        self.assertAlmostEqual(plan["tp2"], 97.0, places=8)
        self.assertAlmostEqual(plan["tp3"], 94.0, places=8)
        self.assertAlmostEqual(plan["target"], plan["tp3"], places=8)

    def test_structural_stop_cannot_override_canonical_sl(self):
        plan = build_entry_geometry("LONG", 100.0, structural_stop=99.9)
        self.assertAlmostEqual(plan["stop"], 99.5, places=8)
        self.assertAlmostEqual(plan["structural_stop"], 99.9, places=8)

    def test_timing_calibration_uses_40_candle_anchor_and_context(self):
        rows_5m = [candle(i) for i in range(100)]
        rows_5m[40] = candle(40, close=10.5, low=10.0, high=10.7, volume=180.0)
        rows_15m = [candle(i, close=10.8, low=10.0, high=11.5) for i in range(32)]
        result = calibrate_entry(
            rows_5m,
            "LONG",
            1.0,
            rows_15m=rows_15m,
            context={
                "order_flow_score": 0.8,
                "whale_score": 0.7,
                "liquidation_score": 0.6,
                "flow_conviction": 0.9,
            },
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["lookback_candles"], 100)
        self.assertEqual(result["anchor_source"], "40c_timing")
        self.assertEqual(result["anchor_window"], 40)
        self.assertAlmostEqual(result["anchor"], 10.0, places=8)
        self.assertIn("timing_score", result)
        self.assertIn("volume_regime", result)
        self.assertIn("flow_score", result)
        self.assertIn("regime_score_15m", result)
        self.assertIn("calibration_inputs", result)

    def test_40_candle_timing_anchor_replaces_unreachable_100_anchor(self):
        rows_5m = [candle(i, close=100.0, low=99.8, high=100.2) for i in range(100)]
        # Old 100-candle extreme is deliberately far away.
        rows_5m[10] = candle(10, close=90.0, low=89.0, high=90.5, volume=150.0)
        # Recent 40-candle extreme is close enough to be executable.
        rows_5m[-1] = candle(99, close=100.0, low=99.8, high=100.2, volume=160.0)
        result = calibrate_entry(rows_5m, "LONG", 1.0)
        self.assertEqual(result["anchor_source"], "40c_timing")
        self.assertEqual(result["anchor_window"], 40)
        self.assertAlmostEqual(result["anchor_100"], 89.0, places=8)
        self.assertAlmostEqual(result["anchor_40"], 99.8, places=8)
        self.assertAlmostEqual(result["anchor"], 99.8, places=8)
        self.assertLess(result["distance_atr"], 1.0)

    def test_geometry_is_independent_of_calibration_entry_location(self):
        a = build_entry_geometry("LONG", 100.0)
        b = build_entry_geometry("LONG", 110.0)
        self.assertAlmostEqual(a["stop"] / a["entry"], b["stop"] / b["entry"], places=8)
        self.assertAlmostEqual(a["tp1"] / a["entry"], b["tp1"] / b["entry"], places=8)


if __name__ == "__main__":
    unittest.main()

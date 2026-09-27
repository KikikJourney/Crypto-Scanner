import unittest

from margin_risk_model import (
    DEFAULT_LEVERAGE,
    DEFAULT_MARGIN_USDT,
    MAX_MARGIN_LOSS_PCT,
    MIN_MARGIN_TP_PCT,
    MAX_MARGIN_TP_PCT,
    TP1_MARGIN_PCT, TP2_MARGIN_PCT, TP3_MARGIN_PCT,
    build_margin_plan,
    target_margin_pct_from_price,
    stop_margin_pct_from_price,
)


class MarginRiskModelTests(unittest.TestCase):
    def test_default_long_plan_10_margin_25x(self):
        plan = build_margin_plan("LONG", 100.0)
        self.assertEqual(plan["margin_usdt"], 10.0)
        self.assertEqual(plan["leverage"], 25.0)
        self.assertEqual(plan["notional_usdt"], 250.0)
        self.assertEqual(plan["stop_margin_pct"], 5.0)
        self.assertEqual(plan["tp_margin_pct"], 30.0)
        self.assertAlmostEqual(plan["stop"], 99.8, places=8)
        self.assertAlmostEqual(plan["target"], 101.2, places=8)
        self.assertAlmostEqual(plan["tp1"], 101.2, places=8)
        self.assertAlmostEqual(plan["tp2"], 102.4, places=8)
        self.assertAlmostEqual(plan["tp3"], 104.8, places=8)
        self.assertAlmostEqual(plan["max_loss_usdt"], 0.5, places=8)
        self.assertAlmostEqual(plan["target_pnl_usdt"], 3.0, places=8)
        self.assertEqual(plan["tp1_margin_pct"], 30.0)
        self.assertEqual(plan["tp2_margin_pct"], 60.0)
        self.assertEqual(plan["tp3_margin_pct"], 120.0)

    def test_120_percent_margin_tp_is_4_8_percent_price_move_at_25x(self):
        plan = build_margin_plan("LONG", 100.0, 10.0, 25.0, 5.0, 120.0)
        self.assertAlmostEqual(plan["target"], 104.8, places=8)
        self.assertAlmostEqual(plan["target_price_move_pct"], 4.8, places=8)
        self.assertAlmostEqual(plan["target_pnl_usdt"], 12.0, places=8)
        self.assertAlmostEqual(plan["reward_to_r"], 24.0, places=8)

    def test_short_plan_mirrors_long(self):
        plan = build_margin_plan("SHORT", 100.0, 10.0, 25.0, 5.0, 30.0)
        self.assertAlmostEqual(plan["stop"], 100.2, places=8)
        self.assertAlmostEqual(plan["target"], 98.8, places=8)

    def test_stop_and_target_percentages_are_margin_based(self):
        self.assertAlmostEqual(stop_margin_pct_from_price(100, 99.8, "LONG", 25), 5.0)
        self.assertAlmostEqual(target_margin_pct_from_price(100, 101.2, "LONG", 25), 30.0)
        self.assertAlmostEqual(stop_margin_pct_from_price(100, 100.2, "SHORT", 25), 5.0)
        self.assertAlmostEqual(target_margin_pct_from_price(100, 98.8, "SHORT", 25), 30.0)

    def test_tp_band_is_enforced(self):
        with self.assertRaises(ValueError):
            build_margin_plan("LONG", 100, 10, 25, 5, 29)
        with self.assertRaises(ValueError):
            build_margin_plan("LONG", 100, 10, 25, 5, 121)

    def test_stop_cap_is_enforced(self):
        with self.assertRaises(ValueError):
            build_margin_plan("LONG", 100, 10, 25, 5.01, 30)


if __name__ == "__main__":
    unittest.main(verbosity=2)

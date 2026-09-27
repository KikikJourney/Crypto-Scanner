import unittest

from margin_risk_model import (
    DEFAULT_LEVERAGE,
    DEFAULT_MARGIN_USDT,
    MAX_MARGIN_LOSS_PCT,
    MIN_MARGIN_TP_PCT,
    MAX_MARGIN_TP_PCT,
    build_margin_plan,
    target_margin_pct_from_price,
    stop_margin_pct_from_price,
)


class MarginRiskModelTests(unittest.TestCase):
    def test_default_long_plan_10_margin_10x(self):
        plan = build_margin_plan("LONG", 100.0)
        self.assertEqual(plan["margin_usdt"], 10.0)
        self.assertEqual(plan["leverage"], 10.0)
        self.assertEqual(plan["notional_usdt"], 100.0)
        self.assertEqual(plan["stop_margin_pct"], 5.0)
        self.assertEqual(plan["tp_margin_pct"], 40.0)
        self.assertAlmostEqual(plan["stop"], 99.5, places=8)
        self.assertAlmostEqual(plan["target"], 104.0, places=8)
        self.assertAlmostEqual(plan["max_loss_usdt"], 0.5, places=8)
        self.assertAlmostEqual(plan["target_pnl_usdt"], 4.0, places=8)

    def test_100_percent_margin_tp_is_10_percent_price_move_at_10x(self):
        plan = build_margin_plan("LONG", 100.0, 10.0, 10.0, 5.0, 100.0)
        self.assertAlmostEqual(plan["target"], 110.0, places=8)
        self.assertAlmostEqual(plan["target_price_move_pct"], 10.0, places=8)
        self.assertAlmostEqual(plan["target_pnl_usdt"], 10.0, places=8)
        self.assertAlmostEqual(plan["reward_to_r"], 20.0, places=8)

    def test_short_plan_mirrors_long(self):
        plan = build_margin_plan("SHORT", 100.0, 10.0, 10.0, 5.0, 40.0)
        self.assertAlmostEqual(plan["stop"], 100.5, places=8)
        self.assertAlmostEqual(plan["target"], 96.0, places=8)

    def test_stop_and_target_percentages_are_margin_based(self):
        self.assertAlmostEqual(stop_margin_pct_from_price(100, 99.5, "LONG", 10), 5.0)
        self.assertAlmostEqual(target_margin_pct_from_price(100, 104, "LONG", 10), 40.0)
        self.assertAlmostEqual(stop_margin_pct_from_price(100, 100.5, "SHORT", 10), 5.0)
        self.assertAlmostEqual(target_margin_pct_from_price(100, 96, "SHORT", 10), 40.0)

    def test_tp_band_is_enforced(self):
        with self.assertRaises(ValueError):
            build_margin_plan("LONG", 100, 10, 10, 5, 39)
        with self.assertRaises(ValueError):
            build_margin_plan("LONG", 100, 10, 10, 5, 101)

    def test_stop_cap_is_enforced(self):
        with self.assertRaises(ValueError):
            build_margin_plan("LONG", 100, 10, 10, 5.01, 40)


if __name__ == "__main__":
    unittest.main(verbosity=2)

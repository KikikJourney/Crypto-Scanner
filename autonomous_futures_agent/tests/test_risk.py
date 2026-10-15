import unittest

from autonomous_futures_agent.models import Side, TradingConfig
from autonomous_futures_agent.risk import build_trade_plan


class TradePlanTests(unittest.TestCase):
    def test_long_plan_uses_five_usdt_margin_and_twenty_x_leverage(self):
        plan = build_trade_plan(Side.LONG, 100.0, TradingConfig())
        self.assertAlmostEqual(plan.notional_usdt, 100.0)
        self.assertAlmostEqual(plan.quantity, 1.0)
        self.assertAlmostEqual(plan.stop_loss_price, 99.5)
        self.assertAlmostEqual(plan.take_profit_prices[0], 101.5)
        self.assertAlmostEqual(plan.take_profit_prices[1], 103.0)
        self.assertAlmostEqual(plan.take_profit_prices[2], 106.0)

    def test_short_plan_reverses_price_geometry(self):
        plan = build_trade_plan(Side.SHORT, 100.0, TradingConfig())
        self.assertAlmostEqual(plan.stop_loss_price, 100.5)
        self.assertAlmostEqual(plan.take_profit_prices[0], 98.5)
        self.assertAlmostEqual(plan.take_profit_prices[1], 97.0)
        self.assertAlmostEqual(plan.take_profit_prices[2], 94.0)

    def test_rejects_invalid_entry_price(self):
        with self.assertRaises(ValueError):
            build_trade_plan(Side.LONG, 0.0, TradingConfig())

    def test_rejects_non_isolated_margin(self):
        with self.assertRaises(ValueError):
            TradingConfig(margin_mode="cross")


if __name__ == "__main__":
    unittest.main()

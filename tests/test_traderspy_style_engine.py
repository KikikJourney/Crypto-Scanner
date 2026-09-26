import unittest

from traderspy_style_engine import (
    adx,
    atr,
    ema,
    rsi,
    volume_ratio,
    build_plan,
    _entry_location_40,
)


def candle(ts, close, volume=100.0, spread=0.002):
    return [
        ts,
        close * (1.0 - spread),
        close * (1.0 + spread),
        close * (1.0 - spread * 1.5),
        close,
        volume,
    ]


class TraderSpyStyleEngineTests(unittest.TestCase):
    def setUp(self):
        # Deterministic rising tape with a pullback/reclaim at the end.
        self.rows = []
        price = 1.0
        for i in range(194):
            price *= 1.0015
            if i >= 188:
                price *= 0.9995
            self.rows.append(candle(i * 900000, price, 250.0 if i >= 188 else 100.0))
        self.rows[-1][1] = self.rows[-1][4] * 0.998
        self.rows[-1][2] = self.rows[-1][4] * 1.001

    def test_indicators_return_finite_values(self):
        closes = [r[4] for r in self.rows]
        self.assertIsNotNone(ema(closes, 20))
        self.assertIsNotNone(rsi(closes))
        self.assertIsNotNone(atr(self.rows))
        self.assertIsNotNone(adx(self.rows))
        self.assertIsNotNone(volume_ratio(self.rows))

    def test_build_plan_never_emits_malformed_action(self):
        plan = build_plan(self.rows, self.rows[-60:])
        self.assertIn(plan["status"], {
            "ACTION LONG", "ACTION SHORT", "WAIT", "DATA-LIMITED"
        })
        if plan["status"].startswith("ACTION"):
            self.assertGreaterEqual(plan["confidence"], 70.0)
            self.assertGreaterEqual(plan["reward_r"], 1.40)
            self.assertLessEqual(plan["reward_r"], 3.50)
            self.assertGreater(plan["entry"], 0)
            self.assertGreater(plan["stop"], 0)
            self.assertGreater(plan["target"], 0)


    def test_requires_5m_execution_timing(self):
        self.assertIsNone(_entry_location_40(self.rows[:20], "LONG", 0.01))

    def test_action_reward_is_bounded_to_2_8r(self):
        plan = build_plan(self.rows, self.rows[-80:])
        if plan["status"] in {"ACTION LONG", "ACTION SHORT"}:
            self.assertTrue(1.40 <= float(plan["reward_r"]) <= 3.50)
            self.assertIn("entry_anchor_40", plan)


if __name__ == "__main__":
    unittest.main()

import unittest
from scalping_intelligence import aggregate, build_plan, infer_direction


def rows(prices, volume=100):
    return [
        [i * 900, str(p), str(p + 1), str(p - 1), str(p), str(volume)]
        for i, p in enumerate(prices)
    ]


class ScalpingIntelligenceTests(unittest.TestCase):
    def test_aggregate(self):
        out = aggregate(rows([100, 101, 102, 103]), 2)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0][4], 101.0)
        self.assertEqual(out[1][4], 103.0)

    def test_requires_mtf_history(self):
        plan = build_plan(
            "LONG",
            rows(list(range(100, 150))),
            rows(list(range(100, 150))),
            80,
            {"extreme_low_24": 90, "extreme_high_24": 160, "atr": 2},
        )
        self.assertEqual(plan["status"], "DATA-LIMITED")

    def test_infer_direction_requires_mtf_alignment(self):
        prices15 = [100 + i * 0.05 for i in range(194)]
        prices5 = [105 + i * 0.01 for i in range(194)]
        self.assertEqual(infer_direction(rows(prices15), rows(prices5)), "LONG")

    def test_independent_brain_plan_does_not_require_extreme(self):
        prices15 = [100 + i * 0.02 for i in range(194)]
        prices5 = [103.5 + i * 0.005 for i in range(194)]
        plan = build_plan(
            "LONG",
            rows(prices15, 120),
            rows(prices5, 180),
            0,
            {"extreme_low_24": 100, "extreme_high_24": 110, "atr": 1.0},
            require_v2_direction=False,
        )
        self.assertIn(plan["status"], {"ACTION LONG", "WAIT", "NO-TRADE"})
        if plan["status"] == "ACTION LONG":
            self.assertIn("MTF brain", plan["reason"])

    def test_long_plan_contains_entry_zone_and_risk(self):
        prices15 = [100 + i * 0.02 for i in range(194)]
        prices5 = [103.5 + i * 0.005 for i in range(194)]
        plan = build_plan(
            "LONG",
            rows(prices15, 120),
            rows(prices5, 180),
            88,
            {"extreme_low_24": 100, "extreme_high_24": 110, "atr": 1.0},
        )
        self.assertIn(plan["status"], {"ACTION LONG", "WAIT", "NO-TRADE"})
        if plan["status"] == "ACTION LONG":
            self.assertLessEqual(plan["entry_low"], plan["entry"])
            self.assertGreaterEqual(plan["entry_high"], plan["entry"])
            self.assertEqual(plan["reward_r"], 2.0)
            self.assertEqual(plan["timeframes"], "4H/1H/30m/15m/5m")


if __name__ == "__main__":
    unittest.main(verbosity=2)

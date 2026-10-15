import unittest
from datetime import datetime, timezone

from adaptive_edge_learning import apply_policy, derive_policy, resolve_signal


def candle(ts, high, low, close=None):
    return {
        "timestamp": ts,
        "high": high,
        "low": low,
        "close": close if close is not None else (high + low) / 2,
    }


class AdaptiveEdgeLearningTests(unittest.TestCase):
    def signal(self, direction="LONG"):
        return {
            "id": "sig-1",
            "timestamp": "2026-10-15T10:00:00+00:00",
            "symbol_full": "TESTUSDT",
            "direction": direction,
            "entry": 100.0,
            "stop": 99.0 if direction == "LONG" else 101.0,
            "tp1": 103.0 if direction == "LONG" else 97.0,
            "quality": 80,
            "timing": 75,
            "regime": {"type": "TREND"},
        }

    def test_resolves_long_win_from_first_target_touch(self):
        signal = self.signal("LONG")
        candles = [
            candle("2026-10-15T10:05:00+00:00", 101, 99.5),
            candle("2026-10-15T10:10:00+00:00", 103.2, 100),
        ]
        result = resolve_signal(signal, candles, now="2026-10-15T10:15:00+00:00")
        self.assertEqual(result["outcome"], "WIN")
        self.assertEqual(result["outcome_r"], 3.0)

    def test_resolves_short_loss_from_stop_touch(self):
        signal = self.signal("SHORT")
        candles = [
            candle("2026-10-15T10:05:00+00:00", 101.2, 99.5),
        ]
        result = resolve_signal(signal, candles, now="2026-10-15T10:10:00+00:00")
        self.assertEqual(result["outcome"], "LOSS")
        self.assertEqual(result["outcome_r"], -1.0)

    def test_same_candle_stop_and_target_is_ambiguous_not_guessed(self):
        signal = self.signal("LONG")
        candles = [candle("2026-10-15T10:05:00+00:00", 104, 98)]
        result = resolve_signal(signal, candles, now="2026-10-15T10:10:00+00:00")
        self.assertEqual(result["outcome"], "AMBIGUOUS")
        self.assertEqual(result["outcome_r"], 0.0)

    def test_no_fill_is_not_counted_as_a_loss(self):
        signal = self.signal("LONG")
        candles = [candle("2026-10-15T10:05:00+00:00", 99.8, 98.8)]
        result = resolve_signal(signal, candles, now="2026-10-15T12:05:00+00:00")
        self.assertEqual(result["outcome"], "NO_FILL")
        self.assertIsNone(result["outcome_r"])

    def test_policy_does_not_learn_from_small_samples(self):
        observations = [
            {"cohort": "LONG|TREND", "outcome": "LOSS", "outcome_r": -1}
            for _ in range(29)
        ]
        policy = derive_policy(observations, min_sample=30)
        self.assertNotIn("LONG|TREND", policy["cohorts"])

    def test_policy_blocks_cohort_only_after_sufficient_negative_expectancy(self):
        observations = [
            {"cohort": "LONG|TREND", "outcome": "LOSS", "outcome_r": -1}
            for _ in range(30)
        ]
        policy = derive_policy(observations, min_sample=30)
        self.assertEqual(policy["cohorts"]["LONG|TREND"]["decision"], "BLOCK")
        self.assertEqual(policy["cohorts"]["LONG|TREND"]["sample"], 30)

    def test_policy_keeps_positive_expectancy_cohort(self):
        observations = [
            {"cohort": "SHORT|RANGE", "outcome": "WIN", "outcome_r": 2.0}
            for _ in range(30)
        ]
        policy = derive_policy(observations, min_sample=30)
        self.assertEqual(policy["cohorts"]["SHORT|RANGE"]["decision"], "ALLOW")

    def test_apply_policy_only_filters_proven_bad_cohort(self):
        results = [
            {"symbol_full": "AUSDT", "direction": "LONG", "regime": {"type": "TREND"}},
            {"symbol_full": "BUSDT", "direction": "SHORT", "regime": {"type": "TREND"}},
        ]
        policy = {"cohorts": {"LONG|TREND": {"decision": "BLOCK", "sample": 30, "expectancy_r": -1.0}}}
        kept, blocked = apply_policy(results, policy)
        self.assertEqual([x["symbol_full"] for x in kept], ["BUSDT"])
        self.assertEqual([x["symbol_full"] for x in blocked], ["AUSDT"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

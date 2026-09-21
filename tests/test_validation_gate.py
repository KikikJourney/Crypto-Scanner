import unittest

from validation_gate import build_report, metrics, walk_forward


def row(ts, outcome="", r=""):
    return {"timestamp": ts, "first_touch": outcome, "outcome_r": r}


class ValidationGateTests(unittest.TestCase):
    def test_metrics(self):
        result = metrics([2.0, -1.0, 2.0, -1.0])
        self.assertEqual(result["n"], 4)
        self.assertEqual(result["win_rate"], 0.5)
        self.assertEqual(result["expectancy_r"], 0.5)
        self.assertEqual(result["net_r"], 2.0)

    def test_walk_forward_preserves_time_order(self):
        result = walk_forward([1.0, 1.0, -1.0, -1.0, 2.0, 2.0], segments=3)
        self.assertEqual([x["n"] for x in result], [2, 2, 2])
        self.assertEqual([x["net_r"] for x in result], [2.0, -2.0, 4.0])

    def test_ambiguous_is_not_counted_as_trade(self):
        rows = [
            row("2026-09-20T10:00:00+00:00", "EXPANSION", "2.0"),
            row("2026-09-20T11:00:00+00:00", "FAIL", "-1.0"),
            row("2026-09-20T12:00:00+00:00", "AMBIGUOUS", ""),
            row("2026-09-20T13:00:00+00:00", "", ""),
        ]
        result = build_report(rows)
        self.assertEqual(result["resolved_trades"], 2)
        self.assertEqual(result["ambiguous"], 1)
        self.assertEqual(result["unresolved"], 1)
        self.assertFalse(result["sample_gate_pass"])

    def test_bootstrap_is_deterministic(self):
        rows = [
            row("2026-09-20T10:00:00+00:00", "EXPANSION", "2.0"),
            row("2026-09-20T11:00:00+00:00", "FAIL", "-1.0"),
        ] * 20
        first = build_report(rows)
        second = build_report(rows)
        self.assertEqual(first["bootstrap_ci95_low"], second["bootstrap_ci95_low"])
        self.assertEqual(first["bootstrap_ci95_high"], second["bootstrap_ci95_high"])
        self.assertTrue(first["sample_gate_pass"])


if __name__ == "__main__":
    unittest.main()

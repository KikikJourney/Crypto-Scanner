import unittest
from scalping_optimizer import build_report


class TestScalpingOptimizer(unittest.TestCase):
    def test_groups_resolved_actions_without_tuning_rules(self):
        rows = [
            {"confidence": "82", "location_15m": "1.0", "reversal_5m": "1.0", "h15": "EXPANSION"},
            {"confidence": "92", "location_15m": "0.5", "reversal_5m": "0.5", "h15": "FAIL"},
            {"confidence": "92", "location_15m": "0.5", "reversal_5m": "1.0", "h15": "AMBIGUOUS"},
        ]
        report = build_report(rows)
        self.assertTrue(any(r["dimension"] == "confidence" and r["bucket"] == "80-84.9" for r in report))
        self.assertTrue(any(r["dimension"] == "confidence" and r["bucket"] == "90-100" for r in report))
        self.assertTrue(all(r["min_sample_for_review"] == 30 for r in report))


if __name__ == "__main__":
    unittest.main()

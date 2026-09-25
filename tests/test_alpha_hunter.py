import csv
import tempfile
import unittest
from pathlib import Path

import alpha_hunter

FIELDS = [
    "timestamp", "symbol", "provider", "stage", "direction", "confidence",
    "alignment", "v2_score", "location_15m", "exhaustion_15m", "base_15m",
    "structure_shift_5m", "reversal_trigger_5m", "early_reversal_score", "reason",
]

class AlphaHunterTests(unittest.TestCase):
    def write_funnel(self, path, rows):
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(FIELDS)
            writer.writerows(rows)

    def test_does_not_promote_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, out, summary = root / "funnel.csv", root / "watch.csv", root / "summary.csv"
            self.write_funnel(source, [[
                "2026-09-25T03:00:00+00:00", "BTCUSDT", "Bitget", "ACTION", "LONG",
                "95", "4", "90", "1", "1", "1", "1", "1", "1", "already actionable",
            ]])
            result, rows = alpha_hunter.run(source, out, summary)
            self.assertEqual(result["candidates"], 0)
            self.assertEqual(rows, [])

    def test_near_miss_becomes_shadow_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, out, summary = root / "funnel.csv", root / "watch.csv", root / "summary.csv"
            self.write_funnel(source, [
                ["2026-09-25T03:00:00+00:00", "TESTUSDT", "Bitget", "WAIT", "LONG",
                 "88", "3.5", "86", ".90", ".80", ".75", ".85", ".90", ".82", "reclaim 0.10<0.25"],
                ["2026-09-25T02:45:00+00:00", "TESTUSDT", "Bitget", "WAIT", "LONG",
                 "82", "3.0", "84", ".80", ".75", ".70", ".80", ".85", ".78", "reclaim 0.08<0.25"],
            ])
            result, rows = alpha_hunter.run(source, out, summary)
            self.assertEqual(result["latest_rows"], 1)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["direction"], "LONG")
            self.assertGreaterEqual(float(rows[0]["alpha_score"]), 50)
            self.assertGreaterEqual(int(rows[0]["persistence_count"]), 2)
            self.assertIn("reclaim", rows[0]["blockers"])

    def test_missing_dataset_is_hard_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                alpha_hunter.run(Path(tmp) / "missing.csv")

    def test_score_is_bounded(self):
        row = {
            "direction": "LONG", "confidence": "100", "v2_score": "100",
            "early_reversal_score": "1", "alignment": "4",
            "location_15m": "1", "exhaustion_15m": "1", "base_15m": "1",
            "structure_shift_5m": "1", "reversal_trigger_5m": "1", "reason": "",
        }
        scored = alpha_hunter.score_candidate(row, 10)
        self.assertLessEqual(scored["alpha_score"], 100)
        self.assertGreaterEqual(scored["alpha_score"], 0)

if __name__ == "__main__":
    unittest.main()

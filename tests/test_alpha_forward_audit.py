import unittest
from datetime import datetime, timezone, timedelta

from alpha_forward_audit import evaluate


class TestAlphaForwardAudit(unittest.TestCase):
    def test_window_field_mapping(self):
        signal = datetime.now(timezone.utc) - timedelta(hours=3)
        row = {
            "timestamp": signal.isoformat(),
            "symbol": "TESTUSDT",
            "direction": "LONG",
            "state": "WATCH",
            "alpha_score": "60",
            "price": "100",
        }
        candles = []
        for i in range(1, 9):
            ts = int((signal + timedelta(minutes=15 * i)).timestamp() * 1000)
            candles.append([
                str(ts), "100", "101", "99", "100.5", "1000", "1000"
            ])
        _, out = evaluate(row, candles)
        self.assertIn("window_15m", out)
        self.assertIn("window_30m", out)
        self.assertIn("window_1h", out)
        self.assertIn("window_2h", out)
        self.assertNotIn("window_1", out)
        self.assertNotIn("window_2", out)
        self.assertNotIn("window_4", out)
        self.assertNotIn("window_8", out)
        self.assertEqual(out["status"], "COMPLETE")


if __name__ == "__main__":
    unittest.main()

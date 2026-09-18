import unittest

from signal_funnel_diagnostic import diagnose


def candle(ts, close=100.0, volume=10.0):
    return [ts, close, close + 1, close - 1, close, volume]


class TestSignalFunnelDiagnostic(unittest.TestCase):
    def test_no_direction_is_counted(self):
        rows15 = [candle(i * 900) for i in range(194)]
        rows5 = [candle(i * 300) for i in range(194)]
        extreme = {"status": "NO EXTREME", "direction": None, "score": 50}
        result = {
            "symbol": "TESTUSDT", "extreme": extreme,
            "scalping_rows_15m": rows15, "scalping_rows_5m": rows5,
            "extreme_features": {"atr": 1, "extreme_low_24": 90, "extreme_high_24": 110},
        }
        summary, detail = diagnose([result], [], 10, 1, "Bitget", "2026-01-01T00:00:00+00:00")
        self.assertEqual(summary["data_valid"], 1)
        self.assertEqual(summary["no_direction"], 1)
        self.assertEqual(summary["actions"], 0)
        self.assertEqual(detail[0]["stage"], "NO_DIRECTION")

    def test_data_error_is_preserved_in_summary(self):
        summary, detail = diagnose([], [("BADUSDT", "stale")], 10, 1, "Bitget", "2026-01-01T00:00:00+00:00")
        self.assertEqual(summary["data_valid"], 0)
        self.assertEqual(summary["data_errors"], 1)
        self.assertEqual(detail, [])


if __name__ == "__main__":
    unittest.main()

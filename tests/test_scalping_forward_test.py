import unittest
import scalping_forward_test as ft


def action(ts="2026-09-20T10:00:00+00:00", direction="LONG"):
    return {
        "id": f"A-{direction}-{ts}", "timestamp": ts, "symbol": "TESTUSDT",
        "provider": "Bitget", "direction": direction, "entry": "100",
        "stop": "99", "target": "102",
    }


def candle(ts, high, low):
    return {"id": f"C-{ts}", "timestamp": ts, "symbol": "TESTUSDT",
            "provider": "Bitget", "open": "100", "high": str(high),
            "low": str(low), "close": "100"}


class ScalpingForwardTest(unittest.TestCase):
    def test_first_touch_long_tp(self):
        self.assertEqual(ft._first_touch("LONG", 102.1, 99.5, 99, 102), "EXPANSION")
        self.assertEqual(ft._first_touch("LONG", 100.5, 98.9, 99, 102), "FAIL")

    def test_first_touch_short_tp(self):
        self.assertEqual(ft._first_touch("SHORT", 100.5, 97.9, 101, 98), "EXPANSION")
        self.assertEqual(ft._first_touch("SHORT", 102.1, 99.5, 101, 98), "FAIL")

    def test_same_candle_is_ambiguous(self):
        self.assertEqual(ft._first_touch("LONG", 102.5, 98.5, 99, 102), "AMBIGUOUS")

    def test_mfe_mae_long(self):
        mfe, mae = ft._metrics("LONG", 100, [candle("2026-09-20T10:05:00+00:00", 103, 98)])
        self.assertEqual(mfe, 3.0)
        self.assertEqual(mae, 2.0)

    def test_evaluate_uses_future_ohlc_and_first_touch(self):
        result = ft.evaluate([action()], [
            candle("2026-09-20T10:05:00+00:00", 101, 99.5),
            candle("2026-09-20T10:10:00+00:00", 102.1, 100),
        ])
        self.assertEqual(result[0]["h15"], "EXPANSION")
        self.assertEqual(result[0]["first_touch"], "EXPANSION")
        self.assertEqual(result[0]["first_touch_timestamp"], "2026-09-20T10:15:00+00:00")
        self.assertEqual(result[0]["resolved_horizon"], "15")
        self.assertEqual(result[0]["outcome_r"], "2.0")
        self.assertEqual(result[0]["mfe_pct"], 2.1)
        self.assertEqual(result[0]["mae_pct"], 0.5)

    def test_close_timestamp_controls_horizon_boundary(self):
        result = ft.evaluate([action()], [
            candle("2026-09-20T09:55:00+00:00", 102.5, 100),
            candle("2026-09-20T10:10:00+00:00", 102.1, 100),
        ])
        self.assertEqual(result[0]["h15"], "EXPANSION")
        self.assertEqual(result[0]["first_touch_timestamp"], "2026-09-20T10:15:00+00:00")

    def test_evaluate_ignores_candles_before_signal(self):
        result = ft.evaluate([action()], [
            candle("2026-09-20T09:55:00+00:00", 103, 98),
            candle("2026-09-20T10:05:00+00:00", 100.5, 99.5),
        ])
        self.assertEqual(result[0]["h15"], "")
        self.assertEqual(result[0]["first_touch"], "")


if __name__ == "__main__":
    unittest.main(verbosity=2)

import unittest
from datetime import datetime, timedelta
import execution_retest_calibration as rc


class ExecutionRetestCalibrationTests(unittest.TestCase):
    def action(self, direction="LONG"):
        return {
            "id": "a1", "timestamp": "2026-09-22T00:00:00+00:00",
            "symbol": "TESTUSDT", "provider": "Bitget",
            "direction": direction, "strategy_version": rc.STRATEGY_VERSION,
            "entry": "100", "stop": "99", "target": "104",
        }

    def candle(self, ts, close, high, low):
        opened = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        closed = opened + timedelta(minutes=5)
        return {
            "timestamp": ts,
            "close_timestamp": closed.isoformat(),
            "symbol": "TESTUSDT", "provider": "Bitget",
            "open": str(close), "high": str(high), "low": str(low), "close": str(close),
        }

    def test_requires_confirmation_then_retest(self):
        detail = rc.calibrate([self.action()], [
            self.candle("2026-09-22T00:05:00+00:00", 101, 102, 100),
            self.candle("2026-09-22T00:10:00+00:00", 100, 101, 99.5),
            self.candle("2026-09-22T00:15:00+00:00", 102, 103, 100.5),
        ])
        self.assertEqual(detail[0]["status"], "RESOLVED")
        self.assertEqual(detail[0]["retest_close"], "100")
        self.assertEqual(detail[0]["outcome"], "EXPANSION")

    def test_no_retest_stays_unresolved(self):
        detail = rc.calibrate([self.action()], [
            self.candle("2026-09-22T00:05:00+00:00", 101, 102, 100),
            self.candle("2026-09-22T00:10:00+00:00", 103, 104, 102),
        ])
        self.assertEqual(detail[0]["status"], "SKIPPED")
        self.assertIn("no closed-candle retest", detail[0]["reason"])

    def test_retest_candle_cannot_resolve_trade(self):
        detail = rc.calibrate([self.action()], [
            self.candle("2026-09-22T00:05:00+00:00", 101, 102, 100),
            self.candle("2026-09-22T00:10:00+00:00", 100, 105, 99),
        ])
        self.assertEqual(detail[0]["status"], "ELIGIBLE_UNRESOLVED")

    def test_confirmation_candle_touch_invalidates_retest(self):
        detail = rc.calibrate([self.action()], [
            self.candle("2026-09-22T00:05:00+00:00", 101, 102, 99),
            self.candle("2026-09-22T00:10:00+00:00", 100, 101, 99.5),
        ])
        self.assertEqual(detail[0]["status"], "SKIPPED")
        self.assertIn("confirmation candle already touched", detail[0]["reason"])


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import execution_calibration as ec


class ExecutionCalibrationTests(unittest.TestCase):
    def action(self, direction="LONG"):
        return {
            "id": "a1", "timestamp": "2026-09-22T00:00:00+00:00",
            "symbol": "TESTUSDT", "provider": "Bitget",
            "direction": direction, "confidence": "100",
            "strategy_version": ec.CURRENT_STRATEGY_VERSION,
            "entry": "100", "stop": "99", "target": "104",
        }

    def candle(self, ts, close, high, low):
        return {
            "timestamp": ts, "close_timestamp": ts.replace("00:00:00", "00:05:00"),
            "symbol": "TESTUSDT", "provider": "Bitget",
            "open": str(close), "high": str(high), "low": str(low), "close": str(close),
        }

    def test_confirmation_is_required_before_entry(self):
        action = self.action()
        market = [
            self.candle("2026-09-22T00:05:00+00:00", 99, 100, 98.5),
            self.candle("2026-09-22T00:10:00+00:00", 105, 106, 104),
        ]
        detail = ec.calibrate([action], market)
        self.assertEqual(detail[0]["status"], "SKIPPED")
        self.assertIn("did not preserve direction", detail[0]["reason"])

    def test_confirmation_candle_is_not_allowed_to_resolve_trade(self):
        action = self.action()
        market = [
            self.candle("2026-09-22T00:05:00+00:00", 101, 102, 99.5),
            self.candle("2026-09-22T00:10:00+00:00", 101, 108, 100),
        ]
        detail = ec.calibrate([action], market)
        self.assertEqual(detail[0]["status"], "RESOLVED")
        self.assertEqual(detail[0]["outcome"], "EXPANSION")
        self.assertEqual(detail[0]["outcome_r"], "2.0")

    def test_confirmation_touch_invalidates_fill(self):
        action = self.action()
        market = [
            self.candle("2026-09-22T00:05:00+00:00", 101, 102, 97),
            self.candle("2026-09-22T00:10:00+00:00", 101, 102, 100),
        ]
        detail = ec.calibrate([action], market)
        self.assertEqual(detail[0]["status"], "SKIPPED")
        self.assertIn("already touched", detail[0]["reason"])


if __name__ == "__main__":
    unittest.main()

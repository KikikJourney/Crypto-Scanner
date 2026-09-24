import unittest
from datetime import datetime, timedelta, timezone

import execution_entry_location_40 as m


class EntryLocation40Tests(unittest.TestCase):
    def candle(self, minutes, close, high=None, low=None):
        opened = datetime(2026, 9, 22, 0, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes)
        high = close + 1 if high is None else high
        low = close - 1 if low is None else low
        return {
            "timestamp": opened.isoformat(),
            "close_timestamp": (opened + timedelta(minutes=5)).isoformat(),
            "symbol": "TESTUSDT",
            "provider": "Bitget",
            "open": str(close),
            "high": str(high),
            "low": str(low),
            "close": str(close),
        }

    def action(self, direction="LONG"):
        return {
            "id": "a1",
            "timestamp": "2026-09-22T04:00:00+00:00",
            "symbol": "TESTUSDT",
            "provider": "Bitget",
            "direction": direction,
            "strategy_version": m.CURRENT_STRATEGY_VERSION,
            "entry": "100",
            "stop": "98" if direction == "LONG" else "102",
            "target": "104" if direction == "LONG" else "99.7",
        }

    def market(self, direction="LONG", fill=True):
        rows = []
        for i in range(40):
            rows.append(self.candle(i * 5, 100 + (i % 3) * 0.1))
        if direction == "LONG":
            rows[-1]["low"] = "99"
            if fill:
                rows.append(self.candle(245, 100, high=101, low=98.9))
                rows.append(self.candle(250, 103, high=104.5, low=99.5))
            else:
                rows.append(self.candle(245, 101, high=102, low=100.5))
        else:
            rows[-1]["high"] = "101"
            if fill:
                rows.append(self.candle(245, 100, high=101.1, low=99))
                rows.append(self.candle(250, 99, high=100.5, low=99.0))
        return rows

    def test_uses_only_pre_signal_candles(self):
        action = self.action()
        detail = m.calibrate([action], self.market(fill=True))
        self.assertEqual(detail[0]["status"], "RESOLVED")
        self.assertEqual(detail[0]["direction"], "LONG")
        self.assertGreater(float(detail[0]["anchor_40"]), 0)

    def test_unfilled_limit_is_not_a_loss(self):
        action = self.action()
        detail = m.calibrate([action], self.market(fill=False))
        self.assertEqual(detail[0]["status"], "UNFILLED")
        self.assertEqual(detail[0]["outcome"], "")

    def test_fill_candle_with_stop_or_target_is_ambiguous(self):
        action = self.action()
        rows = self.market(fill=True)
        rows[-2]["high"] = "104.5"
        detail = m.calibrate([action], rows)
        self.assertEqual(detail[0]["status"], "AMBIGUOUS_FILL")
        self.assertEqual(detail[0]["outcome"], "AMBIGUOUS")

    def test_short_anchor_is_highest_high(self):
        action = self.action("SHORT")
        detail = m.calibrate([action], self.market("SHORT", fill=True))
        self.assertEqual(detail[0]["direction"], "SHORT")
        self.assertGreater(float(detail[0]["anchor_40"]), float(detail[0]["planned_entry"]))


if __name__ == "__main__":
    unittest.main()

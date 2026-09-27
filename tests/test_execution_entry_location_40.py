import unittest
from datetime import datetime, timedelta, timezone

import execution_entry_location_40 as m


class EntryLocation40Tests(unittest.TestCase):
    def candle(self, minutes, close, high=None, low=None):
        opened = datetime(2026, 9, 22, 0, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes)
        high = close + 0.05 if high is None else high
        low = close - 0.05 if low is None else low
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
            "stop": "98",
            # Structural target deliberately sits inside the 3R-8R
            # feasibility band after ATR-derived entry/stop recalibration.
            "target": "99.50" if direction == "LONG" else "100.50",
        }

    def market(self, direction="LONG", fill=True):
        rows = []
        for i in range(40):
            rows.append(self.candle(i * 5, 100.0))
        if direction == "LONG":
            rows[-1]["low"] = "99.00"
            if fill:
                rows.append(self.candle(245, 99.02, high=99.06, low=99.00))
                rows.append(self.candle(250, 99.50, high=99.60, low=99.40))
            else:
                rows.append(self.candle(245, 100.0, high=100.08, low=99.98))
        else:
            rows[-1]["high"] = "101.00"
            if fill:
                rows.append(self.candle(245, 100.98, high=101.00, low=100.94))
                rows.append(self.candle(250, 100.50, high=100.60, low=100.40))
            else:
                rows.append(self.candle(245, 100.0, high=100.02, low=99.92))
        return rows

    def test_uses_only_pre_signal_candles(self):
        row = m.calibrate([self.action()], self.market(fill=True))[0]
        self.assertEqual(row["status"], "RESOLVED")
        self.assertEqual(row["direction"], "LONG")
        self.assertAlmostEqual(float(row["anchor_40"]), 99.0)

    def test_unfilled_limit_is_not_a_loss(self):
        row = m.calibrate([self.action()], self.market(fill=False))[0]
        self.assertEqual(row["status"], "UNFILLED")
        self.assertEqual(row["outcome"], "")

    def test_fill_candle_with_stop_or_target_is_ambiguous(self):
        rows = self.market(fill=True)
        rows[-2]["low"] = "98.90"
        row = m.calibrate([self.action()], rows)[0]
        self.assertEqual(row["status"], "AMBIGUOUS_FILL")
        self.assertEqual(row["outcome"], "AMBIGUOUS")

    def test_structural_target_is_used_and_rr_is_measured(self):
        row = m.calibrate([self.action()], self.market(fill=True))[0]
        self.assertAlmostEqual(float(row["planned_target"]), 99.50)
        self.assertGreater(float(row["reward_r"]), 3.0)
        self.assertLess(float(row["reward_r"]), 8.0)
        self.assertEqual(row["outcome"], "EXPANSION")
        self.assertAlmostEqual(float(row["outcome_r"]), float(row["reward_r"]), places=6)

    def test_short_anchor_is_highest_high(self):
        row = m.calibrate([self.action("SHORT")], self.market("SHORT", fill=True))[0]
        self.assertEqual(row["direction"], "SHORT")
        self.assertAlmostEqual(float(row["anchor_40"]), 101.0)

    def test_fixed_r_ladder_is_not_present(self):
        self.assertFalse(hasattr(m, "REWARD_LEVELS"))
        self.assertFalse(hasattr(m, "target_2r"))
        self.assertNotIn("target_2r", m.DETAIL_FIELDS)
        self.assertNotIn("target_8r", m.DETAIL_FIELDS)


if __name__ == "__main__":
    unittest.main()

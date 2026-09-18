import unittest

from telegram_notifier import format_action
from send_telegram_actions import _still_actionable


class TelegramNotifierTests(unittest.TestCase):
    def test_format_action_contains_mtf_trade_plan(self):
        text = format_action({
            "direction": "LONG",
            "symbol": "RDDTUSDT",
            "entry": "157.98",
            "entry_low": "157.50",
            "entry_high": "158.46",
            "stop": "155.51",
            "target": "162.90",
            "risk_pct": "1.55",
            "reward_r": "2.0",
            "confidence": "86.5",
            "score": "72.2",
            "timeframes": "4H/1H/30m/15m/5m",
            "rsi_5m": "54.2",
            "liquidity_sweep_5m": "True",
            "volume_5m": "0.82",
            "valid_until": "2026-09-18T07:15:00+00:00",
        })
        self.assertIn("ZORATHVAEL SCALPING LONG", text)
        self.assertIn("Entry zone: 157.50 - 158.46", text)
        self.assertIn("Stop: 155.51", text)
        self.assertIn("Target: 162.90", text)
        self.assertIn("RR: 2.0", text)
        self.assertIn("Risk: 1.55%", text)
        self.assertIn("Confidence: 86.5/100", text)

    def test_live_window_accepts_long_inside_entry_zone_before_target(self):
        row = {
            "direction": "LONG",
            "entry": "105",
            "entry_low": "104",
            "entry_high": "107",
            "stop": "100",
            "target": "115",
        }
        self.assertTrue(_still_actionable(row, 106))

    def test_live_window_rejects_long_after_target_or_outside_entry_zone(self):
        row = {
            "direction": "LONG",
            "entry": "105",
            "entry_low": "104",
            "entry_high": "107",
            "stop": "100",
            "target": "115",
        }
        self.assertFalse(_still_actionable(row, 116))
        self.assertFalse(_still_actionable(row, 103))
        self.assertFalse(_still_actionable(row, 100))

    def test_live_window_accepts_short_inside_entry_zone_before_target(self):
        row = {
            "direction": "SHORT",
            "entry": "105",
            "entry_low": "103",
            "entry_high": "107",
            "stop": "115",
            "target": "95",
        }
        self.assertTrue(_still_actionable(row, 104))

    def test_live_window_rejects_short_after_target_or_outside_entry_zone(self):
        row = {
            "direction": "SHORT",
            "entry": "105",
            "entry_low": "103",
            "entry_high": "107",
            "stop": "115",
            "target": "95",
        }
        self.assertFalse(_still_actionable(row, 94))
        self.assertFalse(_still_actionable(row, 108))
        self.assertFalse(_still_actionable(row, 115))


if __name__ == "__main__":
    unittest.main(verbosity=2)

import unittest

from telegram_notifier import format_action
from send_telegram_actions import _still_actionable


class TelegramNotifierTests(unittest.TestCase):
    def test_format_action_contains_fixed_trade_plan(self):
        text = format_action({
            'direction': 'LONG', 'symbol': 'RDDTUSDT', 'trigger': '157.98',
            'stop': '155.51', 'target': '162.90', 'risk_pct': '1.55',
            'score': '72.2', 'timestamp': '2026-09-16T07:00:00+00:00'
        })
        self.assertIn('ZORATHVAEL ACTION LONG', text)
        self.assertIn('Entry: 157.98', text)
        self.assertIn('Stop: 155.51', text)
        self.assertIn('Target: 162.90', text)
        self.assertIn('Risk: 1.55%', text)

    def test_live_window_accepts_long_after_entry_before_target(self):
        row={'direction':'LONG','entry':'105','stop':'100','target':'115'}
        self.assertTrue(_still_actionable(row,106))

    def test_live_window_rejects_long_after_target_or_before_entry(self):
        row={'direction':'LONG','entry':'105','stop':'100','target':'115'}
        self.assertFalse(_still_actionable(row,116))
        self.assertFalse(_still_actionable(row,104))
        self.assertFalse(_still_actionable(row,100))

    def test_live_window_accepts_short_after_entry_before_target(self):
        row={'direction':'SHORT','entry':'105','stop':'115','target':'95'}
        self.assertTrue(_still_actionable(row,104))

    def test_live_window_rejects_short_after_target_or_before_entry(self):
        row={'direction':'SHORT','entry':'105','stop':'115','target':'95'}
        self.assertFalse(_still_actionable(row,94))
        self.assertFalse(_still_actionable(row,106))
        self.assertFalse(_still_actionable(row,115))


if __name__ == '__main__':
    unittest.main(verbosity=2)

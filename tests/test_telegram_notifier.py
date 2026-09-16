import unittest

from telegram_notifier import format_action


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


if __name__ == '__main__':
    unittest.main(verbosity=2)

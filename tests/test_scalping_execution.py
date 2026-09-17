import unittest
from scalping_execution_layer import aggregate_30m, build_plan


def rows(prices):
    return [[i * 900, str(p), str(p + 1), str(p - 1), str(p), '100'] for i, p in enumerate(prices)]


class ScalpingExecutionTests(unittest.TestCase):
    def features(self):
        return {
            'data_ok': True, 'price': 100.0, 'atr': 2.0,
            'extreme_low_24': 95.0, 'extreme_high_24': 105.0,
        }

    def test_30m_aggregation_uses_two_15m_candles(self):
        out = aggregate_30m(rows([100, 101, 102, 103]))
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0][4], 101.0)
        self.assertEqual(out[1][4], 103.0)

    def test_long_waits_when_trigger_not_confirmed(self):
        f = self.features()
        # Trigger is prior 30m high = 101; latest 30m close is 100.
        plan = build_plan(f, rows([99, 100, 100, 100]), 'LONG')
        self.assertEqual(plan['status'], 'WAIT FOR LONG TRIGGER')
        self.assertFalse(plan['confirmed'])
        self.assertEqual(plan['confirmation_timeframe'], '30m')

    def test_long_action_requires_closed_30m_confirmation(self):
        f = self.features(); f['price'] = 103
        # Prior 30m high = 101; latest closed 30m close = 103.
        plan = build_plan(f, rows([99, 101, 102, 103]), 'LONG')
        self.assertEqual(plan['status'], 'ACTION LONG')
        self.assertTrue(plan['confirmed'])
        self.assertEqual(plan['trigger_timeframe'], '15m')
        self.assertEqual(plan['confirmation_timeframe'], '30m')
        self.assertEqual(plan['reward_r'], 2.0)

    def test_short_action_requires_closed_30m_confirmation(self):
        f = self.features(); f['price'] = 97
        # Prior 30m low = 99; latest closed 30m close = 97.
        plan = build_plan(f, rows([101, 99, 98, 97]), 'SHORT')
        self.assertEqual(plan['status'], 'ACTION SHORT')
        self.assertTrue(plan['confirmed'])

    def test_stale_trigger_is_rejected(self):
        f = self.features(); f['price'] = 94
        plan = build_plan(f, rows([99, 100, 100, 100]), 'LONG')
        self.assertEqual(plan['status'], 'STALE')


if __name__ == '__main__':
    unittest.main(verbosity=2)

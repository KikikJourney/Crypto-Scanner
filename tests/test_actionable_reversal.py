import unittest

from actionable_reversal_layer import build_action_plan, _action_outcome


class ActionableReversalTests(unittest.TestCase):
    def features(self):
        return {
            'data_ok': True,
            'price': 90.0,
            'atr': 2.0,
            'extreme_low_24': 88.0,
            'extreme_high_24': 120.0,
            'long_trigger': 92.0,
            'short_trigger': 116.0,
        }

    def test_long_waits_for_structure_reclaim(self):
        r = build_action_plan(self.features(), 'LONG')
        self.assertEqual(r['status'], 'WAIT FOR LONG TRIGGER')
        self.assertEqual(r['trigger'], 92.0)
        self.assertLess(r['stop'], 88.0)
        self.assertGreater(r['target'], 92.0)

    def test_long_action_when_trigger_is_confirmed(self):
        f = self.features(); f['price'] = 93.0
        r = build_action_plan(f, 'LONG')
        self.assertEqual(r['status'], 'ACTION LONG')
        self.assertEqual(r['reason'], '4H structure reclaim confirmed')

    def test_short_waits_for_structure_break(self):
        f = self.features(); f['price'] = 118.0
        r = build_action_plan(f, 'SHORT')
        self.assertEqual(r['status'], 'WAIT FOR SHORT TRIGGER')
        self.assertEqual(r['trigger'], 116.0)

    def test_short_action_when_trigger_is_confirmed(self):
        f = self.features(); f['price'] = 115.0
        r = build_action_plan(f, 'SHORT')
        self.assertEqual(r['status'], 'ACTION SHORT')

    def test_data_limited_never_becomes_action(self):
        r = build_action_plan({'data_ok': False}, 'LONG')
        self.assertEqual(r['status'], 'DATA-LIMITED')

    def test_action_outcomes(self):
        self.assertEqual(_action_outcome('LONG', 92, 96, 90, 96), 'EXPANSION')
        self.assertEqual(_action_outcome('LONG', 92, 90, 90, 96), 'FAIL')
        self.assertEqual(_action_outcome('SHORT', 116, 112, 118, 112), 'EXPANSION')
        self.assertEqual(_action_outcome('SHORT', 116, 118, 118, 112), 'FAIL')
        self.assertIsNone(_action_outcome('LONG', 92, 93, 90, 96))

    def test_invalid_risk_is_not_action(self):
        # Trigger far above the extreme low makes the execution risk > 8%.
        f = self.features(); f['long_trigger'] = 105.0
        r = build_action_plan(f, 'LONG')
        self.assertEqual(r['status'], 'WAIT')
        self.assertGreater(r['risk_pct'], 8.0)


if __name__ == '__main__':
    unittest.main(verbosity=2)

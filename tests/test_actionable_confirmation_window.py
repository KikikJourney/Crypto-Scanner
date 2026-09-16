import unittest

from actionable_forward_test import build_confirmed_actions


class ActionableConfirmationWindowTests(unittest.TestCase):
    def _extreme(self, ts='2026-09-16T10:00:00+00:00'):
        return {
            'timestamp': ts,
            'provider': 'Bitget',
            'symbol': 'TESTUSDT',
            'direction': 'LONG',
            'event_role': 'PRIMARY',
            'event_id': 'Bitget_TESTUSDT_LONG_' + ts,
            'trigger': '100',
            'action_stop': '98',
            'action_target': '104',
            'action_risk_pct': '2',
            'action_reward_r': '2',
            'atr_pct': '1',
            'score': '90',
        }

    def test_confirmation_after_event_window_is_rejected(self):
        extreme = self._extreme()
        snapshots = [
            {'timestamp': '2026-09-16T12:01:00+00:00', 'provider': 'Bitget', 'symbol': 'TESTUSDT', 'price': '100'},
        ]
        self.assertEqual(build_confirmed_actions([extreme], snapshots), [])

    def test_confirmation_at_event_window_boundary_is_allowed(self):
        extreme = self._extreme()
        snapshots = [
            {'timestamp': '2026-09-16T12:00:00+00:00', 'provider': 'Bitget', 'symbol': 'TESTUSDT', 'price': '100'},
        ]
        actions = build_confirmed_actions([extreme], snapshots)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]['entry'], 100.0)

    def test_confirmation_after_stale_excursion_is_rejected(self):
        """A stale move before the trigger invalidates the whole event."""
        extreme = self._extreme()
        snapshots = [
            # 98 is 2 ATR below the 100 LONG trigger, so the trigger is stale.
            {'timestamp': '2026-09-16T10:30:00+00:00', 'provider': 'Bitget', 'symbol': 'TESTUSDT', 'price': '98'},
            # Returning to the trigger later must not resurrect the stale setup.
            {'timestamp': '2026-09-16T11:00:00+00:00', 'provider': 'Bitget', 'symbol': 'TESTUSDT', 'price': '100'},
        ]
        self.assertEqual(build_confirmed_actions([extreme], snapshots), [])


if __name__ == '__main__':
    unittest.main()

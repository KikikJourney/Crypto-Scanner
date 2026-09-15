import unittest
from datetime import datetime, timezone, timedelta

from early_reversal_layer import classify, early_score, _outcome


def result(**parts):
    base = {
        'long_location': .0, 'long_exhaustion': .0, 'long_flow': .0, 'long_reclaim': .0,
        'short_location': .0, 'short_exhaustion': .0, 'short_flow': .0, 'short_reject': .0,
    }
    base.update(parts)
    return base


class EarlyReversalTests(unittest.TestCase):
    def test_long_early_without_expansion(self):
        r = result(long_location=.90, long_exhaustion=.70, long_flow=.62, long_reclaim=.20)
        d = classify(r)
        self.assertEqual(d['status'], 'EARLY REVERSAL LONG')
        self.assertGreaterEqual(d['score'], 65)

    def test_short_early_without_expansion(self):
        r = result(short_location=.90, short_exhaustion=.70, short_flow=.62, short_reject=.20)
        d = classify(r)
        self.assertEqual(d['status'], 'EARLY REVERSAL SHORT')

    def test_midrange_blocked(self):
        r = result(long_location=.40, long_exhaustion=.80, long_flow=.70, long_reclaim=.60)
        self.assertFalse(classify(r)['status'].startswith('EARLY REVERSAL'))

    def test_weak_flow_blocked(self):
        r = result(long_location=.90, long_exhaustion=.70, long_flow=.48, long_reclaim=.30)
        self.assertFalse(classify(r)['status'].startswith('EARLY REVERSAL'))

    def test_weak_exhaustion_blocked(self):
        r = result(long_location=.90, long_exhaustion=.35, long_flow=.65, long_reclaim=.30)
        self.assertFalse(classify(r)['status'].startswith('EARLY REVERSAL'))

    def test_weak_structure_blocked(self):
        r = result(long_location=.95, long_exhaustion=.80, long_flow=.70, long_reclaim=.05)
        self.assertFalse(classify(r)['status'].startswith('EARLY REVERSAL'))

    def test_score_is_deterministic(self):
        self.assertEqual(early_score({'location': .9, 'exhaustion': .7, 'flow': .62, 'structure': .2}), 67.0)

    def test_missing_data_is_not_entry(self):
        r = result(long_location=.9, long_exhaustion=None, long_flow=.7, long_reclaim=.3)
        d = classify(r)
        self.assertNotEqual(d['status'], 'EARLY REVERSAL LONG')
        self.assertIn('data unavailable', d['blocker'])

    def test_future_only_outcome(self):
        self.assertEqual(_outcome('LONG', 100, 102.1, 1.0), 'EXPANSION')
        self.assertEqual(_outcome('LONG', 100, 99.0, 1.0), 'FAIL')
        self.assertEqual(_outcome('SHORT', 100, 97.9, 1.0), 'EXPANSION')
        self.assertEqual(_outcome('SHORT', 100, 101.0, 1.0), 'FAIL')


if __name__ == '__main__':
    unittest.main(verbosity=2)

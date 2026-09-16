import unittest
from actionable_forward_test import build_confirmed_actions, summarize


class ActionableForwardTest(unittest.TestCase):
    def extreme(self, direction='LONG'):
        return [{
            'timestamp':'2026-09-16T00:00:00+00:00','symbol':'TESTUSDT','provider':'Bitget',
            'direction':direction,'score':'75','event_id':'TEST_EVENT','event_role':'PRIMARY',
            'trigger':'105','action_stop':'100','action_target':'115','action_risk_pct':'4.76',
            'action_reward_r':'2.0'
        }]

    def snaps(self, prices):
        return [{'timestamp':f'2026-09-16T{h:02d}:00:00+00:00','symbol':'TESTUSDT','provider':'Bitget','price':str(p)} for h,p in prices]

    def test_confirmation_uses_fixed_trigger_and_future_only_outcome(self):
        rows = build_confirmed_actions(self.extreme(), self.snaps([(0,103),(1,105),(2,110),(3,116)]))
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['entry'],105.0)
        self.assertEqual(rows[0]['timestamp'],'2026-09-16T01:00:00+00:00')
        self.assertEqual(rows[0]['event_role'],'PRIMARY')

    def test_no_confirmation_means_no_action(self):
        rows = build_confirmed_actions(self.extreme(), self.snaps([(0,103),(1,104),(2,104)]))
        self.assertEqual(rows,[])

    def test_summary_counts_events_not_horizons(self):
        rows = [
            {'event_id':'E1','event_role':'PRIMARY','h1':'','h4':'EXPANSION','h12':'EXPANSION','h24':''},
            {'event_id':'E1','event_role':'DUPLICATE','h1':'FAIL','h4':'','h12':'','h24':''},
            {'event_id':'E2','event_role':'PRIMARY','h1':'FAIL','h4':'','h12':'','h24':''},
            {'event_id':'E3','event_role':'PRIMARY','h1':'','h4':'','h12':'','h24':''},
        ]
        s=summarize(rows)
        self.assertEqual(s['raw_actions'],4)
        self.assertEqual(s['independent_events'],3)
        self.assertEqual(s['resolved_events'],2)
        self.assertEqual(s['unresolved_events'],1)
        self.assertEqual(s['event_expansion'],1)
        self.assertEqual(s['event_fail'],1)
        self.assertEqual(s['event_ambiguous'],0)


if __name__ == '__main__':
    unittest.main(verbosity=2)

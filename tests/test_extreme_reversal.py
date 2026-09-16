import unittest
from datetime import datetime, timezone

from extreme_reversal_layer import classify, _outcome, _assign_events
from extreme_market_data import build_features
from extreme_event_stats import summarize


def extreme(**overrides):
    x={'data_ok':True,'h1_pos_48':.03,'h1_pos_24':.05,'dist_low_atr':.2,'dist_high_atr':3.0,'move_into_low_atr':2.0,'move_into_high_atr':.2,'turn_long':.8,'turn_short':.1}
    x.update(overrides); return x


class ExtremeReversalTests(unittest.TestCase):
    def test_true_bottom_long(self):
        self.assertEqual(classify(extreme())['status'],'EXTREME REVERSAL LONG')

    def test_true_top_short(self):
        r=classify(extreme(h1_pos_48=.97,h1_pos_24=.95,dist_low_atr=3.0,dist_high_atr=.2,move_into_low_atr=.2,move_into_high_atr=2.0,turn_long=.1,turn_short=.8))
        self.assertEqual(r['status'],'EXTREME REVERSAL SHORT')

    def test_midrange_blocked(self):
        r=classify(extreme(h1_pos_48=.50,h1_pos_24=.50,dist_low_atr=3.0,dist_high_atr=3.0,move_into_low_atr=2.0,move_into_high_atr=2.0))
        self.assertFalse(r['status'].startswith('EXTREME REVERSAL'))

    def test_weak_turn_blocked(self):
        self.assertFalse(classify(extreme(turn_long=.05))['status'].startswith('EXTREME REVERSAL'))
        self.assertFalse(classify(extreme(h1_pos_48=.97,h1_pos_24=.95,dist_low_atr=3.0,dist_high_atr=.2,move_into_low_atr=.2,move_into_high_atr=2.0,turn_long=.1,turn_short=.05))['status'].startswith('EXTREME REVERSAL'))

    def test_negative_distance_blocked(self):
        self.assertFalse(classify(extreme(dist_low_atr=-5.0))['status'].startswith('EXTREME REVERSAL'))
        self.assertFalse(classify(extreme(h1_pos_48=.97,h1_pos_24=.95,dist_low_atr=3.0,dist_high_atr=-5.0,move_into_low_atr=.2,move_into_high_atr=2.0,turn_long=.1,turn_short=.8))['status'].startswith('EXTREME REVERSAL'))

    def test_missing_data_blocked(self):
        self.assertEqual(classify({'data_ok':False})['status'],'DATA-LIMITED')

    def test_forward_outcome_uses_two_atr_favorable_and_one_atr_adverse(self):
        self.assertEqual(_outcome('SHORT',100,97,1.0),'EXPANSION')
        self.assertEqual(_outcome('SHORT',100,101,1.0),'FAIL')
        self.assertIsNone(_outcome('SHORT',100,99.5,1.0))

    def test_repeated_signals_within_event_gap_share_event(self):
        rows=[]
        for i,minutes in enumerate((0,15,45,105,150,300)):
            ts=datetime(2026,1,1,tzinfo=timezone.utc).timestamp()+minutes*60
            iso=datetime.fromtimestamp(ts,tz=timezone.utc).isoformat()
            rows.append({'id':str(i),'timestamp':iso,'symbol':'MINAUSDT','provider':'Bitget','direction':'SHORT','event_id':'','event_role':''})
        _assign_events(rows)
        self.assertEqual(len({r['event_id'] for r in rows}),2)
        self.assertEqual([r['event_role'] for r in rows],['PRIMARY','DUPLICATE','DUPLICATE','DUPLICATE','DUPLICATE','PRIMARY'])

    def test_event_assignment_handles_unsorted_rows_and_exact_gap(self):
        rows=[]
        for i,minutes in ((2,120),(0,0),(1,119),(3,121),(4,242)):
            ts=datetime(2026,1,1,tzinfo=timezone.utc).timestamp()+minutes*60
            rows.append({'id':str(i),'timestamp':datetime.fromtimestamp(ts,tz=timezone.utc).isoformat(),'symbol':'BTCUSDT','provider':'Bitget','direction':'LONG','event_id':'','event_role':''})
        _assign_events(rows)
        by_id={r['id']:r for r in rows}
        self.assertEqual(by_id['0']['event_role'],'PRIMARY')
        self.assertEqual(by_id['1']['event_role'],'DUPLICATE')
        self.assertEqual(by_id['2']['event_role'],'DUPLICATE')
        self.assertEqual(by_id['3']['event_role'],'DUPLICATE')
        self.assertEqual(by_id['4']['event_role'],'PRIMARY')
        self.assertEqual(len({r['event_id'] for r in rows}),2)

    def test_event_assignment_separates_gap_greater_than_two_hours(self):
        rows=[]
        for i,minutes in enumerate((0,121)):
            ts=datetime(2026,1,1,tzinfo=timezone.utc).timestamp()+minutes*60
            rows.append({'id':str(i),'timestamp':datetime.fromtimestamp(ts,tz=timezone.utc).isoformat(),'symbol':'ETHUSDT','provider':'Bitget','direction':'SHORT','event_id':'','event_role':''})
        _assign_events(rows)
        self.assertEqual([r['event_role'] for r in rows],['PRIMARY','PRIMARY'])
        self.assertEqual(len({r['event_id'] for r in rows}),2)

    def test_different_symbols_and_directions_are_independent(self):
        rows=[]
        for i,(sym,side) in enumerate((('A','SHORT'),('B','SHORT'),('A','LONG'))):
            ts=datetime(2026,1,1,12,i,tzinfo=timezone.utc).isoformat()
            rows.append({'id':str(i),'timestamp':ts,'symbol':sym,'provider':'Bitget','direction':side,'event_id':'','event_role':''})
        _assign_events(rows)
        self.assertEqual(len({r['event_id'] for r in rows}),3)

    def test_different_providers_are_independent_events(self):
        rows=[]
        for i,provider in enumerate(('Bitget','Binance')):
            ts=datetime(2026,1,1,12,tzinfo=timezone.utc).isoformat()
            rows.append({'id':str(i),'timestamp':ts,'symbol':'UAIUSDT','provider':provider,'direction':'SHORT','event_id':'','event_role':''})
        _assign_events(rows)
        self.assertEqual([r['event_role'] for r in rows],['PRIMARY','PRIMARY'])
        self.assertEqual(len({r['event_id'] for r in rows}),2)
        self.assertTrue(all('UAIUSDT' in r['event_id'] and r['provider'] in r['event_id'] for r in rows))

    def test_event_stats_do_not_double_count_horizons(self):
        rows=[
            {'event_id':'E1','event_role':'PRIMARY','h1':'','h4':'','h12':'EXPANSION','h24':'EXPANSION'},
            {'event_id':'E1','event_role':'DUPLICATE','h1':'FAIL','h4':'FAIL','h12':'FAIL','h24':'FAIL'},
            {'event_id':'E2','event_role':'PRIMARY','h1':'','h4':'FAIL','h12':'FAIL','h24':'FAIL'},
            {'event_id':'E3','event_role':'PRIMARY','h1':'','h4':'','h12':'','h24':''},
        ]
        s=summarize(rows)
        self.assertEqual(s['raw_signals'],4)
        self.assertEqual(s['independent_events'],3)
        self.assertEqual(s['resolved_events'],2)
        self.assertEqual(s['unresolved_events'],1)
        self.assertEqual(s['event_outcomes'],{'EXPANSION':1,'FAIL':1,'AMBIGUOUS':0})
        self.assertEqual(s['horizon_outcomes']['h12']['EXPANSION'],1)
        self.assertEqual(s['horizon_outcomes']['h24']['EXPANSION'],1)


class ExtremeMarketDataTests(unittest.TestCase):
    def _rows(self, mode):
        rows=[]
        for i in range(192):
            if mode=='low': p=200-i*.45 if i<188 else 115+(i-188)*.3
            elif mode=='mid': p=150+((i%40)-20)*.2
            else: p=100+i*.45 if i<188 else 185-(i-188)*.3
            rows.append([i,p,p+1,p-1,p,100])
        return rows

    def test_low_market_features(self):
        rows=self._rows('low'); f=build_features(rows,rows[-1][4])
        self.assertTrue(f['data_ok']); self.assertLess(f['h1_pos_24'],.30); self.assertLess(f['dist_low_atr'],1.0); self.assertGreaterEqual(f['dist_low_atr'],0); self.assertIn('price',f); self.assertIn('atr_pct',f); self.assertEqual(f['atr_basis'],'1H')

    def test_mid_market_features(self):
        rows=self._rows('mid'); f=build_features(rows,150)
        self.assertTrue(.25<f['h1_pos_24']<.75)

    def test_high_market_features(self):
        rows=self._rows('high'); f=build_features(rows,rows[-1][4])
        self.assertTrue(f['data_ok']); self.assertGreater(f['h1_pos_24'],.70); self.assertLess(f['dist_high_atr'],1.0); self.assertGreaterEqual(f['dist_high_atr'],0)

    def test_live_price_outside_closed_range_does_not_create_negative_distance(self):
        rows=self._rows('low')
        f=build_features(rows,rows[-1][4]-100)
        self.assertGreaterEqual(f['dist_low_atr'],0)
        self.assertGreaterEqual(f['dist_high_atr'],0)
        self.assertEqual(f['price'],rows[-1][4])


if __name__=='__main__': unittest.main(verbosity=2)

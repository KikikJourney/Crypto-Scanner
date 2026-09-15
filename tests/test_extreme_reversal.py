import unittest

from extreme_reversal_layer import classify
from extreme_market_data import build_features


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

    def test_missing_data_blocked(self):
        self.assertEqual(classify({'data_ok':False})['status'],'DATA-LIMITED')


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
        f=build_features(self._rows('low'),self._rows('low')[-1][4])
        self.assertTrue(f['data_ok']); self.assertLess(f['h1_pos_24'],.30); self.assertLess(f['dist_low_atr'],1.0)

    def test_mid_market_features(self):
        rows=self._rows('mid'); f=build_features(rows,150)
        self.assertTrue(.25<f['h1_pos_24']<.75)

    def test_high_market_features(self):
        rows=self._rows('high'); f=build_features(rows,rows[-1][4])
        self.assertTrue(f['data_ok']); self.assertGreater(f['h1_pos_24'],.70); self.assertLess(f['dist_high_atr'],1.0)


if __name__=='__main__': unittest.main(verbosity=2)

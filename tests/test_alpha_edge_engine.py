import unittest
from alpha_edge_engine import pullback_calibration, regime

def bar(o,h,l,c,v=100):
    return {"o":o,"h":h,"l":l,"c":c,"v":v}

class EdgeEngineTests(unittest.TestCase):
    def test_pullback_returns_directional_zone(self):
        rows=[]
        p=100.0
        for i in range(80):
            p += 0.20
            rows.append(bar(p-0.1,p+0.4,p-0.2,p,100+i))
        rows += [
            bar(p,p+4,p-0.2,p+3,500),
            bar(p+3,p+3.2,p+1.0,p+1.8,180),
            bar(p+1.8,p+2.2,p+1.2,p+1.9,150),
        ]
        pb=pullback_calibration(rows,"LONG")
        self.assertIsNotNone(pb)
        self.assertLess(pb["zone_low"],pb["zone_high"])

    def test_regime_has_required_measurements(self):
        rows=[bar(100+i,101+i,99+i,100.5+i,100+i) for i in range(80)]
        r=regime(rows)
        for key in ("type","atr_pct","volume_ratio","ema_drift_pct"):
            self.assertIn(key,r)

if __name__=="__main__":
    unittest.main()

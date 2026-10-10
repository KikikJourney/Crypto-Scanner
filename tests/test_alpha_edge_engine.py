import unittest
from alpha_edge_engine import crowding_score, live_entry_timing, pullback_calibration, regime

def bar(o,h,l,c,v=100):
    return {"o":o,"h":h,"l":l,"c":c,"v":v}

class EdgeEngineTests(unittest.TestCase):
    def test_crowding_score_handles_zero_or_missing_ratio(self):
        self.assertEqual(crowding_score(0, "SHORT"), 0.5)
        self.assertEqual(crowding_score(None, "LONG"), 0.5)
        self.assertGreaterEqual(crowding_score(1.2, "LONG"), 0.0)
        self.assertLessEqual(crowding_score(1.2, "LONG"), 1.0)

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

    def test_short_pullback_calibration_returns_displacement(self):
        rows=[]
        p=100.0
        for i in range(80):
            p -= 0.20
            rows.append(bar(p+0.1,p+0.4,p-0.2,p,100+i))
        rows += [
            bar(p,p+0.2,p-4.0,p-3.0,500),
            bar(p-3.0,p-1.0,p-3.2,p-1.8,180),
            bar(p-1.8,p-1.2,p-2.2,p-1.9,150),
        ]
        pb=pullback_calibration(rows,"SHORT")
        self.assertIsNotNone(pb)
        self.assertIn("disp", pb)

    def test_live_entry_timing_rejects_price_outside_calibrated_zone(self):
        timing = live_entry_timing(99.0, 100.0, 102.0, 101.0, 1.0, "LONG")
        self.assertFalse(timing["ready"])
        self.assertIn("passed entry zone", timing["reason"])

    def test_live_entry_timing_accepts_price_inside_calibrated_zone(self):
        timing = live_entry_timing(101.0, 100.0, 102.0, 101.0, 1.0, "LONG")
        self.assertTrue(timing["ready"])
        self.assertEqual(timing["timing"], 100.0)

    def test_live_entry_timing_accepts_reachable_pending_long_limit(self):
        timing = live_entry_timing(103.0, 100.0, 102.0, 101.0, 1.0, "LONG")
        self.assertTrue(timing["ready"])
        self.assertEqual(timing["reason"], "pending limit zone remains reachable")

    def test_live_entry_timing_accepts_reachable_pending_short_limit(self):
        timing = live_entry_timing(99.0, 100.0, 102.0, 101.0, 1.0, "SHORT")
        self.assertTrue(timing["ready"])
        self.assertEqual(timing["reason"], "pending limit zone remains reachable")

    def test_live_entry_timing_rejects_price_that_has_passed_zone(self):
        self.assertFalse(live_entry_timing(99.0, 100.0, 102.0, 101.0, 1.0, "LONG")["ready"])
        self.assertFalse(live_entry_timing(103.0, 100.0, 102.0, 101.0, 1.0, "SHORT")["ready"])

    def test_live_entry_timing_rejects_invalid_inputs(self):
        timing = live_entry_timing(0.0, 100.0, 102.0, 101.0, 1.0, "LONG")
        self.assertFalse(timing["ready"])

    def test_regime_has_required_measurements(self):
        rows=[bar(100+i,101+i,99+i,100.5+i,100+i) for i in range(80)]
        r=regime(rows)
        for key in ("type","atr_pct","volume_ratio","ema_drift_pct"):
            self.assertIn(key,r)

if __name__=="__main__":
    unittest.main()

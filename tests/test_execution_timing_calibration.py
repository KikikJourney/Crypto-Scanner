import unittest
from execution_timing_calibration import calibrate

class TimingCalibrationTests(unittest.TestCase):
    def candle(self, ts, close, high, low):
        from datetime import datetime, timedelta
        d=datetime.fromisoformat(ts.replace("Z","+00:00"))
        return {"timestamp":ts,"close_timestamp":(d+timedelta(minutes=5)).isoformat(),"symbol":"TESTUSDT","provider":"Bitget","high":str(high),"low":str(low),"close":str(close)}
    def test_later_timing_is_evaluated_after_early_adverse_touch(self):
        action={"id":"a","timestamp":"2026-09-27T00:00:00+00:00","symbol":"TESTUSDT","provider":"Bitget","direction":"LONG","strategy_version":"scalp-structure-v1","entry":"100","stop":"99","target":"102"}
        market=[
          self.candle("2026-09-27T00:05:00+00:00",99.5,100.1,99.0),
          self.candle("2026-09-27T00:10:00+00:00",100.5,100.6,100.2),
          self.candle("2026-09-27T00:15:00+00:00",101.0,101.1,100.4),
          self.candle("2026-09-27T00:20:00+00:00",102.1,102.2,100.8)]
        rows=calibrate([action],market)
        by={int(r["offset_bars"]):r for r in rows}
        self.assertEqual(by[0]["status"],"SKIPPED")
        self.assertEqual(by[1]["outcome"], "EXPANSION")
if __name__=="__main__": unittest.main()

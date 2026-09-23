import unittest
import execution_adverse_timing as et

class ExecutionAdverseTimingTests(unittest.TestCase):
    def candle(self, ts, close, high, low):
        from datetime import datetime, timedelta
        opened=datetime.fromisoformat(ts.replace("Z","+00:00"))
        return {"timestamp":ts,"close_timestamp":(opened+timedelta(minutes=5)).isoformat(),"symbol":"TESTUSDT","provider":"Bitget","high":str(high),"low":str(low),"close":str(close)}

    def test_adverse_before_favorable_is_detected(self):
        action={"timestamp":"2026-09-22T00:00:00+00:00","symbol":"TESTUSDT","provider":"Bitget","direction":"LONG","entry":"100","stop":"99","first_touch":"FAIL"}
        result=et.write([action],[self.candle("2026-09-22T00:05:00+00:00",99.5,100.1,99),self.candle("2026-09-22T00:10:00+00:00",101,101,99.5)],"/tmp/timing.csv")[0]
        self.assertEqual(result["adverse_1r_before_favorable_0_5r"],1)

    def test_favorable_before_adverse_is_detected(self):
        action={"timestamp":"2026-09-22T00:00:00+00:00","symbol":"TESTUSDT","provider":"Bitget","direction":"LONG","entry":"100","stop":"99","first_touch":"EXPANSION"}
        result=et.write([action],[self.candle("2026-09-22T00:05:00+00:00",100.5,100.5,100),self.candle("2026-09-22T00:10:00+00:00",101,101,99.5)],"/tmp/timing.csv")[0]
        self.assertEqual(result["favorable_0_5r_before_adverse_1r"],1)

if __name__=="__main__": unittest.main()

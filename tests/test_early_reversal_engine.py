import unittest
from early_reversal_engine import evaluate_setup

def rows(prices, volume=100):
    return [[i * 900, str(p), str(p + 1), str(p - 1), str(p), str(volume)] for i,p in enumerate(prices)]
def rows_ohlc(prices, volume=100):
    return [[i * 300, str(o), str(h), str(l), str(c), str(volume)] for i,(o,h,l,c) in enumerate(prices)]

class T(unittest.TestCase):
    def test_long(self):
        prices15=[110.0-i*0.45 for i in range(36)]+[94.2,94.1,94.25,94.15]
        candles=[(94.2,94.5,93.9,94.1)]*19
        candles[-1]=(94.0,94.9,93.5,94.7)
        s=evaluate_setup(rows(prices15),rows_ohlc(candles),"LONG")
        self.assertTrue(s["eligible"], s)
        self.assertEqual(s["location_15m"],1.0)

if __name__=="__main__":unittest.main(verbosity=2)

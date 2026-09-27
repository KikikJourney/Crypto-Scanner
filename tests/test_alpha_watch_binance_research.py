import unittest
from unittest.mock import patch
from alpha_watch_binance_research import _aggregate_15m, _outcome

class AlphaWatchBinanceResearchTests(unittest.TestCase):
    def test_aggregate_15m_uses_three_closed_5m_bars(self):
        rows = [
            [0, "", 10, 9, 9.5, 1],
            [300000, "", 11, 9.4, 10.5, 2],
            [600000, "", 12, 10, 11.5, 3],
            [900000, "", 13, 11, 12.5, 4],
            [1200000, "", 14, 12, 13.5, 5],
            [1500000, "", 15, 13, 14.5, 6],
        ]
        out = _aggregate_15m(rows)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0][2:6], [12, 9, 11.5, 6])
        self.assertEqual(out[1][2:6], [15, 11, 14.5, 15])

    def test_long_touch_then_tp_is_win(self):
        future = [
            [0, "", 101, 99, 100, 1],
            [300000, "", 103, 100, 102, 1],
        ]
        result = _outcome("LONG", 100, 98, 102, future)
        self.assertEqual(result[-1], "WIN")
        self.assertEqual(result[0], 0)

    def test_same_candle_tp_and_sl_is_ambiguous(self):
        future = [[0, "", 103, 97, 100, 1]]
        result = _outcome("LONG", 100, 98, 102, future)
        self.assertEqual(result[-1], "AMBIGUOUS")

if __name__ == "__main__":
    unittest.main()

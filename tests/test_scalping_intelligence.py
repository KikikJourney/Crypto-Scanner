import unittest
from datetime import datetime, timezone
from extreme_runner import _normalize_bitget_mtf_candles
from scalping_intelligence import (
    aggregate, build_plan, infer_direction, _timestamp,
    _location_score, _reversal_score,
)


def rows(prices, volume=100):
    return [[i * 900, str(p), str(p + 1), str(p - 1), str(p), str(volume)]
            for i, p in enumerate(prices)]


def rows_ohlc(prices, volume=100):
    return [[i * 300, str(o), str(h), str(l), str(c), str(volume)]
            for i, (o, h, l, c) in enumerate(prices)]


def prices_to_rows(prices, volume=100):
    return rows(prices, volume)


class ScalpingIntelligenceTests(unittest.TestCase):
    def test_timestamp_parses_milliseconds(self):
        self.assertIsNotNone(_timestamp([1758196500000]))

    def test_bitget_mtf_normalization_sorts_oldest_first_and_drops_open_candle(self):
        interval_ms = 15 * 60 * 1000
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        current_start = (now_ms // interval_ms) * interval_ms
        base_ms = current_start - 194 * interval_ms
        data = [[str(base_ms + i * interval_ms), "100", "101", "99", "100", "10"]
                for i in range(194)]
        data.append([str(base_ms + 194 * interval_ms), "100", "101", "99", "100", "10"])
        normalized = _normalize_bitget_mtf_candles(data, 15, limit=194)
        self.assertEqual(len(normalized), 194)
        self.assertEqual(int(normalized[0][0]), base_ms)
        self.assertEqual(int(normalized[-1][0]), current_start - interval_ms)

    def test_aggregate(self):
        out = aggregate(rows([100, 101, 102, 103]), 2)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0][4], 101.0)
        self.assertEqual(out[1][4], 103.0)

    def test_requires_mtf_history(self):
        plan = build_plan("LONG", rows(list(range(100, 150))), rows(list(range(100, 150))),
                          80, {"extreme_low_24": 90, "extreme_high_24": 160, "atr": 2})
        self.assertEqual(plan["status"], "DATA-LIMITED")

    def test_infer_direction_requires_mtf_alignment(self):
        prices15 = [100 + i * 0.05 for i in range(194)]
        prices5 = [105 + i * 0.01 for i in range(194)]
        self.assertEqual(infer_direction(rows(prices15), rows(prices5)), "LONG")

    def test_location_blocks_long_at_top_of_range(self):
        self.assertEqual(_location_score(rows([100 + i * 0.15 for i in range(32)]), "LONG"), 0.0)

    def test_location_blocks_short_at_bottom_of_range(self):
        self.assertEqual(_location_score(rows([110 - i * 0.15 for i in range(32)]), "SHORT"), 0.0)

    def test_location_accepts_long_in_lower_range(self):
        prices = [100 + i * 0.05 for i in range(31)] + [100.2]
        self.assertGreaterEqual(_location_score(rows(prices), "LONG"), 0.5)

    def test_reversal_detects_long_sweep(self):
        candles = [(100, 101, 99, 100)] * 8
        candles[-1] = (99.8, 100.8, 98.5, 100.5)
        self.assertEqual(_reversal_score(rows_ohlc(candles), "LONG"), 1.0)

    def test_reversal_detects_short_sweep(self):
        candles = [(100, 101, 99, 100)] * 8
        candles[-1] = (100.2, 101.5, 99.2, 99.5)
        self.assertEqual(_reversal_score(rows_ohlc(candles), "SHORT"), 1.0)

    def test_max_stop_distance_returns_wait(self):
        # Keep 15m price in the lower range so the location gate passes.
        prices15 = [100.0] * 194
        prices5 = [103.5 + i * 0.005 for i in range(194)]
        prices5[-7:-1] = [100, 100.2, 100.1, 100.3, 100.0, 100.2]
        plan = build_plan("LONG", prices_to_rows(prices15, 120),
                          prices_to_rows(prices5, 180), 88,
                          {"extreme_low_24": 50, "extreme_high_24": 110, "atr": 1.0})
        self.assertEqual(plan["status"], "WAIT")
        self.assertGreater(plan["risk_pct"], 2.0)
        self.assertEqual(plan["max_stop_distance_pct"], 2.0)
        self.assertEqual(plan["reason"], "execution stop distance exceeds scalping limit")


if __name__ == "__main__":
    unittest.main(verbosity=2)

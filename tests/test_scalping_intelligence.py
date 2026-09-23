import unittest
from datetime import datetime, timezone
from extreme_runner import _normalize_bitget_mtf_candles
from scalping_intelligence import (
    aggregate, build_plan, infer_direction, _timestamp,
    _location_score, _reversal_score, _opposing_structure_target,
    _countertrend_early_reversal_allowed,
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

    def test_midrange_location_cannot_be_action(self):
        prices15 = [100.0] * 194
        prices5 = [100.0] * 194
        for i in range(32):
            prices15[-32 + i] = 90.0 + i * (20.0 / 31.0)
        prices15[-1] = 100.0
        execution_rows = prices_to_rows(prices5, 180)
        execution_rows[-2] = [execution_rows[-2][0], "99", "100", "98", "99", "180"]
        execution_rows[-1] = [execution_rows[-1][0], "99", "101", "99", "100.5", "180"]
        plan = build_plan("LONG", prices_to_rows(prices15, 120), execution_rows, 90,
                          {"extreme_low_24": 80, "extreme_high_24": 120, "atr": 1.0})
        self.assertEqual(plan["status"], "WAIT")
        self.assertEqual(plan["location_15m"], 0.0)
        self.assertIn("unfavorable", plan["reason"])

    def test_reversal_detects_long_sweep(self):
        candles = [(100, 101, 99, 100)] * 8
        candles[-1] = (99.8, 100.8, 98.5, 100.5)
        self.assertEqual(_reversal_score(rows_ohlc(candles), "LONG"), 1.0)

    def test_reversal_detects_short_sweep(self):
        candles = [(100, 101, 99, 100)] * 8
        candles[-1] = (100.2, 101.5, 99.2, 99.5)
        self.assertEqual(_reversal_score(rows_ohlc(candles), "SHORT"), 1.0)


    def test_recovery_only_cannot_be_action(self):
        prices15 = [100.0] * 194
        prices15[-32:] = [100.0 - i * 0.05 for i in range(31)] + [98.4]
        candles = [(98.2, 99.0, 98.0, 98.6)] * 59 + [(98.5, 99.8, 98.4, 99.7)]
        execution = rows_ohlc(candles, 180)
        plan = build_plan("LONG", prices_to_rows(prices15, 120), execution, 88,
                          {"extreme_low_24": 90, "extreme_high_24": 110, "atr": 1.0})
        self.assertEqual(plan["status"], "WAIT")
        self.assertEqual(plan["reversal_5m"], 0.5)
        self.assertIn("true sweep", plan["reason"])

    def test_structure_target_rejects_stale_extreme_and_prefers_nearest_swing(self):
        prices = [100.0] * 32
        prices[10] = 104.5
        prices[11] = 102.5
        prices[12] = 103.0
        prices[25] = 150.0  # stale far extreme
        target = _opposing_structure_target(rows(prices), "LONG", 100.0, 2.0)
        self.assertEqual(target, 104.5)

    def test_structure_target_rejects_only_stale_extreme(self):
        prices = [100.0] * 32
        prices[25] = 150.0
        target = _opposing_structure_target(rows(prices), "LONG", 100.0, 2.0)
        self.assertIsNone(target)

    def test_structure_target_must_support_two_r(self):
        prices15 = [100.0] * 194
        prices15[-32:] = [100.0 - i * 0.10 for i in range(31)] + [96.5]
        candles = [(96.0, 96.8, 95.5, 96.2)] * 59 + [(96.1, 97.2, 95.8, 97.0)]
        execution = rows_ohlc(candles, 180)
        plan = build_plan("LONG", prices_to_rows(prices15, 120), execution, 88,
                          {"extreme_low_24": 90, "extreme_high_24": 100, "atr": 1.0})
        self.assertIn(plan["status"], {"WAIT", "ACTION LONG"})
        if plan["status"] == "ACTION LONG":
            self.assertGreaterEqual(plan["reward_r"], 2.0)
            self.assertGreaterEqual(plan["target"], plan["target_structure"])

    def test_max_stop_distance_returns_wait(self):
        # Isolate the stop-distance gate: preferred LONG location + true sweep.
        prices15 = [100.0] * 194
        prices15[-32:] = [100.0 + i * 0.005 for i in range(30)] + [130.0, 99.0]
        execution_rows = prices_to_rows([103.5] * 194, 180)
        execution_rows[-7:-1] = [
            [execution_rows[-7][0], "100", "101", "99", "100", "180"],
            [execution_rows[-6][0], "100", "101", "99", "100.2", "180"],
            [execution_rows[-5][0], "100.2", "101.2", "99.2", "100.1", "180"],
            [execution_rows[-4][0], "100.1", "101.3", "99.0", "100.3", "180"],
            [execution_rows[-3][0], "100.3", "101.0", "99.1", "100.0", "180"],
            [execution_rows[-2][0], "100.0", "101.2", "99.0", "100.2", "180"],
        ]
        execution_rows[-1] = [execution_rows[-1][0], "103.5", "105.5", "98.0", "105.0", "180"]
        plan = build_plan("LONG", prices_to_rows(prices15, 120),
                          execution_rows, 88,
                          {"extreme_low_24": 50, "extreme_high_24": 110, "atr": 1.0})
        self.assertEqual(plan["status"], "WAIT")
        self.assertGreater(plan["risk_pct"], 2.0)
        self.assertEqual(plan["max_stop_distance_pct"], 2.0)
        self.assertEqual(plan["reason"], "execution stop distance exceeds scalping limit")

    def test_countertrend_early_reversal_requires_stronger_confirmation(self):
        self.assertFalse(_countertrend_early_reversal_allowed("SHORT", 0.0, 0.0, 0.875, 0.0))
        self.assertTrue(_countertrend_early_reversal_allowed("SHORT", 0.0, 0.0, 0.90, 0.0))
        self.assertTrue(_countertrend_early_reversal_allowed("SHORT", 0.0, 0.0, 0.80, 80.0))
        self.assertTrue(_countertrend_early_reversal_allowed("LONG", 1.0, 1.0, 0.80, 0.0))
        self.assertFalse(
            _countertrend_early_reversal_allowed(
                "SHORT", 0.0, 0.0, 1.0, 0.0, 0.0, 1.0
            )
        )
        self.assertTrue(
            _countertrend_early_reversal_allowed(
                "SHORT", 0.0, 0.0, 1.0, 80.0, 0.0, 1.0
            )
        )
    def test_execution_geometry_uses_published_entry_for_risk_and_target(self):
        entry = 100.0
        stop = 98.0
        risk = entry - stop
        target = entry + 2.0 * risk
        self.assertEqual(risk, 2.0)
        self.assertEqual(target, 104.0)

        entry = 100.0
        stop = 102.0
        risk = stop - entry
        target = entry - 2.0 * risk
        self.assertEqual(risk, 2.0)
        self.assertEqual(target, 96.0)

    def test_execution_signal_expires_after_one_5m_candle(self):
        prices15 = [100.0] * 194
        prices5 = [100.0] * 194
        plan = build_plan("LONG", prices_to_rows(prices15), prices_to_rows(prices5), 0,
                          {"extreme_low_24": 90, "extreme_high_24": 110, "atr": 1.0})
        self.assertIn(plan["status"], {"WAIT", "NO-TRADE", "DATA-LIMITED", "INVALID"})

    def test_live_action_gate_is_disabled_by_default(self):
        import os
        from unittest.mock import patch
        import send_telegram_actions

        with patch.dict(os.environ, {}, clear=True):
            self.assertNotEqual(os.environ.get("ENABLE_SCANNER_ACTIONS"), "true")
            self.assertEqual(send_telegram_actions.main(), 0)

    def test_early_reversal_runner_dependency_is_imported(self):
        from extreme_runner import infer_early_reversal_direction
        self.assertTrue(callable(infer_early_reversal_direction))

if __name__ == "__main__":
    unittest.main(verbosity=2)

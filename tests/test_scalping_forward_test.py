import unittest
from unittest import mock
import scalping_forward_test as ft


def action(ts="2026-09-20T10:00:00+00:00", direction="LONG"):
    return {
        "id": f"A-{direction}-{ts}", "timestamp": ts, "symbol": "TESTUSDT",
        "provider": "Bitget", "direction": direction, "strategy_version": ft.CURRENT_STRATEGY_VERSION, "entry": "100",
        "stop": "99", "target": "102",
    }


def candle(ts, high, low):
    return {"id": f"C-{ts}", "timestamp": ts, "symbol": "TESTUSDT",
            "provider": "Bitget", "open": "100", "high": str(high),
            "low": str(low), "close": "100"}


class ScalpingForwardTest(unittest.TestCase):
    def test_overlapping_open_candle_is_excluded(self):
        act = action("2026-09-20T10:25:21+00:00")
        market = [
            candle("2026-09-20T10:25:00+00:00", 110, 90),
            candle("2026-09-20T10:30:00+00:00", 101, 100),
        ]
        rows = ft.evaluate([act], market)
        self.assertEqual(rows[0]["first_touch"], "")
        self.assertEqual(rows[0]["mfe_pct"], 1.0)
        self.assertEqual(rows[0]["mae_pct"], 0.0)

    def test_archive_actions_deduplicates_same_setup_within_window(self):
        first = action("2026-09-20T10:00:00+00:00")
        duplicate = action("2026-09-20T10:10:00+00:00")
        with mock.patch.object(ft, "_migrate_history"),              mock.patch.object(ft, "_load", return_value=[first]):
            self.assertEqual(ft.archive_actions([duplicate]), 0)


    def test_pending_action_refresh_selects_recent_symbols(self):
        actions = [action("2026-09-20T10:00:00+00:00")]
        calls = []

        def fake_fetch(symbol, provider, start_ms, end_ms):
            calls.append((symbol, provider, start_ms, end_ms))
            return [["2026-09-20T10:05:00+00:00", "100", "101", "99", "100", "100"]]

        with mock.patch.object(ft, "_load", return_value=actions),              unittest.mock.patch.object(ft, "_migrate_history"),              unittest.mock.patch.object(ft, "archive_market_candles", return_value=1):
            result = ft.archive_pending_action_candles(
                fake_fetch,
                now=ft._ts("2026-09-20T10:30:00+00:00"),
                per_symbol=32,
            )

        self.assertEqual(result, 1)
        self.assertEqual(calls, [(
            "TESTUSDT", "Bitget",
            int(ft._ts("2026-09-20T10:00:00+00:00").timestamp() * 1000),
            int(ft._ts("2026-09-20T10:30:00+00:00").timestamp() * 1000),
        )])


    def test_pending_action_refresh_handles_naive_provider_timestamp(self):
        actions = [action("2026-09-20T10:00:00+00:00")]

        def fake_fetch(symbol, provider, start_ms, end_ms):
            return [["2026-09-20T10:05:00", "100", "101", "99.5", "100", "100"]]

        with mock.patch.object(ft, "_load", return_value=actions), mock.patch.object(ft, "_migrate_history"), mock.patch.object(ft, "archive_market_candles", return_value=1):
            self.assertEqual(
                ft.archive_pending_action_candles(
                    fake_fetch,
                    now=ft._ts("2026-09-20T10:30:00+00:00"),
                    per_symbol=32,
                ),
                1,
            )

    def test_output_preserves_injected_fixture_strategy_version(self):
        result = ft.evaluate([action()], [
            candle("2026-09-20T10:05:00+00:00", 101, 99.5),
            candle("2026-09-20T10:10:00+00:00", 102.1, 100),
        ])
        self.assertEqual(result[0]["strategy_version"], ft.CURRENT_STRATEGY_VERSION)

    def test_first_touch_long_tp(self):
        self.assertEqual(ft._first_touch("LONG", 102.1, 99.5, 99, 102), "EXPANSION")
        self.assertEqual(ft._first_touch("LONG", 100.5, 98.9, 99, 102), "FAIL")

    def test_first_touch_short_tp(self):
        self.assertEqual(ft._first_touch("SHORT", 100.5, 97.9, 101, 98), "EXPANSION")
        self.assertEqual(ft._first_touch("SHORT", 102.1, 99.5, 101, 98), "FAIL")

    def test_same_candle_is_ambiguous(self):
        self.assertEqual(ft._first_touch("LONG", 102.5, 98.5, 99, 102), "AMBIGUOUS")

    def test_mfe_mae_long(self):
        mfe, mae = ft._metrics("LONG", 100, [candle("2026-09-20T10:05:00+00:00", 103, 98)])
        self.assertEqual(mfe, 3.0)
        self.assertEqual(mae, 2.0)

    def test_mfe_mae_stop_after_resolution_ignores_later_excursion(self):
        result = ft.evaluate([action()], [
            candle("2026-09-20T10:05:00+00:00", 100.5, 98.5),
            candle("2026-09-20T10:10:00+00:00", 103.0, 100.0),
        ])
        self.assertEqual(result[0]["first_touch"], "FAIL")
        self.assertEqual(result[0]["resolved_horizon"], "15")
        self.assertEqual(result[0]["mfe_pct"], 0.5)
        self.assertEqual(result[0]["mae_pct"], 1.5)

    def test_evaluate_uses_future_ohlc_and_first_touch(self):
        result = ft.evaluate([action()], [
            candle("2026-09-20T10:05:00+00:00", 101, 99.5),
            candle("2026-09-20T10:10:00+00:00", 102.1, 100),
        ])
        self.assertEqual(result[0]["h15"], "EXPANSION")
        self.assertEqual(result[0]["first_touch"], "EXPANSION")
        self.assertEqual(result[0]["first_touch_timestamp"], "2026-09-20T10:15:00+00:00")
        self.assertEqual(result[0]["resolved_horizon"], "15")
        self.assertEqual(result[0]["outcome_r"], "2.0")
        self.assertEqual(result[0]["mfe_pct"], 2.1)
        self.assertEqual(result[0]["mae_pct"], 0.5)

    def test_close_timestamp_controls_horizon_boundary(self):
        result = ft.evaluate([action()], [
            candle("2026-09-20T09:55:00+00:00", 102.5, 100),
            candle("2026-09-20T10:10:00+00:00", 102.1, 100),
        ])
        self.assertEqual(result[0]["h15"], "EXPANSION")
        self.assertEqual(result[0]["first_touch_timestamp"], "2026-09-20T10:15:00+00:00")

    def test_evaluate_ignores_candles_before_signal(self):
        result = ft.evaluate([action()], [
            candle("2026-09-20T09:55:00+00:00", 103, 98),
            candle("2026-09-20T10:05:00+00:00", 100.5, 99.5),
        ])
        self.assertEqual(result[0]["h15"], "")
        self.assertEqual(result[0]["first_touch"], "")


if __name__ == "__main__":
    unittest.main(verbosity=2)

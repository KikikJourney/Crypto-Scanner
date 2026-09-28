import unittest

from telegram_notifier import format_action
import send_telegram_actions as actions
from send_telegram_actions import _execution_status, _still_actionable


class TelegramNotifierTests(unittest.TestCase):
    def test_format_action_contains_explicit_geometry_prices(self):
        text = format_action({
            "direction": "LONG",
            "symbol": "RDDTUSDT",
            "entry": "157.98",
            "entry_low": "157.50",
            "entry_high": "158.46",
            "stop": "157.1901",
            "target": "162.7197",
            "risk_pct": "0.50",
            "reward_r": "6.0",
            "confidence": "86.5",
            "score": "72.2",
            "timeframes": "4H/1H/30m/15m/5m",
            "rsi_5m": "54.2",
            "liquidity_sweep_5m": "True",
            "volume_5m": "0.82",
            "margin_usdt": "10",
            "leverage": "20",
            "notional_usdt": "200",
            "stop_margin_pct": "10",
            "tp_margin_pct": "60",
            "max_loss_usdt": "1",
            "target_pnl_usdt": "6",
            "tp1": "160.3497",
            "tp2": "162.7197",
            "tp3": "167.4588",
            "tp1_pnl_usdt": "3",
            "tp2_pnl_usdt": "6",
            "tp3_pnl_usdt": "12",
            "target_price_move_pct": "3.0",
            "flow_conviction": "0.72",
            "valid_until": "2026-09-18T07:15:00+00:00",
        })
        self.assertIn("ZORATHVAEL SIGNAL LONG", text)
        self.assertIn("EXECUTION PRICES", text)
        self.assertIn("Entry (calibrated): 157.98", text)
        self.assertIn("Entry Zone: 157.5 - 158.46", text)
        self.assertIn("SL (10% margin): 157.1901", text)
        self.assertIn("TP1 (+30% margin): 160.3497", text)
        self.assertIn("TP2 (+60% margin): 162.7197", text)
        self.assertIn("TP3 (+120% margin): 167.4588", text)
        self.assertIn("Selected TP: 162.7197", text)
        self.assertIn("Margin: 10 USDT | Leverage: 20x", text)
        self.assertIn("SL Margin Risk: 10% (-1 USDT)", text)
        self.assertIn("TP1 PnL: +3 USDT | TP2: +6 USDT | TP3: +12 USDT", text)
        self.assertIn("Canonical geometry: Entry → SL -0.50% price / TP1 +1.50% / TP2 +3.00% / TP3 +6.00% at 20x.", text)
        self.assertNotIn("TP 2R:", text)
        self.assertNotIn("TP 4R:", text)
        self.assertNotIn("TP 6R:", text)
        self.assertNotIn("Modal/Entry:", text)
        self.assertNotIn("Estimasi Loss @ SL:", text)
        self.assertNotIn("EXECUTION PLAN", text)

    def test_live_window_accepts_long_inside_entry_zone_before_target(self):
        row = {
            "direction": "LONG",
            "entry": "105",
            "entry_low": "104",
            "entry_high": "107",
            "stop": "100",
            "target": "115",
        }
        self.assertTrue(_still_actionable(row, 106))

    def test_live_window_rejects_long_after_target_or_outside_entry_zone(self):
        row = {
            "direction": "LONG",
            "entry": "105",
            "entry_low": "104",
            "entry_high": "107",
            "stop": "100",
            "target": "115",
        }
        self.assertFalse(_still_actionable(row, 116))
        self.assertFalse(_still_actionable(row, 103))
        self.assertFalse(_still_actionable(row, 100))

    def test_live_window_accepts_short_inside_entry_zone_before_target(self):
        row = {
            "direction": "SHORT",
            "entry": "105",
            "entry_low": "103",
            "entry_high": "107",
            "stop": "115",
            "target": "95",
        }
        self.assertTrue(_still_actionable(row, 104))

    def test_live_window_rejects_short_after_target_or_outside_entry_zone(self):
        row = {
            "direction": "SHORT",
            "entry": "105",
            "entry_low": "103",
            "entry_high": "107",
            "stop": "115",
            "target": "95",
        }
        self.assertFalse(_still_actionable(row, 94))
        self.assertFalse(_still_actionable(row, 108))
        self.assertFalse(_still_actionable(row, 115))

    def test_execution_status_reports_wait_when_price_is_outside_zone(self):
        row = {
            "direction": "LONG",
            "entry": "105",
            "entry_low": "104",
            "entry_high": "107",
            "stop": "100",
            "target": "115",
        }
        self.assertEqual(_execution_status(row, 103), "WAIT — PRICE OUTSIDE ENTRY ZONE")

    def test_execution_status_reports_triggered_inside_zone(self):
        row = {
            "direction": "LONG",
            "entry": "105",
            "entry_low": "104",
            "entry_high": "107",
            "stop": "100",
            "target": "115",
        }
        self.assertEqual(_execution_status(row, 106), "TRIGGERED — PRICE IN ENTRY ZONE")

    def test_positive_oos_gate_rejects_negative_ci(self):
        original = actions.VALIDATION_REPORT
        try:
            from pathlib import Path
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                actions.VALIDATION_REPORT = Path(tmp) / "validation.csv"
                actions.VALIDATION_REPORT.write_text(
                    "evidence_status,sample_gate_pass,bootstrap_ci95_low,bootstrap_ci95_high\n"
                    "NEGATIVE_CI,True,-0.82,-0.42\n",
                    encoding="utf-8",
                )
                self.assertFalse(actions._positive_oos_gate())
        finally:
            actions.VALIDATION_REPORT = original

    def test_positive_oos_gate_accepts_only_positive_ci(self):
        original = actions.VALIDATION_REPORT
        try:
            from pathlib import Path
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                actions.VALIDATION_REPORT = Path(tmp) / "validation.csv"
                actions.VALIDATION_REPORT.write_text(
                    "evidence_status,sample_gate_pass,bootstrap_ci95_low,bootstrap_ci95_high\n"
                    "POSITIVE_CI,True,0.10,0.40\n",
                    encoding="utf-8",
                )
                self.assertTrue(actions._positive_oos_gate())
        finally:
            actions.VALIDATION_REPORT = original


if __name__ == "__main__":
    unittest.main(verbosity=2)

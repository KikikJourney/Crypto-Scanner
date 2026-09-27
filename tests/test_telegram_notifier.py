import unittest

from telegram_notifier import format_action
import send_telegram_actions as actions
from send_telegram_actions import _execution_status, _still_actionable


class TelegramNotifierTests(unittest.TestCase):
    def test_format_action_contains_mtf_trade_plan(self):
        text = format_action({
            "direction": "LONG",
            "symbol": "RDDTUSDT",
            "entry": "157.98",
            "entry_low": "157.50",
            "entry_high": "158.46",
            "stop": "155.51",
            "target": "162.90",
            "risk_pct": "1.55",
            "reward_r": "2.0",
            "confidence": "86.5",
            "score": "72.2",
            "timeframes": "4H/1H/30m/15m/5m",
            "rsi_5m": "54.2",
            "liquidity_sweep_5m": "True",
            "volume_5m": "0.82",
            "margin_usdt": "10",
            "leverage": "25",
            "notional_usdt": "250",
            "stop_margin_pct": "5",
            "tp_margin_pct": "77.78",
            "max_loss_usdt": "0.5",
            "target_pnl_usdt": "7.78",
            "tp1": "159.8756",
            "tp2": "161.7715",
            "tp3": "165.5629",
            "tp1_pnl_usdt": "3",
            "tp2_pnl_usdt": "6",
            "tp3_pnl_usdt": "12",
            "target_price_move_pct": "3.11",
            "flow_conviction": "0.72",
            "valid_until": "2026-09-18T07:15:00+00:00",
        })
        self.assertIn("ZORATHVAEL SIGNAL LONG", text)
        self.assertIn("Entry: 157.50 - 158.46", text)
        self.assertIn("SL: 155.51", text)
        self.assertIn("TP: 162.90", text)
        self.assertIn("RR Equivalent: 2.0", text)
        self.assertIn("Margin: 10 USDT | Leverage: 25x", text)
        self.assertIn("SL Margin Risk: 5% (-0.5 USDT)", text)
        self.assertIn("Selected TP: 162.90 (77.78% margin / +7.78 USDT)", text)
        self.assertIn("Confidence: 86.5/100", text)
        self.assertIn("Standard scanner model: 10 USDT margin / 25x leverage / max SL 5% / TP1 30% / TP2 60% / TP3 120%.", text)
        self.assertNotIn("TP 2R:", text)
        self.assertNotIn("TP 4R:", text)
        self.assertNotIn("TP 6R:", text)
        self.assertIn("RISK MODEL", text)
        self.assertNotIn("Modal/Entry:", text)
        self.assertIn("Leverage:", text)
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

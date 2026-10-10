import unittest
from telegram_signal_dedup import filter_new_signals, signal_fingerprint, signal_key


class TelegramSignalDedupTests(unittest.TestCase):
    def test_empty_result_has_no_fingerprint(self):
        self.assertEqual(signal_fingerprint([]), "none")

    def test_fingerprint_is_stable_for_minor_price_noise(self):
        a = [{"symbol_full": "STRKUSDT", "direction": "LONG", "entry": 0.072146}]
        b = [{"symbol_full": "STRKUSDT", "direction": "LONG", "entry": 0.072149}]
        self.assertEqual(signal_fingerprint(a), signal_fingerprint(b))

    def test_filter_new_signals_suppresses_previous_rows_when_batch_changes(self):
        old = [{"symbol_full": "ETHUSDT", "direction": "LONG", "entry": 2493.0}]
        new = old + [{"symbol_full": "KORUUSDT", "direction": "LONG", "entry": 0.142}]
        pending, updated = filter_new_signals(new, {signal_key(old[0])})
        self.assertEqual([row["symbol_full"] for row in pending], ["KORUUSDT"])
        self.assertIn(signal_key(old[0]), updated)
        self.assertEqual(len(updated), 2)

    def test_direction_or_symbol_change_changes_fingerprint(self):
        a = [{"symbol_full": "STRKUSDT", "direction": "LONG", "entry": 0.0721}]
        b = [{"symbol_full": "STRKUSDT", "direction": "SHORT", "entry": 0.0721}]
        c = [{"symbol_full": "ETHUSDT", "direction": "LONG", "entry": 2493.0}]
        self.assertNotEqual(signal_fingerprint(a), signal_fingerprint(b))
        self.assertNotEqual(signal_fingerprint(a), signal_fingerprint(c))


if __name__ == "__main__":
    unittest.main()

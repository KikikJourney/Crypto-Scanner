import unittest
from telegram_signal_dedup import signal_fingerprint


class TelegramSignalDedupTests(unittest.TestCase):
    def test_empty_result_has_no_fingerprint(self):
        self.assertEqual(signal_fingerprint([]), "none")

    def test_fingerprint_is_stable_for_minor_price_noise(self):
        a = [{"symbol_full": "STRKUSDT", "direction": "LONG", "entry": 0.072146}]
        b = [{"symbol_full": "STRKUSDT", "direction": "LONG", "entry": 0.072149}]
        self.assertEqual(signal_fingerprint(a), signal_fingerprint(b))

    def test_direction_or_symbol_change_changes_fingerprint(self):
        a = [{"symbol_full": "STRKUSDT", "direction": "LONG", "entry": 0.0721}]
        b = [{"symbol_full": "STRKUSDT", "direction": "SHORT", "entry": 0.0721}]
        c = [{"symbol_full": "ETHUSDT", "direction": "LONG", "entry": 2493.0}]
        self.assertNotEqual(signal_fingerprint(a), signal_fingerprint(b))
        self.assertNotEqual(signal_fingerprint(a), signal_fingerprint(c))


if __name__ == "__main__":
    unittest.main()

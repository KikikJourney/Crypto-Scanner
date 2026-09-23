import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from extreme_archive_integrity import validate, sanitize


class ExtremeArchiveIntegrityTests(unittest.TestCase):
    def test_rejects_bad_timestamp_duplicate_and_unknown_symbol(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "snapshots.csv"
            path.write_text(
                "id,timestamp,symbol,provider,price\n"
                "a,not-a-date,BTCUSDT,Bitget,100\n"
                "a,2026-09-23T10:00:00Z,FAKEUSDT,Bitget,100\n",
                encoding="utf-8",
            )
            result = validate(
                path,
                now=datetime(2026, 9, 23, 11, 0, tzinfo=timezone.utc),
                universe={"BTCUSDT"},
                require_price=True,
            )
            self.assertFalse(result["valid"])
            self.assertGreaterEqual(len(result["errors"]), 3)

    def test_sanitize_preserves_valid_rows_and_returns_rejected_rows(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "snapshots.csv"
            path.write_text(
                "id,timestamp,symbol,provider,price\n"
                "good,2026-09-23T10:00:00Z,BTCUSDT,Bitget,100\n"
                "bad,garbage,BTCUSDT,Bitget,100\n",
                encoding="utf-8",
            )
            kept, rejected = sanitize(
                path,
                now=datetime(2026, 9, 23, 11, 0, tzinfo=timezone.utc),
                universe={"BTCUSDT"},
                require_price=True,
            )
            self.assertEqual(len(kept), 1)
            self.assertEqual(len(rejected), 1)
            result = validate(
                path,
                now=datetime(2026, 9, 23, 11, 0, tzinfo=timezone.utc),
                universe={"BTCUSDT"},
                require_price=True,
            )
            self.assertTrue(result["valid"])


if __name__ == "__main__":
    unittest.main()

import csv
import os
import tempfile
from pathlib import Path

SIGNAL_FILE = Path("data/forward_test.csv")
CSV_FIELDS = [
    "id", "timestamp", "symbol", "provider", "price", "score", "bias", "signal", "change24h",
    "m1", "m6", "m24", "volume_ratio", "atr_pct", "taker_100", "taker_250", "taker_500",
    "taker_ratio", "taker_spread_pct", "taker_stability", "taker_fills", "book_ratio", "funding", "entry_low",
    "entry_high", "sl", "position_idr", "tp1", "tp2", "tp3", "stop_pct", "btc24", "btc6",
    "h1", "h4", "h12", "h24"
]

def clean_row(row):
    old_taker = row.get("taker_ratio", "")
    clean = {key: row.get(key, "") for key in CSV_FIELDS}
    if not clean["taker_100"] and old_taker:
        clean["taker_100"] = old_taker
    return clean

def sanitize():
    if not SIGNAL_FILE.exists():
        return False
    with SIGNAL_FILE.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = [clean_row(row) for row in reader]
        header = reader.fieldnames or []
    if header == CSV_FIELDS and all(None not in row for row in rows):
        return False
    SIGNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="forward_test.", suffix=".csv", dir=SIGNAL_FILE.parent)
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_name, SIGNAL_FILE)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise
    print(f"Sanitized {SIGNAL_FILE}: {len(rows)} rows; schema normalized to {len(CSV_FIELDS)} fields")
    return True

if __name__ == "__main__":
    sanitize()

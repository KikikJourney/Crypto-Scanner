"""Stable fingerprints for suppressing duplicate Telegram signal batches."""
import hashlib


def signal_fingerprint(results):
    if not results:
        return "none"
    rows = []
    for item in results:
        symbol = str(item.get("symbol_full") or item.get("symbol") or "").upper()
        direction = str(item.get("direction") or "").upper()
        try:
            entry = format(float(item.get("entry")), ".3g")
        except (TypeError, ValueError):
            entry = "invalid"
        if symbol and direction:
            rows.append(f"{symbol}:{direction}:{entry}")
    if not rows:
        return "none"
    payload = "|".join(sorted(set(rows))).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:24]

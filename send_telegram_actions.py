"""Send only currently valid MTF scalping actions to Telegram."""
import csv
from datetime import datetime, timezone
from pathlib import Path

import scanner_v2 as core
from telegram_notifier import format_action, send_message

ACTIONS = Path("data/actionable_signals.csv")
STATE = Path("data/telegram_sent_actions.csv")
STATE_FIELDS = ["id"]


def _live_price(row):
    provider = row.get("provider", "")
    symbol = row.get("symbol", "")
    if not provider or not symbol:
        return None
    try:
        if provider == "Binance":
            return float(core.binance("/fapi/v1/ticker/price", {"symbol": symbol})["price"])
        if provider == "Bybit":
            data = core.bybit("/v5/market/tickers", {"category": "linear", "symbol": symbol})
            return float(data["result"]["list"][0]["lastPrice"])
        if provider == "Bitget":
            data = core.bitget(
                "/api/v2/mix/market/ticker",
                {"symbol": symbol, "productType": "USDT-FUTURES"},
            )
            return float(data["data"][0]["lastPr"])
    except (KeyError, IndexError, TypeError, ValueError, RuntimeError):
        return None
    return None


def _valid_until(row):
    value = row.get("valid_until", "")
    if not value:
        return True
    try:
        expiry = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) <= expiry
    except ValueError:
        return False


def _still_actionable(row, live_price):
    if live_price is None or not _valid_until(row):
        return False
    try:
        price = float(live_price)
        low = float(row.get("entry_low", row["entry"]))
        high = float(row.get("entry_high", row["entry"]))
        stop = float(row["stop"])
        target = float(row["target"])
    except (KeyError, TypeError, ValueError):
        return False

    if row.get("direction") == "LONG":
        return low <= price <= high and price > stop and price < target
    if row.get("direction") == "SHORT":
        return low <= price <= high and price < stop and price > target
    return False


def main():
    if not ACTIONS.exists():
        print("TELEGRAM: no actionable signal file")
        return 0

    with ACTIONS.open(newline="", encoding="utf-8") as f:
        actions = list(csv.DictReader(f))

    STATE.parent.mkdir(parents=True, exist_ok=True)
    sent = set()
    if STATE.exists():
        with STATE.open(newline="", encoding="utf-8") as f:
            sent = {r["id"] for r in csv.DictReader(f) if r.get("id")}

    pending = [row for row in actions if row.get("id") and row["id"] not in sent]
    token = __import__("os").environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = __import__("os").environ.get("TELEGRAM_CHAT_ID")

    if not pending:
        print("TELEGRAM: no new confirmed MTF scalping actions")
    elif not token or not chat_id:
        print(f"TELEGRAM: {len(pending)} action(s) pending; credentials not configured")
        return 0
    else:
        for row in pending:
            live = _live_price(row)
            if not _still_actionable(row, live):
                print(
                    f"TELEGRAM SKIP: {row.get('symbol','?')} {row.get('direction','?')} "
                    f"outside entry/validity window (price={live})"
                )
                continue
            ok, detail = send_message(format_action(row), token, chat_id)
            if not ok:
                raise RuntimeError(f"Telegram send failed for {row['id']}: {detail}")
            sent.add(row["id"])
            print(
                f"TELEGRAM SENT: {row['symbol']} {row['direction']} "
                f"entry={row.get('entry_low')}-{row.get('entry_high')} live={live}"
            )

    with STATE.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=STATE_FIELDS)
        writer.writeheader()
        for value in sorted(sent):
            writer.writerow({"id": value})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Telegram notifier for confirmed multi-timeframe scalping actions."""
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _valid_now(row):
    value = row.get("valid_until")
    if not value:
        return True
    try:
        expiry = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) <= expiry
    except ValueError:
        return False


def format_action(row):
    direction = row.get("direction", "")
    entry_low = row.get("entry_low") or row.get("entry") or row.get("trigger", "")
    entry_high = row.get("entry_high") or row.get("entry") or row.get("trigger", "")
    return (
        f"🚨 ZORATHVAEL SCALPING {direction}\n"
        f"Symbol: {row.get('symbol', '')}\n"
        f"Confidence: {row.get('confidence', '')}/100\n"
        f"Entry zone: {entry_low} - {entry_high}\n"
        f"Stop: {row.get('stop', '')}\n"
        f"Target: {row.get('target', '')}\n"
        f"RR: {row.get('reward_r', '')}\n"
        f"Risk: {row.get('risk_pct', '')}%\n"
        f"MTF: {row.get('timeframes', '4H/1H/30m/15m/5m')}\n"
        f"5m RSI: {row.get('rsi_5m', '')}\n"
        f"Liquidity sweep: {row.get('liquidity_sweep_5m', '')}\n"
        f"5m volume score: {row.get('volume_5m', '')}\n"
        f"Valid until: {row.get('valid_until', '')}\n"
        f"V2.2 score: {row.get('score', '')}\n\n"
        "Execution rule: only enter while the live price remains inside the entry zone "
        "and before the validity window expires."
    )


def send_message(text, token=None, chat_id=None):
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False, "Telegram credentials not configured"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    request = urllib.request.Request(url, data=payload, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = json.loads(response.read().decode())
        if body.get("ok") is not True:
            return False, str(body)
        return True, "sent"
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return False, f"HTTP {exc.code}: {body or exc.reason}"
    except Exception as exc:
        return False, str(exc)


if __name__ == "__main__":
    print("Telegram notifier module loaded")

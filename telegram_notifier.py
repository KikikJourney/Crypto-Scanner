"""Minimal Telegram Bot API notifier for scanner action alerts.

Uses only the Python standard library. Secrets are supplied by GitHub Actions;
this module never stores credentials in the repository.
"""
import json
import os
import urllib.parse
import urllib.request


def format_action(row):
    direction = row.get('direction', '')
    return (
        f"🚨 ZORATHVAEL ACTION {direction}\n"
        f"Symbol: {row.get('symbol', '')}\n"
        f"Entry: {row.get('trigger', '')}\n"
        f"Stop: {row.get('stop', '')}\n"
        f"Target: {row.get('target', '')}\n"
        f"Risk: {row.get('risk_pct', '')}%\n"
        f"Extreme score: {row.get('score', '')}\n"
        f"Time: {row.get('timestamp', '')}\n\n"
        "Rule: entry is confirmed only after the structure trigger is reached."
    )


def send_message(text, token=None, chat_id=None):
    token = token or os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = chat_id or os.environ.get('TELEGRAM_CHAT_ID')
    if not token or not chat_id:
        return False, 'Telegram credentials not configured'
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({'chat_id': chat_id, 'text': text}).encode()
    req = urllib.request.Request(url, data=payload, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            body = json.loads(response.read().decode())
        if body.get('ok') is not True:
            return False, str(body)
        return True, 'sent'
    except Exception as exc:
        return False, str(exc)


if __name__ == '__main__':
    print('Telegram notifier module loaded')

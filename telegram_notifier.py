"""Unified Telegram notifier for all scanner signal types."""
import json
import math
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

def _risk_levels(row):
    """Return structural R levels without prescribing capital or leverage."""
    entry = _float(row.get("entry_low") or row.get("entry") or row.get("trigger"))
    stop = _float(row.get("stop"))
    if entry is None or stop is None or entry <= 0:
        return None
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    direction = row.get("direction")
    if direction == "LONG":
        levels = {f"{r}R": entry + r * risk for r in (2, 4, 6)}
    elif direction == "SHORT":
        levels = {f"{r}R": entry - r * risk for r in (2, 4, 6)}
    else:
        return None
    return {"entry": entry, "risk_distance": risk, "levels": levels}


def format_action(row):
    direction = row.get("direction", "")
    entry_low = row.get("entry_low") or row.get("entry") or row.get("trigger", "")
    entry_high = row.get("entry_high") or row.get("entry") or row.get("trigger", "")
    levels = _risk_levels(row)

    lines = [
        f"🚨 ZORATHVAEL SIGNAL {direction}",
        f"Symbol: {row.get('symbol', '')}",
        f"Confidence: {row.get('confidence', '')}/100",
        f"Entry: {entry_low} - {entry_high}",
        f"SL: {row.get('stop', '')}",
        f"Margin: {row.get('margin_usdt', '')} USDT | Leverage: {row.get('leverage', '')}x",
        f"Notional: {row.get('notional_usdt', '')} USDT",
    ]

    if levels:
        lines.extend([
            f"TP 2R: {levels['levels']['2R']:.12g}",
            f"TP 4R: {levels['levels']['4R']:.12g}",
            f"TP 6R: {levels['levels']['6R']:.12g}",
            f"Signal TP: {row.get('target', '')}",
            f"RR: {row.get('reward_r', '')}",
            f"SL Distance: {levels['risk_distance']:.12g}",
            f"SL Margin Risk: {row.get('stop_margin_pct', '')}% (-{row.get('max_loss_usdt', '')} USDT)",
            f"TP Margin ROI: {row.get('tp_margin_pct', '')}% (+{row.get('target_pnl_usdt', '')} USDT)",
        ])
    else:
        lines.extend([
            f"TP: {row.get('target', '')}",
            f"RR: {row.get('reward_r', '')}",
        ])

    lines.extend([
        "",
        "RISK MODEL",
        "SL budget: maximum 5% of margin. TP target: 40%-100% of margin ROI.",
        "Default scanner model: 10 USDT margin / 10x leverage; price levels are derived from these limits.",
        "",
        f"Strategy: {row.get('strategy', row.get('signal_type', ''))}",
        f"MTF: {row.get('timeframes', '4H/1H/30m/15m/5m')}",
        f"5m RSI: {row.get('rsi_5m', '')}",
        f"Liquidity sweep: {row.get('liquidity_sweep_5m', '')}",
        f"5m volume score: {row.get('volume_5m', '')}",
        f"Valid until: {row.get('valid_until', '')}",
        f"Score: {row.get('score', '')}",
        "",
        "Execution rule: only enter while live price remains inside the Entry zone and before the validity window expires.",
        "Flow inputs may include liquidity sweep, volume, whale/order-flow and liquidation context; missing external flow data is treated conservatively.",
    ])
    return "\n".join(lines)

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

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

def format_action(row):
    direction = row.get("direction", "")
    entry_low = row.get("entry_low") or row.get("entry") or row.get("trigger", "")
    entry_high = row.get("entry_high") or row.get("entry") or row.get("trigger", "")

    lines = [
        f"🚨 ZORATHVAEL SIGNAL {direction}",
        f"Symbol: {row.get('symbol', '')}",
        f"Confidence: {row.get('confidence', '')}/100",
        f"Entry: {entry_low} - {entry_high}",
        f"SL: {row.get('stop', '')}",
        f"TP: {row.get('target', '')}",
        f"Margin: {row.get('margin_usdt', '')} USDT | Leverage: {row.get('leverage', '')}x",
        f"Notional: {row.get('notional_usdt', '')} USDT",
        f"SL Margin Risk: {row.get('stop_margin_pct', '')}% (-{row.get('max_loss_usdt', '')} USDT)",
        f"TP1: {row.get('tp1', '')} (+30% margin / +{row.get('tp1_pnl_usdt', '')} USDT)",
        f"TP2: {row.get('tp2', '')} (+60% margin / +{row.get('tp2_pnl_usdt', '')} USDT)",
        f"TP3: {row.get('tp3', '')} (+120% margin / +{row.get('tp3_pnl_usdt', '')} USDT)",
        f"Selected TP: {row.get('target', '')} ({row.get('tp_margin_pct', '')}% margin / +{row.get('target_pnl_usdt', '')} USDT)",
        f"Target Price Move: {row.get('target_price_move_pct', '')}%",
        f"RR Equivalent: {row.get('reward_r', '')}",
        "",
        "RISK MODEL",
        "SL budget: maximum 10% of margin. TP ladder: 30% / 60% / 120% of margin ROI.",
        "Canonical geometry: 10 USDT margin / 20x leverage / SL -10% / TP1 +30% / TP2 +60% / TP3 +120% of margin.",
        "Flow inputs may include liquidity sweep, volume, whale/order-flow and liquidation context; missing external flow data is treated conservatively.",
        "",
        f"Strategy: {row.get('strategy', row.get('signal_type', ''))}",
        f"MTF: {row.get('timeframes', '4H/1H/30m/15m/5m')}",
        f"5m RSI: {row.get('rsi_5m', '')}",
        f"Liquidity sweep: {row.get('liquidity_sweep_5m', '')}",
        f"5m volume score: {row.get('volume_5m', '')}",
        f"Flow conviction: {row.get('flow_conviction', '')}",
        f"Timing calibration: {row.get('calibration_inputs', '100x5m + volume/flow/regime')}",
        f"Timing score: {row.get('timing_score', '')} | Volume regime: {row.get('volume_regime', '')}",
        f"100c anchor: {row.get('entry_anchor_100', '')} | Buffer ATR: {row.get('entry_buffer_atr', '')}",
        f"Valid until: {row.get('valid_until', '')}",
        f"Score: {row.get('score', '')}",
        "",
        "Execution rule: only enter while live price remains inside the Entry zone and before the validity window expires.",
    ]
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

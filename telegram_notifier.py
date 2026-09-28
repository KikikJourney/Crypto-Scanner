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


def _fmt_price(value):
    """Format an absolute market price without hiding small-price precision."""
    number = _float(value)
    if number is None:
        return str(value or "")
    if number == 0:
        return "0"
    if abs(number) >= 1000:
        decimals = 2
    elif abs(number) >= 1:
        decimals = 4
    elif abs(number) >= 0.01:
        decimals = 6
    elif abs(number) >= 0.0001:
        decimals = 8
    else:
        decimals = 10
    return f"{number:.{decimals}f}".rstrip("0").rstrip(".")


def format_action(row):
    direction = row.get("direction", "")
    entry = row.get("entry") or row.get("trigger", "")
    entry_low = row.get("entry_low") or entry
    entry_high = row.get("entry_high") or entry

    # Entry is the single calibrated execution price used by the canonical
    # geometry. The optional zone is displayed separately so it cannot be
    # mistaken for the geometry's actual entry.
    lines = [
        f"🚨 ZORATHVAEL SIGNAL {direction}",
        f"Symbol: {row.get('symbol', '')}",
        f"Confidence: {row.get('confidence', '')}/100",
        "",
        "EXECUTION PRICES",
        f"Entry (calibrated): {_fmt_price(entry)}",
        f"Entry Zone: {_fmt_price(entry_low)} - {_fmt_price(entry_high)}",
        f"SL (10% margin): {_fmt_price(row.get('stop', ''))}",
        f"TP1 (+30% margin): {_fmt_price(row.get('tp1', ''))}",
        f"TP2 (+60% margin): {_fmt_price(row.get('tp2', ''))}",
        f"TP3 (+120% margin): {_fmt_price(row.get('tp3', ''))}",
        f"Selected TP: {_fmt_price(row.get('target', ''))}",
        "",
        "MARGIN / GEOMETRY",
        f"Margin: {row.get('margin_usdt', '')} USDT | Leverage: {row.get('leverage', '')}x",
        f"Notional: {row.get('notional_usdt', '')} USDT",
        f"SL Margin Risk: {row.get('stop_margin_pct', '')}% (-{row.get('max_loss_usdt', '')} USDT)",
        f"TP1 PnL: +{row.get('tp1_pnl_usdt', '')} USDT | TP2: +{row.get('tp2_pnl_usdt', '')} USDT | TP3: +{row.get('tp3_pnl_usdt', '')} USDT",
        f"Selected TP PnL: +{row.get('target_pnl_usdt', '')} USDT",
        f"Target Price Move: {row.get('target_price_move_pct', '')}%",
        f"RR Equivalent: {row.get('reward_r', '')}",
        "Canonical geometry: Entry → SL -0.50% price / TP1 +1.50% / TP2 +3.00% / TP3 +6.00% at 20x.",
        "",
        "TIMING / MARKET CONTEXT",
        f"Strategy: {row.get('strategy', row.get('signal_type', ''))}",
        f"MTF: {row.get('timeframes', '4H/1H/30m/15m/5m')}",
        f"5m RSI: {row.get('rsi_5m', '')}",
        f"Liquidity sweep: {row.get('liquidity_sweep_5m', '')}",
        f"5m volume score: {row.get('volume_5m', '')}",
        f"Flow conviction: {row.get('flow_conviction', '')}",
        f"Timing calibration: {row.get('calibration_inputs', '40c timing / 100c reference + volume/flow/regime')}",
        f"Timing score: {row.get('timing_score', '')} | Volume regime: {row.get('volume_regime', '')}",
        f"100c anchor: {_fmt_price(row.get('entry_anchor_100', ''))} | Buffer ATR: {row.get('entry_buffer_atr', '')}",
        f"Valid until: {row.get('valid_until', '')}",
        f"Score: {row.get('score', '')}",
        "",
        "Execution rule: use the calibrated Entry price as the geometry origin. Enter only while live price remains inside the Entry Zone and before validity expires.",
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

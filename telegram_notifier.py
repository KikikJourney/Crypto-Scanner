"""Telegram notifier for confirmed multi-timeframe scalping actions."""
import json
import math
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# Fixed per-signal margin requested for the Telegram execution plan.
MARGIN_USDT = 5.0

# Keep the stop-loss cash exposure small relative to the fixed margin.
# This is a sizing rule for the notification only; it does NOT place orders.
MAX_STOP_LOSS_USDT = 0.50
MAX_LEVERAGE = 20


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


def _execution_plan(row):
    """Calculate a fixed-margin, stop-risk-based leverage plan.

    The leverage is derived from the distance between the reference entry and
    stop so that the estimated loss at SL is <= MAX_STOP_LOSS_USDT, subject to
    exchange-compatible integer leverage and a hard cap. This is sizing math
    for the Telegram message only; it never authorizes or places an order.
    """
    entry_low = _float(row.get("entry_low") or row.get("entry") or row.get("trigger"))
    entry_high = _float(row.get("entry_high") or row.get("entry") or row.get("trigger"))
    stop = _float(row.get("stop"))
    target = _float(row.get("target"))

    if entry_low is None or entry_high is None or stop is None or target is None:
        return None

    entry = (entry_low + entry_high) / 2.0
    if entry <= 0:
        return None

    stop_distance_pct = abs(entry - stop) / entry
    if stop_distance_pct <= 0:
        return None

    # Integer leverage, rounded down, keeps estimated SL loss at or below
    # the configured cash-risk ceiling.
    raw_leverage = MAX_STOP_LOSS_USDT / (MARGIN_USDT * stop_distance_pct)
    leverage = max(1, min(MAX_LEVERAGE, math.floor(raw_leverage)))

    notional = MARGIN_USDT * leverage
    position_qty = notional / entry
    estimated_sl_loss = notional * stop_distance_pct

    if row.get("direction") == "LONG":
        reward_distance = target - entry
    elif row.get("direction") == "SHORT":
        reward_distance = entry - target
    else:
        reward_distance = 0.0

    rr = reward_distance / abs(entry - stop) if reward_distance > 0 else None

    return {
        "entry": entry,
        "stop_distance_pct": stop_distance_pct * 100.0,
        "leverage": leverage,
        "margin_usdt": MARGIN_USDT,
        "notional_usdt": notional,
        "position_qty": position_qty,
        "estimated_sl_loss_usdt": estimated_sl_loss,
        "rr": rr,
    }


def format_action(row):
    direction = row.get("direction", "")
    entry_low = row.get("entry_low") or row.get("entry") or row.get("trigger", "")
    entry_high = row.get("entry_high") or row.get("entry") or row.get("trigger", "")
    plan = _execution_plan(row)

    lines = [
        f"🚨 ZORATHVAEL SCALPING {direction}",
        f"Symbol: {row.get('symbol', '')}",
        f"Confidence: {row.get('confidence', '')}/100",
        f"Entry zone: {entry_low} - {entry_high}",
        f"Stop: {row.get('stop', '')}",
        f"Target: {row.get('target', '')}",
        f"RR: {row.get('reward_r', '')}",
        f"Risk: {row.get('risk_pct', '')}%",
    ]

    if plan:
        lines.extend([
            "",
            "💰 EXECUTION PLAN",
            f"Margin: {plan['margin_usdt']:.2f} USDT",
            f"Leverage: {plan['leverage']}x",
            f"Reference entry: {plan['entry']:.12g}",
            f"Position notional: {plan['notional_usdt']:.2f} USDT",
            f"Position size: {plan['position_qty']:.8g} {row.get('symbol', '').replace('USDT', '')}",
            f"Estimated SL loss: {plan['estimated_sl_loss_usdt']:.2f} USDT",
            f"Entry→SL distance: {plan['stop_distance_pct']:.3f}%",
            f"Calculated RR: {plan['rr']:.2f}R" if plan["rr"] is not None else "Calculated RR: N/A",
        ])
    else:
        lines.extend([
            "",
            "💰 EXECUTION PLAN: UNAVAILABLE — invalid entry/SL/TP data",
        ])

    lines.extend([
        "",
        f"MTF: {row.get('timeframes', '4H/1H/30m/15m/5m')}",
        f"5m RSI: {row.get('rsi_5m', '')}",
        f"Liquidity sweep: {row.get('liquidity_sweep_5m', '')}",
        f"5m volume score: {row.get('volume_5m', '')}",
        f"Valid until: {row.get('valid_until', '')}",
        f"V2.2 score: {row.get('score', '')}",
        "",
        "Sizing note: fixed 5 USDT margin; leverage is derived from SL distance "
        "to target <= 0.50 USDT estimated loss at SL. Fees, funding, slippage, "
        "and liquidation mechanics are not included.",
        "Execution rule: only enter while the live price remains inside the entry zone "
        "and before the validity window expires.",
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

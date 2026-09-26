"""Unified Telegram notifier for all scanner signal types."""
import json
import math
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# Fixed per-signal margin for the Telegram execution plan.
MARGIN_USDT = 5.0

# Notification sizing rule only; it does NOT place orders.
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
    """Calculate fixed-margin leverage from the signal's actual SL distance."""
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

    raw_leverage = MAX_STOP_LOSS_USDT / (MARGIN_USDT * stop_distance_pct)

    # If even 1x exceeds the configured cash-risk ceiling, do not fabricate
    # a safe leverage value. The signal is explicitly marked too risky.
    if raw_leverage < 1:
        return {
            "entry": entry,
            "stop_distance_pct": stop_distance_pct * 100.0,
            "leverage": None,
            "margin_usdt": MARGIN_USDT,
            "notional_usdt": None,
            "position_qty": None,
            "estimated_sl_loss_usdt": None,
            "rr": None,
            "risk_too_high": True,
        }

    leverage = min(MAX_LEVERAGE, math.floor(raw_leverage))
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
        "risk_too_high": False,
    }


def format_action(row):
    direction = row.get("direction", "")
    entry_low = row.get("entry_low") or row.get("entry") or row.get("trigger", "")
    entry_high = row.get("entry_high") or row.get("entry") or row.get("trigger", "")
    plan = _execution_plan(row)

    lines = [
        f"🚨 ZORATHVAEL SIGNAL {direction}",
        f"Symbol: {row.get('symbol', '')}",
        f"Confidence: {row.get('confidence', '')}/100",
        f"Entry: {entry_low} - {entry_high}",
        f"SL: {row.get('stop', '')}",
        f"TP: {row.get('target', '')}",
        f"RR: {row.get('reward_r', '')}",
        f"Risk: {row.get('risk_pct', '')}%",
        "",
        "💰 EXECUTION PLAN",
    ]

    if plan and not plan["risk_too_high"]:
        lines.extend([
            f"Modal/Entry: {plan['margin_usdt']:.2f} USDT",
            f"Leverage: {plan['leverage']}x",
            f"Reference Entry: {plan['entry']:.12g}",
            f"Notional: {plan['notional_usdt']:.2f} USDT",
            f"Position Size: {plan['position_qty']:.8g} {row.get('symbol', '').replace('USDT', '')}",
            f"Estimasi Loss @ SL: {plan['estimated_sl_loss_usdt']:.2f} USDT",
            f"Jarak Entry→SL: {plan['stop_distance_pct']:.3f}%",
            f"Calculated RR: {plan['rr']:.2f}R" if plan["rr"] is not None else "Calculated RR: N/A",
        ])
    elif plan and plan["risk_too_high"]:
        lines.extend([
            f"Modal/Entry: {plan['margin_usdt']:.2f} USDT",
            "Leverage: TIDAK AMAN @ 5 USDT",
            f"Jarak Entry→SL: {plan['stop_distance_pct']:.3f}%",
            "Status: SKIP — 1x leverage saja melebihi batas loss 0.50 USDT.",
        ])
    else:
        lines.append("Status: UNAVAILABLE — invalid Entry/SL/TP data")

    lines.extend([
        "",
        f"Strategy: {row.get('strategy', row.get('signal_type', ''))}",
        f"MTF: {row.get('timeframes', '4H/1H/30m/15m/5m')}",
        f"5m RSI: {row.get('rsi_5m', '')}",
        f"Liquidity sweep: {row.get('liquidity_sweep_5m', '')}",
        f"5m volume score: {row.get('volume_5m', '')}",
        f"Valid until: {row.get('valid_until', '')}",
        f"Score: {row.get('score', '')}",
        "",
        "Sizing: fixed 5 USDT margin; leverage is derived from actual Entry→SL distance, capped at 20x and targeted to <= 0.50 USDT estimated SL loss.",
        "Fees, funding, slippage, and liquidation mechanics are not included. Notification sizing only; no order is placed by this module.",
        "Execution rule: only enter while live price remains inside the Entry zone and before the validity window expires.",
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

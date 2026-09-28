"""Margin-based futures risk model.

Risk is expressed in account-margin terms and converted to explicit price
levels. The production TP envelope is 2R..8R when SL uses the 10% margin-loss
budget; the standard ladder is 3R/6R/8R.
"""
from math import isfinite

DEFAULT_MARGIN_USDT = 10.0
DEFAULT_LEVERAGE = 20.0
MAX_MARGIN_LOSS_PCT = 10.0
TP1_MARGIN_PCT = 30.0
TP2_MARGIN_PCT = 60.0
TP3_MARGIN_PCT = 80.0
MIN_MARGIN_TP_PCT = 20.0
MAX_MARGIN_TP_PCT = 80.0


def _positive(value, name):
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be numeric")
    if not isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def price_move_pct_from_margin_pct(margin_pct, leverage):
    leverage = _positive(leverage, "leverage")
    return float(margin_pct) / leverage


def margin_pnl_usdt(margin_usdt, margin_pct):
    return _positive(margin_usdt, "margin_usdt") * float(margin_pct) / 100.0


def build_margin_plan(direction, entry, margin_usdt=DEFAULT_MARGIN_USDT,
                      leverage=DEFAULT_LEVERAGE,
                      stop_margin_pct=MAX_MARGIN_LOSS_PCT,
                      tp_margin_pct=TP1_MARGIN_PCT):
    if direction not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG or SHORT")
    entry = _positive(entry, "entry")
    margin_usdt = _positive(margin_usdt, "margin_usdt")
    leverage = _positive(leverage, "leverage")
    stop_margin_pct = float(stop_margin_pct)
    tp_margin_pct = float(tp_margin_pct)

    if stop_margin_pct <= 0 or stop_margin_pct > MAX_MARGIN_LOSS_PCT:
        raise ValueError("stop_margin_pct must be > 0 and <= 10%")
    if not MIN_MARGIN_TP_PCT <= tp_margin_pct <= MAX_MARGIN_TP_PCT:
        raise ValueError("tp_margin_pct must be between 20% and 80%")

    stop_move_pct = price_move_pct_from_margin_pct(stop_margin_pct, leverage)
    tp_move_pct = price_move_pct_from_margin_pct(tp_margin_pct, leverage)
    stop_delta = entry * stop_move_pct / 100.0
    tp_delta = entry * tp_move_pct / 100.0
    stop = entry - stop_delta if direction == "LONG" else entry + stop_delta
    target = entry + tp_delta if direction == "LONG" else entry - tp_delta

    return {
        "margin_usdt": margin_usdt, "leverage": leverage,
        "notional_usdt": margin_usdt * leverage,
        "stop_margin_pct": stop_margin_pct, "tp_margin_pct": tp_margin_pct,
        "max_loss_usdt": margin_pnl_usdt(margin_usdt, stop_margin_pct),
        "target_pnl_usdt": margin_pnl_usdt(margin_usdt, tp_margin_pct),
        "stop_price_move_pct": stop_move_pct, "target_price_move_pct": tp_move_pct,
        "entry": entry, "stop": stop, "target": target,
        "tp1_margin_pct": TP1_MARGIN_PCT, "tp2_margin_pct": TP2_MARGIN_PCT,
        "tp3_margin_pct": TP3_MARGIN_PCT,
        "tp1_pnl_usdt": margin_pnl_usdt(margin_usdt, TP1_MARGIN_PCT),
        "tp2_pnl_usdt": margin_pnl_usdt(margin_usdt, TP2_MARGIN_PCT),
        "tp3_pnl_usdt": margin_pnl_usdt(margin_usdt, TP3_MARGIN_PCT),
        "tp1_price_move_pct": price_move_pct_from_margin_pct(TP1_MARGIN_PCT, leverage),
        "tp2_price_move_pct": price_move_pct_from_margin_pct(TP2_MARGIN_PCT, leverage),
        "tp3_price_move_pct": price_move_pct_from_margin_pct(TP3_MARGIN_PCT, leverage),
        "tp1": entry + entry * price_move_pct_from_margin_pct(TP1_MARGIN_PCT, leverage) / 100.0 if direction == "LONG" else entry - entry * price_move_pct_from_margin_pct(TP1_MARGIN_PCT, leverage) / 100.0,
        "tp2": entry + entry * price_move_pct_from_margin_pct(TP2_MARGIN_PCT, leverage) / 100.0 if direction == "LONG" else entry - entry * price_move_pct_from_margin_pct(TP2_MARGIN_PCT, leverage) / 100.0,
        "tp3": entry + entry * price_move_pct_from_margin_pct(TP3_MARGIN_PCT, leverage) / 100.0 if direction == "LONG" else entry - entry * price_move_pct_from_margin_pct(TP3_MARGIN_PCT, leverage) / 100.0,
        "reward_to_r": tp_margin_pct / stop_margin_pct,
    }


def target_margin_pct_from_price(entry, target, direction, leverage):
    entry, target = _positive(entry, "entry"), _positive(target, "target")
    leverage = _positive(leverage, "leverage")
    if direction not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG or SHORT")
    move = ((target - entry) if direction == "LONG" else (entry - target)) / entry * 100.0
    return move * leverage


def stop_margin_pct_from_price(entry, stop, direction, leverage):
    entry, stop = _positive(entry, "entry"), _positive(stop, "stop")
    leverage = _positive(leverage, "leverage")
    if direction not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG or SHORT")
    move = ((entry - stop) if direction == "LONG" else (stop - entry)) / entry * 100.0
    return move * leverage


def clamp_tp_margin_pct(value):
    return max(MIN_MARGIN_TP_PCT, min(MAX_MARGIN_TP_PCT, float(value)))

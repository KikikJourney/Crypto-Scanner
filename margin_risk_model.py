"""Margin-based futures risk model.

The scanner expresses risk/reward in account-margin terms, then converts those
limits into price levels using leverage. This keeps Entry/SL/TP explicit while
avoiding the common mistake of treating ROI% as raw price movement.
"""

from math import isfinite


DEFAULT_MARGIN_USDT = 10.0
DEFAULT_LEVERAGE = 25.0
MAX_MARGIN_LOSS_PCT = 5.0
TP1_MARGIN_PCT = 30.0
TP2_MARGIN_PCT = 60.0
TP3_MARGIN_PCT = 120.0
MIN_MARGIN_TP_PCT = TP1_MARGIN_PCT
MAX_MARGIN_TP_PCT = TP3_MARGIN_PCT


def _positive(value, name):
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be numeric")
    if not isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def price_move_pct_from_margin_pct(margin_pct, leverage):
    """Convert margin PnL percentage into required underlying price movement."""
    leverage = _positive(leverage, "leverage")
    return float(margin_pct) / leverage


def margin_pnl_usdt(margin_usdt, margin_pct):
    return _positive(margin_usdt, "margin_usdt") * float(margin_pct) / 100.0


def build_margin_plan(
    direction,
    entry,
    margin_usdt=DEFAULT_MARGIN_USDT,
    leverage=DEFAULT_LEVERAGE,
    stop_margin_pct=MAX_MARGIN_LOSS_PCT,
    tp_margin_pct=TP1_MARGIN_PCT,
):
    """Build a price-level SL/TP from margin-risk percentages.

    SL is capped at 5% of margin by default. TP must be between 40% and 100%
    of margin. These percentages are PnL-on-margin percentages, not raw price
    percentages.
    """
    if direction not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG or SHORT")
    entry = _positive(entry, "entry")
    margin_usdt = _positive(margin_usdt, "margin_usdt")
    leverage = _positive(leverage, "leverage")
    stop_margin_pct = float(stop_margin_pct)
    tp_margin_pct = float(tp_margin_pct)

    if stop_margin_pct <= 0 or stop_margin_pct > MAX_MARGIN_LOSS_PCT:
        raise ValueError("stop_margin_pct must be > 0 and <= 5%")
    if not MIN_MARGIN_TP_PCT <= tp_margin_pct <= MAX_MARGIN_TP_PCT:
        raise ValueError("tp_margin_pct must be between 30% and 120%")

    stop_move_pct = price_move_pct_from_margin_pct(stop_margin_pct, leverage)
    tp_move_pct = price_move_pct_from_margin_pct(tp_margin_pct, leverage)
    stop_delta = entry * stop_move_pct / 100.0
    tp_delta = entry * tp_move_pct / 100.0

    if direction == "LONG":
        stop = entry - stop_delta
        target = entry + tp_delta
    else:
        stop = entry + stop_delta
        target = entry - tp_delta

    return {
        "margin_usdt": margin_usdt,
        "leverage": leverage,
        "notional_usdt": margin_usdt * leverage,
        "stop_margin_pct": stop_margin_pct,
        "tp_margin_pct": tp_margin_pct,
        "max_loss_usdt": margin_pnl_usdt(margin_usdt, stop_margin_pct),
        "target_pnl_usdt": margin_pnl_usdt(margin_usdt, tp_margin_pct),
        "stop_price_move_pct": stop_move_pct,
        "target_price_move_pct": tp_move_pct,
        "entry": entry,
        "stop": stop,
        "target": target,
        "tp1_margin_pct": TP1_MARGIN_PCT,
        "tp2_margin_pct": TP2_MARGIN_PCT,
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
    """Return TP ROI% on margin for a concrete price target."""
    entry = _positive(entry, "entry")
    target = _positive(target, "target")
    leverage = _positive(leverage, "leverage")
    if direction == "LONG":
        move = (target - entry) / entry * 100.0
    elif direction == "SHORT":
        move = (entry - target) / entry * 100.0
    else:
        raise ValueError("direction must be LONG or SHORT")
    return move * leverage


def stop_margin_pct_from_price(entry, stop, direction, leverage):
    """Return loss% on margin for a concrete stop price."""
    entry = _positive(entry, "entry")
    stop = _positive(stop, "stop")
    leverage = _positive(leverage, "leverage")
    if direction == "LONG":
        move = (entry - stop) / entry * 100.0
    elif direction == "SHORT":
        move = (stop - entry) / entry * 100.0
    else:
        raise ValueError("direction must be LONG or SHORT")
    return move * leverage


def clamp_tp_margin_pct(value):
    return max(MIN_MARGIN_TP_PCT, min(MAX_MARGIN_TP_PCT, float(value)))

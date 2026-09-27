"""Entry calibration layer.

This module answers only: WHERE/WHEN should the scanner attempt execution?
It deliberately does not calculate stop-loss or take-profit geometry.

The production anchor is the 100 fully closed 5m candle extreme. ATR is used
only to place a bounded execution buffer around that anchor.
"""

LOOKBACK_CANDLES = 100
ENTRY_BUFFER_ATR = 0.25
ENTRY_BUFFER_FLOOR_PCT = 0.03


def _f(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _close(row):
    return _f(row[4])


def _low(row):
    return _f(row[3])


def _high(row):
    return _f(row[2])


def calibrate_entry(rows_5m, direction, micro_atr):
    """Return calibrated entry location without producing SL/TP.

    Output fields describe entry timing/location only:
    anchor, current_price, entry, buffer, distance_atr.
    """
    if direction not in {"LONG", "SHORT"}:
        return None
    if len(rows_5m) < LOOKBACK_CANDLES or micro_atr is None or micro_atr <= 0:
        return None

    window = rows_5m[-LOOKBACK_CANDLES:]
    lows = [_low(row) for row in window]
    highs = [_high(row) for row in window]
    if any(value is None or value <= 0 for value in lows + highs):
        return None

    current_price = _close(rows_5m[-1])
    if current_price is None or current_price <= 0:
        return None

    anchor = min(lows) if direction == "LONG" else max(highs)
    buffer = max(micro_atr * ENTRY_BUFFER_ATR, current_price * ENTRY_BUFFER_FLOOR_PCT / 100.0)
    entry = anchor + buffer if direction == "LONG" else anchor - buffer
    distance_atr = abs(current_price - entry) / micro_atr

    return {
        "anchor": anchor,
        "buffer": buffer,
        "entry": entry,
        "current_price": current_price,
        "distance_atr": distance_atr,
        "lookback_candles": LOOKBACK_CANDLES,
    }

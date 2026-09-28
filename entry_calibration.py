"""Entry calibration layer.

This module answers only: WHERE/WHEN should the scanner attempt execution?
It deliberately does not calculate stop-loss or take-profit geometry.

The 40-candle extreme is the executable timing anchor. The 100-candle
extreme is retained only as historical/reference evidence. This preserves
the scanner thesis: LONG near the recent 40-candle low, SHORT near the
recent 40-candle high. Entry timing is independent from SL/TP geometry.
"""

LOOKBACK_CANDLES = 100
TIMING_LOOKBACK_CANDLES = 40
ENTRY_BUFFER_ATR = 0.25
ENTRY_BUFFER_FLOOR_PCT = 0.03
MAX_PRIMARY_ANCHOR_DISTANCE_ATR = 2.0
MIN_TIMING_SCORE = 0.35
MAX_TIMING_SCORE = 1.00


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


def _anchor(window, direction):
    lows = [_low(row) for row in window]
    highs = [_high(row) for row in window]
    if any(value is None or value <= 0 for value in lows + highs):
        return None
    return min(lows) if direction == "LONG" else max(highs)


def calibrate_entry(rows_5m, direction, micro_atr, rows_15m=None, context=None):
    """Return calibrated entry location without producing SL/TP.

    The 40-candle extreme is always the executable timing anchor.
    The 100-candle extreme is retained as a reference only; it must never
    pull an executable entry away from the recent 40-candle extreme.
    """
    if direction not in {"LONG", "SHORT"}:
        return None
    if len(rows_5m) < LOOKBACK_CANDLES or micro_atr is None or micro_atr <= 0:
        return None

    window = rows_5m[-LOOKBACK_CANDLES:]
    current_price = _close(rows_5m[-1])
    if current_price is None or current_price <= 0:
        return None

    anchor_100 = _anchor(window, direction)
    anchor_40 = _anchor(rows_5m[-TIMING_LOOKBACK_CANDLES:], direction)
    if anchor_100 is None or anchor_40 is None:
        return None

    distance_100 = abs(current_price - anchor_100) / micro_atr
    distance_40 = abs(current_price - anchor_40) / micro_atr

    # Production timing thesis: recent 40-candle extreme is authoritative.
    # The 100-candle value is diagnostics/reference only.
    anchor = anchor_40
    anchor_window = TIMING_LOOKBACK_CANDLES
    anchor_source = "40c_timing"

    context = context or {}
    timing_components = []

    volumes = [_f(row[5]) for row in window]
    if len(volumes) >= 21 and all(v is not None and v >= 0 for v in volumes):
        baseline = sum(volumes[-21:-1]) / 20.0
        volume_ratio = volumes[-1] / baseline if baseline > 0 else 1.0
        volume_score = max(0.0, min(1.0, (volume_ratio - 0.75) / 0.75))
    else:
        volume_ratio, volume_score = 1.0, 0.5
    timing_components.append(volume_score)

    sweep_score = 0.0
    if len(window) >= 8:
        previous = window[-7:-1]
        last = window[-1]
        prior_low = min(_low(x) for x in previous)
        prior_high = max(_high(x) for x in previous)
        if direction == "LONG":
            sweep_score = 1.0 if _low(last) < prior_low and _close(last) > prior_low else 0.0
        else:
            sweep_score = 1.0 if _high(last) > prior_high and _close(last) < prior_high else 0.0
    timing_components.append(sweep_score)

    flow_values = []
    for key in ("order_flow_score", "whale_score", "liquidation_score", "flow_conviction"):
        value = _f(context.get(key))
        if value is not None:
            flow_values.append(max(0.0, min(1.0, value)))
    flow_score = sum(flow_values) / len(flow_values) if flow_values else 0.5
    timing_components.append(flow_score)

    regime_score = 0.5
    if rows_15m and len(rows_15m) >= 32:
        window15 = rows_15m[-32:]
        hi15 = max(_high(x) for x in window15)
        lo15 = min(_low(x) for x in window15)
        span15 = hi15 - lo15
        if span15 > 0:
            pos15 = (_close(rows_15m[-1]) - lo15) / span15
            regime_score = (
                max(0.0, min(1.0, 1.0 - pos15 / 0.50))
                if direction == "LONG"
                else max(0.0, min(1.0, (pos15 - 0.50) / 0.50))
            )
    timing_components.append(regime_score)

    timing_score = sum(timing_components) / len(timing_components)

    buffer_factor = ENTRY_BUFFER_ATR
    buffer = max(micro_atr * buffer_factor, current_price * ENTRY_BUFFER_FLOOR_PCT / 100.0)
    entry = anchor + buffer if direction == "LONG" else anchor - buffer
    distance_atr = abs(current_price - entry) / micro_atr

    return {
        "anchor": anchor,
        "anchor_100": anchor_100,
        "anchor_40": anchor_40,
        "anchor_source": anchor_source,
        "anchor_window": anchor_window,
        "anchor_distance_100_atr": round(distance_100, 4),
        "anchor_distance_40_atr": round(distance_40, 4),
        "buffer": buffer,
        "entry": entry,
        "current_price": current_price,
        "distance_atr": distance_atr,
        "lookback_candles": LOOKBACK_CANDLES,
        "timing_lookback_candles": TIMING_LOOKBACK_CANDLES,
        "timing_score": round(timing_score, 4),
        "volume_ratio_5m": round(volume_ratio, 4),
        "volume_regime": "expansion" if volume_ratio >= 1.25 else "compression" if volume_ratio < 0.75 else "normal",
        "flow_score": round(flow_score, 4),
        "sweep_score": round(sweep_score, 4),
        "regime_score_15m": round(regime_score, 4),
        "buffer_atr": round(buffer_factor, 4),
        "calibration_inputs": "40x5m executable extreme + 100x5m reference + 15m regime/location + volume regime + order-flow/liquidity",
    }

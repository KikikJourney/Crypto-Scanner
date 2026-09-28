"""Entry calibration layer.

This module answers only: WHERE/WHEN should the scanner attempt execution?
It deliberately does not calculate stop-loss or take-profit geometry.

The production anchor is the 100 fully closed 5m candle extreme. ATR is used
only to place a bounded execution buffer around that anchor.
"""

LOOKBACK_CANDLES = 100
ENTRY_BUFFER_ATR = 0.25
ENTRY_BUFFER_FLOOR_PCT = 0.03
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


def calibrate_entry(rows_5m, direction, micro_atr, rows_15m=None, context=None):
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

    # Timing calibration uses location first, then market participation.
    # Missing external flow data is neutral rather than a hard rejection.
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

    # Adaptive buffer remains bounded around the 100-candle anchor. This is
    # timing calibration only; SL/TP geometry is untouched.
    # The anchor/buffer remains deterministic. Volume/flow/regime calibrate
    # timing quality without silently moving the 100-candle entry geometry.
    buffer_factor = ENTRY_BUFFER_ATR
    buffer = max(micro_atr * buffer_factor, current_price * ENTRY_BUFFER_FLOOR_PCT / 100.0)
    entry = anchor + buffer if direction == "LONG" else anchor - buffer
    distance_atr = abs(current_price - entry) / micro_atr

    return {
        "anchor": anchor,
        "buffer": buffer,
        "entry": entry,
        "current_price": current_price,
        "distance_atr": distance_atr,
        "lookback_candles": LOOKBACK_CANDLES,
        "timing_score": round(timing_score, 4),
        "volume_ratio_5m": round(volume_ratio, 4),
        "volume_regime": "expansion" if volume_ratio >= 1.25 else "compression" if volume_ratio < 0.75 else "normal",
        "flow_score": round(flow_score, 4),
        "sweep_score": round(sweep_score, 4),
        "regime_score_15m": round(regime_score, 4),
        "buffer_atr": round(buffer_factor, 4),
        "calibration_inputs": "100x5m + 15m regime/location + volume regime + order-flow/liquidity",
    }

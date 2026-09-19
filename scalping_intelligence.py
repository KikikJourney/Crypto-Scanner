"""Multi-timeframe scalping intelligence layer.

This module does NOT modify the existing V2.2 scoring engine. It consumes
MTF direction/context and adds execution-quality filters for 4H/1H/30m/15m
context plus 5m entry precision, location, and reversal confirmation.
"""
from datetime import datetime, timezone, timedelta
from math import isfinite


def _f(v, default=None):
    try:
        x = float(v)
        return x if isfinite(x) else default
    except (TypeError, ValueError):
        return default


def _close(r): return _f(r[4], 0.0)
def _high(r): return _f(r[2], 0.0)
def _low(r): return _f(r[3], 0.0)
def _volume(r): return _f(r[5], 0.0)


def aggregate(rows, bars):
    if bars <= 0:
        raise ValueError("bars must be positive")
    usable = len(rows) - len(rows) % bars
    out = []
    for i in range(0, usable, bars):
        g = rows[i:i + bars]
        out.append([g[0][0], g[0][1], max(_high(x) for x in g),
                    min(_low(x) for x in g), _close(g[-1]),
                    sum(_volume(x) for x in g)])
    return out


def ema(values, period):
    if len(values) < period:
        return None
    value = sum(values[:period]) / period
    alpha = 2.0 / (period + 1.0)
    for item in values[period:]:
        value = alpha * item + (1.0 - alpha) * value
    return value


def rsi(values, period=14):
    if len(values) < period + 1:
        return None
    gains, losses = [], []
    for a, b in zip(values[-period - 1:-1], values[-period:]):
        delta = b - a
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)


def atr(rows, period=14):
    if len(rows) < 2:
        return None
    trs, previous = [], None
    for row in rows:
        high, low, close = _high(row), _low(row), _close(row)
        tr = high - low if previous is None else max(
            high - low, abs(high - previous), abs(low - previous))
        trs.append(tr)
        previous = close
    if len(trs) < period:
        return None
    return sum(trs[-period:]) / period


def _trend_score(rows, direction):
    closes = [_close(x) for x in rows]
    n = len(closes)
    if n >= 50:
        fast_period, slow_period = 20, 50
    elif n >= 20:
        fast_period, slow_period = 8, 20
    elif n >= 10:
        fast_period, slow_period = 3, 8
    else:
        return 0.0
    fast, slow = ema(closes, fast_period), ema(closes, slow_period)
    if fast is None or slow is None:
        return 0.0
    if direction == "LONG":
        return 1.0 if fast >= slow and closes[-1] >= fast else 0.0
    return 1.0 if fast <= slow and closes[-1] <= fast else 0.0


def _structure_score(rows, direction):
    if len(rows) < 6:
        return 0.0
    recent = rows[-6:-1]
    close = _close(rows[-1])
    high = max(_high(x) for x in recent)
    low = min(_low(x) for x in recent)
    if direction == "LONG":
        return 1.0 if close > high else 0.5 if close >= low else 0.0
    return 1.0 if close < low else 0.5 if close <= high else 0.0


def _liquidity_sweep(rows, direction):
    if len(rows) < 8:
        return 0.0
    previous, last = rows[-7:-1], rows[-1]
    prior_high = max(_high(x) for x in previous)
    prior_low = min(_low(x) for x in previous)
    if direction == "LONG":
        return 1.0 if _low(last) < prior_low and _close(last) > prior_low else 0.0
    return 1.0 if _high(last) > prior_high and _close(last) < prior_high else 0.0


def _volume_score(rows):
    if len(rows) < 21:
        return 0.0
    base = sum(_volume(x) for x in rows[-21:-1]) / 20.0
    return min(1.0, max(0.0, (_volume(rows[-1]) / base - 1.0))) if base else 0.0


def _location_score(rows, direction, lookback=32):
    """Prefer lower-half LONG entries and upper-half SHORT entries."""
    if len(rows) < max(8, lookback):
        return 0.0
    window = rows[-lookback:]
    high = max(_high(x) for x in window)
    low = min(_low(x) for x in window)
    span = high - low
    if span <= 0:
        return 0.0
    position = (_close(rows[-1]) - low) / span
    if direction == "LONG":
        return 1.0 if position <= 0.35 else 0.5 if position <= 0.50 else 0.0
    return 1.0 if position >= 0.65 else 0.5 if position >= 0.50 else 0.0


def _reversal_score(rows, direction):
    """Require a 5m rejection/sweep or a fresh directional recovery."""
    if len(rows) < 8:
        return 0.0
    previous, last = rows[-7:-1], rows[-1]
    prior_high = max(_high(x) for x in previous)
    prior_low = min(_low(x) for x in previous)
    last_open, last_close = _f(last[1], _close(last)), _close(last)
    last_high, last_low = _high(last), _low(last)
    candle_range = last_high - last_low
    if candle_range <= 0:
        return 0.0
    bullish = last_close > last_open
    bearish = last_close < last_open
    upper = (last_close - last_low) / candle_range >= 0.60
    lower = (last_high - last_close) / candle_range >= 0.60
    if direction == "LONG":
        sweep = last_low < prior_low and last_close > prior_low
        recovery = bullish and upper and last_close > _close(previous[-1])
        return 1.0 if sweep else 0.5 if recovery else 0.0
    sweep = last_high > prior_high and last_close < prior_high
    recovery = bearish and lower and last_close < _close(previous[-1])
    return 1.0 if sweep else 0.5 if recovery else 0.0


def _timestamp(row):
    try:
        value = float(row[0])
        if value > 10_000_000_000:
            value /= 1000
        return datetime.fromtimestamp(value, timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def infer_direction(rows_15m, rows_5m):
    """Infer trade side from MTF trend/structure without requiring V2.2."""
    if len(rows_15m) < 160 or len(rows_5m) < 60:
        return None
    tf1h, tf4h, tf30 = aggregate(rows_15m, 4), aggregate(rows_15m, 16), aggregate(rows_15m, 2)
    if len(tf1h) < 40 or len(tf4h) < 8 or len(tf30) < 20:
        return None
    long_sum = sum((_trend_score(tf4h, "LONG"), _trend_score(tf1h, "LONG"),
                    _structure_score(tf30, "LONG"), _structure_score(rows_15m, "LONG")))
    short_sum = sum((_trend_score(tf4h, "SHORT"), _trend_score(tf1h, "SHORT"),
                     _structure_score(tf30, "SHORT"), _structure_score(rows_15m, "SHORT")))
    if long_sum >= 3.0 and long_sum > short_sum:
        return "LONG"
    if short_sum >= 3.0 and short_sum > long_sum:
        return "SHORT"
    return None


def build_plan(direction, rows_15m, rows_5m, v2_score, v2_features, require_v2_direction=True):
    """Build a plan only when direction, location, reversal and risk agree."""
    if direction not in {"LONG", "SHORT"}:
        return {"status": "NO-TRADE", "reason": "no trade direction"}
    if len(rows_15m) < 160 or len(rows_5m) < 60:
        return {"status": "DATA-LIMITED", "reason": "insufficient MTF candles"}

    tf30, tf1h, tf4h = aggregate(rows_15m, 2), aggregate(rows_15m, 4), aggregate(rows_15m, 16)
    if len(tf30) < 20 or len(tf1h) < 40 or len(tf4h) < 8:
        return {"status": "DATA-LIMITED", "reason": "insufficient aggregated timeframe history"}

    score_4h = _trend_score(tf4h, direction)
    score_1h = _trend_score(tf1h, direction)
    score_30 = _structure_score(tf30, direction)
    score_15 = _structure_score(rows_15m, direction)
    location_15 = _location_score(rows_15m, direction)
    reversal_5 = _reversal_score(rows_5m, direction)
    sweep_5 = _liquidity_sweep(rows_5m, direction)
    volume_5 = _volume_score(rows_5m)
    closes5 = [_close(x) for x in rows_5m]
    rsi5 = rsi(closes5, 14)
    momentum_5 = 1.0 if (
        (direction == "LONG" and rsi5 is not None and 45 <= rsi5 <= 68) or
        (direction == "SHORT" and rsi5 is not None and 32 <= rsi5 <= 55)
    ) else 0.0

    if location_15 == 0.0:
        return {"status": "WAIT", "direction": direction, "confidence": 0.0,
                "location_15m": location_15, "reversal_5m": reversal_5,
                "reason": "entry location is unfavorable for direction"}
    if reversal_5 == 0.0:
        return {"status": "WAIT", "direction": direction, "confidence": 0.0,
                "location_15m": location_15, "reversal_5m": reversal_5,
                "reason": "no 5m pullback/reversal confirmation"}

    confidence = 100.0 * (
        0.15 * score_4h + 0.15 * score_1h + 0.10 * score_30 + 0.10 * score_15 +
        0.20 * location_15 + 0.20 * reversal_5 + 0.05 * sweep_5 +
        0.03 * volume_5 + 0.02 * momentum_5
    )

    if not require_v2_direction:
        alignment = score_4h + score_1h + score_30 + score_15
        if alignment < 3.0:
            return {"status": "WAIT", "direction": direction,
                    "confidence": round(confidence, 1),
                    "location_15m": location_15, "reversal_5m": reversal_5,
                    "reason": "MTF directional alignment below threshold"}
        if _f(v2_score, 0.0) >= 80.0:
            confidence = min(100.0, confidence + 3.0)

    price = _close(rows_5m[-1])
    atr15 = _f(v2_features.get("atr"))
    if not price or not atr15:
        return {"status": "DATA-LIMITED", "reason": "price/ATR unavailable"}

    micro_atr = atr(rows_5m, 14) or atr15 / 3.0
    buffer = max(micro_atr * 0.20, price * 0.0003)
    entry_low, entry_high = price - buffer, price + buffer
    structure_rows_5, structure_rows_15 = rows_5m[-7:-1], rows_15m[-5:-1]
    if len(structure_rows_5) < 3 or len(structure_rows_15) < 2:
        return {"status": "DATA-LIMITED", "reason": "execution structure unavailable"}

    recent_5m_low = min(_low(x) for x in structure_rows_5)
    recent_5m_high = max(_high(x) for x in structure_rows_5)
    recent_15m_low = min(_low(x) for x in structure_rows_15)
    recent_15m_high = max(_high(x) for x in structure_rows_15)

    if direction == "LONG":
        structural_stop = recent_5m_low
        if structural_stop >= entry_low:
            structural_stop = recent_15m_low
        stop = structural_stop - 0.20 * micro_atr
        risk = entry_high - stop
        target = entry_high + 2.0 * risk
    else:
        structural_stop = recent_5m_high
        if structural_stop <= entry_high:
            structural_stop = recent_15m_high
        stop = structural_stop + 0.20 * micro_atr
        risk = stop - entry_low
        target = entry_low - 2.0 * risk

    if risk <= 0:
        return {"status": "INVALID", "reason": "non-positive execution risk"}

    risk_pct = risk / price * 100.0
    max_stop_distance_pct = 2.0
    if risk_pct > max_stop_distance_pct:
        return {"status": "WAIT", "reason": "execution stop distance exceeds scalping limit",
                "confidence": round(confidence, 1), "location_15m": location_15,
                "reversal_5m": reversal_5, "risk_pct": round(risk_pct, 4),
                "max_stop_distance_pct": max_stop_distance_pct}
    if risk_pct < 0.10:
        return {"status": "NO-TRADE", "reason": "execution risk below configured minimum",
                "confidence": round(confidence, 1), "location_15m": location_15,
                "reversal_5m": reversal_5, "risk_pct": round(risk_pct, 4),
                "max_stop_distance_pct": max_stop_distance_pct}

    status = "WAIT" if confidence < 80.0 else (
        "ACTION LONG" if direction == "LONG" else "ACTION SHORT")
    ts = _timestamp(rows_5m[-1])
    valid_until = ts + timedelta(minutes=15) if ts else None
    latest_5m_ts = _timestamp(rows_5m[-1])
    latest_15m_ts = _timestamp(rows_15m[-1])
    return {
        "status": status, "direction": direction, "confidence": round(confidence, 1),
        "v2_score": round(_f(v2_score, 0.0), 1), "entry": round(price, 12),
        "entry_low": round(entry_low, 12), "entry_high": round(entry_high, 12),
        "stop": round(stop, 12), "target": round(target, 12),
        "risk_pct": round(risk_pct, 4), "reward_r": 2.0,
        "rsi_5m": round(rsi5, 2) if rsi5 is not None else None,
        "trend_4h": score_4h, "trend_1h": score_1h, "structure_30m": score_30,
        "structure_15m": score_15, "location_15m": location_15,
        "reversal_5m": reversal_5, "liquidity_sweep_5m": sweep_5,
        "volume_5m": round(volume_5, 3),
        "valid_until": valid_until.isoformat() if valid_until else "",
        "latest_closed_5m_timestamp": latest_5m_ts.isoformat() if latest_5m_ts else "",
        "latest_closed_15m_timestamp": latest_15m_ts.isoformat() if latest_15m_ts else "",
        "timeframes": "4H/1H/30m/15m/5m",
        "reason": ("MTF brain + V2.2 confirmation" if require_v2_direction
                   else "MTF brain: direction + location + reversal + execution"),
    }

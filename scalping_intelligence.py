"""Multi-timeframe scalping intelligence layer.

This module does NOT modify the existing V2.2 scoring engine. It consumes a
V2.2 extreme direction and adds execution-quality filters for 4H/1H/30m/15m
context plus 5m entry precision.
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
        out.append([
            g[0][0], g[0][1], max(_high(x) for x in g),
            min(_low(x) for x in g), _close(g[-1]),
            sum(_volume(x) for x in g)
        ])
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
    trs = []
    previous = None
    for row in rows:
        high, low, close = _high(row), _low(row), _close(row)
        tr = high - low if previous is None else max(
            high - low, abs(high - previous), abs(low - previous)
        )
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
    previous = rows[-7:-1]
    last = rows[-1]
    prior_high = max(_high(x) for x in previous)
    prior_low = min(_low(x) for x in previous)
    if direction == "LONG":
        return 1.0 if _low(last) < prior_low and _close(last) > prior_low else 0.0
    return 1.0 if _high(last) > prior_high and _close(last) < prior_high else 0.0


def _volume_score(rows):
    if len(rows) < 21:
        return 0.0
    base = sum(_volume(x) for x in rows[-21:-1]) / 20.0
    return min(1.0, max(0.0, (_volume(rows[-1]) / base - 1.0) / 1.0)) if base else 0.0


def _timestamp(row):
    try:
        value = float(row[0])
        if value > 10_000_000_000:
            value /= 1000
        return datetime.fromtimestamp(value, timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def build_plan(direction, rows_15m, rows_5m, v2_score, v2_features):
    """Return an execution plan only when MTF conditions support the V2.2 side."""
    if direction not in {"LONG", "SHORT"}:
        return {"status": "NO-TRADE", "reason": "no V2.2 direction"}
    if len(rows_15m) < 160 or len(rows_5m) < 60:
        return {"status": "DATA-LIMITED", "reason": "insufficient MTF candles"}

    tf30 = aggregate(rows_15m, 2)
    tf1h = aggregate(rows_15m, 4)
    tf4h = aggregate(rows_15m, 16)
    if len(tf30) < 20 or len(tf1h) < 40 or len(tf4h) < 8:
        return {"status": "DATA-LIMITED", "reason": "insufficient aggregated timeframe history"}

    # All calculations use closed candles only. rows_5m is expected to have
    # its current in-progress candle removed by the caller.
    score_4h = _trend_score(tf4h, direction)
    score_1h = _trend_score(tf1h, direction)
    score_30 = _structure_score(tf30, direction)
    score_15 = _structure_score(rows_15m, direction)
    sweep_5 = _liquidity_sweep(rows_5m, direction)
    volume_5 = _volume_score(rows_5m)
    closes5 = [_close(x) for x in rows_5m]
    rsi5 = rsi(closes5, 14)
    momentum_5 = 1.0 if (
        (direction == "LONG" and rsi5 is not None and 52 <= rsi5 <= 72)
        or (direction == "SHORT" and rsi5 is not None and 28 <= rsi5 <= 48)
    ) else 0.0

    # Weighted execution confidence. V2.2 remains the gating layer.
    confidence = 100.0 * (
        0.20 * score_4h +
        0.20 * score_1h +
        0.20 * score_30 +
        0.15 * score_15 +
        0.10 * sweep_5 +
        0.10 * volume_5 +
        0.05 * momentum_5
    )

    price = _close(rows_5m[-1])
    atr15 = _f(v2_features.get("atr"))
    if not price or not atr15:
        return {"status": "DATA-LIMITED", "reason": "price/ATR unavailable"}

    # Entry is a bounded execution zone around the latest 5m close.
    # The V2.2 extreme anchor remains the stop reference.
    micro_atr = atr(rows_5m, 14) or atr15 / 3.0
    buffer = max(micro_atr * 0.20, price * 0.0003)
    if direction == "LONG":
        entry_low, entry_high = price - buffer, price + buffer
        stop = _f(v2_features.get("extreme_low_24")) - 0.25 * atr15
        risk = entry_high - stop
        target = entry_high + 2.0 * risk
    else:
        entry_low, entry_high = price - buffer, price + buffer
        stop = _f(v2_features.get("extreme_high_24")) + 0.25 * atr15
        risk = stop - entry_low
        target = entry_low - 2.0 * risk

    if risk <= 0:
        return {"status": "INVALID", "reason": "non-positive execution risk"}

    risk_pct = risk / price * 100.0
    if risk_pct > 8.0 or risk_pct < 0.10:
        return {
            "status": "NO-TRADE",
            "reason": "execution risk outside configured band",
            "confidence": round(confidence, 1),
            "risk_pct": round(risk_pct, 4),
        }

    # High-confidence threshold deliberately sits above the old V2.2 gate.
    if confidence < 80.0:
        status = "WAIT"
    else:
        status = "ACTION LONG" if direction == "LONG" else "ACTION SHORT"

    ts = _timestamp(rows_5m[-1])
    valid_until = ts + timedelta(minutes=15) if ts else None
    return {
        "status": status,
        "direction": direction,
        "confidence": round(confidence, 1),
        "v2_score": round(_f(v2_score, 0.0), 1),
        "entry": round(price, 12),
        "entry_low": round(entry_low, 12),
        "entry_high": round(entry_high, 12),
        "stop": round(stop, 12),
        "target": round(target, 12),
        "risk_pct": round(risk_pct, 4),
        "reward_r": 2.0,
        "rsi_5m": round(rsi5, 2) if rsi5 is not None else None,
        "trend_4h": score_4h,
        "trend_1h": score_1h,
        "structure_30m": score_30,
        "structure_15m": score_15,
        "liquidity_sweep_5m": sweep_5,
        "volume_5m": round(volume_5, 3),
        "valid_until": valid_until.isoformat() if valid_until else "",
        "timeframes": "4H/1H/30m/15m/5m",
        "reason": "V2.2 extreme + MTF structure/momentum/liquidity confirmation",
    }

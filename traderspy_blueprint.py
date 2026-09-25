"""TraderSpy-inspired external market diagnostic layer.

This module is intentionally independent of scanner_v2.py. It does not create
or block trades. It measures the same market-state dimensions used by the
external TraderSpy audit: ATR%, volume expansion, ADX/trend strength, RSI,
MACD momentum, EMA spread, Bollinger position and directional alignment.

Use it as a diagnostic/confirmation layer for Signal Hunter and Alpha Hunter.
"""
from math import isfinite


def _f(value, default=0.0):
    try:
        x = float(value)
        return x if isfinite(x) else default
    except (TypeError, ValueError):
        return default


def _close(row):
    return _f(row[4])


def _high(row):
    return _f(row[2])


def _low(row):
    return _f(row[3])


def _volume(row):
    return _f(row[5])


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
    gains = []
    losses = []
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
    if len(rows) < period:
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
    return sum(trs[-period:]) / period


def adx(rows, period=14):
    """Wilder-style ADX approximation using the last available window."""
    if len(rows) < period * 2 + 1:
        return None, None, None

    tr_values = []
    plus_dm = []
    minus_dm = []
    previous_high = previous_low = previous_close = None

    for row in rows:
        high, low, close = _high(row), _low(row), _close(row)
        if previous_close is None:
            previous_high, previous_low, previous_close = high, low, close
            continue

        tr_values.append(max(
            high - low,
            abs(high - previous_close),
            abs(low - previous_close),
        ))
        up_move = high - previous_high
        down_move = previous_low - low
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0.0)
        previous_high, previous_low, previous_close = high, low, close

    if len(tr_values) < period:
        return None, None, None

    def smooth(values):
        value = sum(values[:period])
        out = [value]
        for item in values[period:]:
            value = value - value / period + item
            out.append(value)
        return out

    tr_s = smooth(tr_values)
    plus_s = smooth(plus_dm)
    minus_s = smooth(minus_dm)

    dx = []
    plus_di = minus_di = 0.0
    for tr, plus, minus in zip(tr_s, plus_s, minus_s):
        if tr <= 0:
            dx.append(0.0)
            continue
        plus_di = 100.0 * plus / tr
        minus_di = 100.0 * minus / tr
        denom = plus_di + minus_di
        dx.append(100.0 * abs(plus_di - minus_di) / denom if denom else 0.0)

    if len(dx) < period:
        return None, plus_di, minus_di

    adx_value = sum(dx[:period]) / period
    for item in dx[period:]:
        adx_value = ((adx_value * (period - 1)) + item) / period
    return adx_value, plus_di, minus_di


def macd_histogram(values, fast=12, slow=26, signal=9):
    if len(values) < slow + signal:
        return None
    fast_series = []
    # Build the MACD series from progressively growing windows. This is
    # deliberately simple and deterministic for a diagnostic, not a trading
    # engine implementation.
    for i in range(slow, len(values) + 1):
        window = values[:i]
        fast_ema = ema(window, fast)
        slow_ema = ema(window, slow)
        if fast_ema is not None and slow_ema is not None:
            fast_series.append(fast_ema - slow_ema)
    if len(fast_series) < signal:
        return None
    signal_line = ema(fast_series, signal)
    if signal_line is None:
        return None
    return fast_series[-1] - signal_line


def bollinger(values, period=20, std_mult=2.0):
    if len(values) < period:
        return None, None, None
    window = values[-period:]
    mean = sum(window) / period
    variance = sum((x - mean) ** 2 for x in window) / period
    std = variance ** 0.5
    upper = mean + std_mult * std
    lower = mean - std_mult * std
    width_pct = ((upper - lower) / mean * 100.0) if mean else None
    span = upper - lower
    percent_b = (values[-1] - lower) / span if span else 0.5
    return percent_b, width_pct, mean


def volume_ratio(rows, period=20):
    if len(rows) < period + 1:
        return None
    baseline = sum(_volume(row) for row in rows[-period - 1:-1]) / period
    return _volume(rows[-1]) / baseline if baseline > 0 else None


def range_position(rows, lookback=32):
    if len(rows) < lookback:
        return None
    high = max(_high(row) for row in rows[-lookback:])
    low = min(_low(row) for row in rows[-lookback:])
    span = high - low
    return (_close(rows[-1]) - low) / span if span > 0 else 0.5


def diagnose(rows, direction=None, existing=None):
    """Return a non-blocking market-state diagnostic.

    Existing scanner data may contain funding/taker/book fields. Those are
    reported as external-context proxies; open interest is intentionally left
    unknown because the scanner does not currently fetch OI.
    """
    existing = existing or {}
    closes = [_close(row) for row in rows]
    current = closes[-1] if closes else None
    atr_value = atr(rows)
    atr_pct = atr_value / current * 100.0 if atr_value and current else None
    volume = volume_ratio(rows)
    adx_value, plus_di, minus_di = adx(rows)
    rsi_value = rsi(closes)
    macd = macd_histogram(closes)
    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    ema_spread = (
        (ema20 - ema50) / ema50 * 100.0
        if ema20 is not None and ema50
        else None
    )
    bb_pct, bb_width_pct, _ = bollinger(closes)
    position = range_position(rows)

    volatility_active = atr_pct is not None and atr_pct >= 0.50
    volume_expanded = volume is not None and volume >= 1.20
    trend_active = adx_value is not None and adx_value >= 20.0

    if direction == "LONG":
        momentum_aligned = (
            (rsi_value is not None and 45.0 <= rsi_value <= 68.0)
            and (macd is not None and macd >= 0.0)
        )
        location_aligned = position is not None and position <= 0.50
        directional_di = plus_di is not None and minus_di is not None and plus_di >= minus_di
    elif direction == "SHORT":
        momentum_aligned = (
            (rsi_value is not None and 32.0 <= rsi_value <= 55.0)
            and (macd is not None and macd <= 0.0)
        )
        location_aligned = position is not None and position >= 0.50
        directional_di = plus_di is not None and minus_di is not None and minus_di >= plus_di
    else:
        momentum_aligned = (
            rsi_value is not None and macd is not None
        )
        location_aligned = position is not None
        directional_di = (
            plus_di is not None and minus_di is not None
        )

    reasons = []
    if not volatility_active:
        reasons.append("LOW_VOLATILITY")
    if not volume_expanded:
        reasons.append("LOW_VOLUME_EXPANSION")
    if not trend_active:
        reasons.append("WEAK_TREND")
    if direction and not momentum_aligned:
        reasons.append("MOMENTUM_MISALIGNED")
    if direction and not directional_di:
        reasons.append("DIRECTIONAL_DI_MISMATCH")
    if direction and not location_aligned:
        reasons.append("LOCATION_MISMATCH")

    # A diagnostic score is deliberately descriptive, not a trade score.
    checks = [volatility_active, volume_expanded, trend_active,
              momentum_aligned, directional_di, location_aligned]
    context_score = round(100.0 * sum(checks) / len(checks), 1)

    return {
        "context_score": context_score,
        "volatility_active": volatility_active,
        "volume_expanded": volume_expanded,
        "trend_active": trend_active,
        "momentum_aligned": momentum_aligned,
        "directional_di_aligned": directional_di,
        "location_aligned": location_aligned,
        "atr_pct": round(atr_pct, 4) if atr_pct is not None else None,
        "adx": round(adx_value, 3) if adx_value is not None else None,
        "plus_di": round(plus_di, 3) if plus_di is not None else None,
        "minus_di": round(minus_di, 3) if minus_di is not None else None,
        "rsi": round(rsi_value, 3) if rsi_value is not None else None,
        "macd_histogram": macd,
        "ema_spread_pct": round(ema_spread, 4) if ema_spread is not None else None,
        "bb_percent_b": round(bb_pct, 4) if bb_pct is not None else None,
        "bb_width_pct": round(bb_width_pct, 4) if bb_width_pct is not None else None,
        "range_position": round(position, 4) if position is not None else None,
        "volume_ratio": round(volume, 4) if volume is not None else None,
        "funding_proxy": existing.get("funding"),
        "taker_ratio_proxy": existing.get("taker"),
        "book_ratio_proxy": existing.get("book"),
        "open_interest": None,
        "oi_status": "NOT_AVAILABLE",
        "reasons": reasons,
    }


def blueprint_label(diag):
    """Classify market state without declaring a trade signal."""
    if diag["volatility_active"] and diag["volume_expanded"] and diag["trend_active"]:
        return "ACTIVE"
    if diag["volatility_active"] or diag["volume_expanded"]:
        return "BUILDING"
    return "QUIET"


__all__ = [
    "adx", "atr", "blueprint_label", "bollinger", "diagnose",
    "ema", "macd_histogram", "range_position", "rsi", "volume_ratio",
]

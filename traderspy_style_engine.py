"""TraderSpy-style confluence lane for the Zorathvael scanner.

This is an independent discovery lane inspired by TraderSpy's documented
methodology: multi-indicator confluence, multi-timeframe trend context,
volume confirmation, volatility-aware risk, and structural targets.

It does NOT call TraderSpy or copy live TraderSpy signals. It computes the
same class of inputs locally from the scanner's exchange candles.
"""

from math import sqrt

from scalping_intelligence import aggregate


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _close(r): return _f(r[4])
def _high(r): return _f(r[2])
def _low(r): return _f(r[3])
def _open(r): return _f(r[1])
def _volume(r): return _f(r[5]) if len(r) > 5 else 0.0


def ema(values, period):
    if len(values) < period:
        return None
    k = 2.0 / (period + 1.0)
    value = sum(values[:period]) / period
    for item in values[period:]:
        value = item * k + value * (1.0 - k)
    return value


def rsi(values, period=14):
    if len(values) < period + 1:
        return None
    gains = []
    losses = []
    for a, b in zip(values[-period-1:-1], values[-period:]):
        delta = b - a
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def atr(rows, period=14):
    if len(rows) < period + 1:
        return None
    trs = []
    previous = _close(rows[-period-1])
    for row in rows[-period:]:
        high, low = _high(row), _low(row)
        trs.append(max(high - low, abs(high - previous), abs(low - previous)))
        previous = _close(row)
    return sum(trs) / period


def macd(values):
    if len(values) < 35:
        return None, None, None
    fast = ema(values, 12)
    slow = ema(values, 26)
    if fast is None or slow is None:
        return None, None, None
    hist = fast - slow
    # A lightweight signal estimate using the last 9 MACD observations.
    series = []
    for i in range(26, len(values) + 1):
        f = ema(values[:i], 12)
        s = ema(values[:i], 26)
        if f is not None and s is not None:
            series.append(f - s)
    signal = ema(series, 9)
    return fast - slow, signal, hist - signal if signal is not None else None


def adx(rows, period=14):
    if len(rows) < 6:
        return None
    if len(rows) < period * 2 + 1:
        period = max(3, (len(rows) - 1) // 2)
    trs, plus_dm, minus_dm = [], [], []
    previous_close = _close(rows[-period*2-1])
    previous_high = _high(rows[-period*2-1])
    previous_low = _low(rows[-period*2-1])
    for row in rows[-period*2:]:
        high, low = _high(row), _low(row)
        up = high - previous_high
        down = previous_low - low
        trs.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
        previous_close, previous_high, previous_low = _close(row), high, low
    tr = sum(trs[-period:]) / period
    if tr <= 0:
        return 0.0
    pdi = 100.0 * (sum(plus_dm[-period:]) / period) / tr
    mdi = 100.0 * (sum(minus_dm[-period:]) / period) / tr
    denom = pdi + mdi
    return 100.0 * abs(pdi - mdi) / denom if denom else 0.0


def volume_ratio(rows, period=20):
    if len(rows) < period + 1:
        return None
    baseline = sum(_volume(r) for r in rows[-period-1:-1]) / period
    return _volume(rows[-1]) / baseline if baseline > 0 else None


def _side_metrics(rows, direction):
    closes = [_close(r) for r in rows]
    price = closes[-1]
    # Use the longest valid EMA pair for each available history length.
    # The current scanner deep-scan tape is shorter than a literal 200 EMA
    # after 1h/4h aggregation, so a hard 200-period requirement would make
    # this lane permanently DATA-LIMITED.
    if len(closes) >= 220:
        fast_period, slow_period = 50, 200
    elif len(closes) >= 120:
        fast_period, slow_period = 20, 50
    elif len(closes) >= 60:
        fast_period, slow_period = 9, 21
    else:
        fast_period, slow_period = 5, 8
    e20 = ema(closes, fast_period)
    e50 = ema(closes, slow_period)
    e200 = e50
    r = rsi(closes)
    m_hist = macd(closes)[2]
    a = atr(rows)
    adx_v = adx(rows)
    vol = volume_ratio(rows)
    if any(v is None for v in (e20, e50, e200, r, m_hist, a, adx_v, vol)):
        return None

    trend = (
        (price > e200 if direction == "LONG" else price < e200)
        + (e50 > e200 if direction == "LONG" else e50 < e200)
    )
    momentum = (
        (m_hist > 0 if direction == "LONG" else m_hist < 0)
        + (price > e20 if direction == "LONG" else price < e20)
    )
    rsi_ok = 44 <= r <= 68 if direction == "LONG" else 32 <= r <= 56
    volume_ok = vol >= 1.5
    adx_ok = adx_v >= 15.0

    # Pullback quality: price remains close enough to EMA50 to avoid chasing.
    ema50_distance_atr = abs(price - e50) / a if a > 0 else 999.0
    pullback_ok = ema50_distance_atr <= 1.5

    # Closed-candle trigger: direction agrees and closes back through EMA20.
    last = rows[-1]
    trigger = (
        _close(last) > _open(last) and price >= e20
        if direction == "LONG"
        else _close(last) < _open(last) and price <= e20
    )

    points = 0
    points += trend
    points += momentum
    points += 1 if rsi_ok else 0
    points += 1 if volume_ok else 0
    points += 1 if adx_ok else 0
    points += 2 if pullback_ok else 0
    points += 1 if trigger else 0

    return {
        "score": round(points / 9.0 * 100.0, 1),
        "price": price,
        "ema20": e20,
        "ema50": e50,
        "ema200": e200,
        "rsi": r,
        "macd_hist": m_hist,
        "adx": adx_v,
        "volume_ratio": vol,
        "atr": a,
        "ema50_distance_atr": ema50_distance_atr,
        "pullback_ok": pullback_ok,
        "trigger": trigger,
        "trend_points": trend,
        "momentum_points": momentum,
        "rsi_ok": rsi_ok,
        "volume_ok": volume_ok,
        "adx_ok": adx_ok,
    }


def _structure_target(rows, direction, entry, risk):
    if risk <= 0:
        return None
    highs = [_high(r) for r in rows[-48:]]
    lows = [_low(r) for r in rows[-48:]]
    if direction == "LONG":
        levels = sorted({x for x in highs if x > entry})
        for level in levels:
            rr = (level - entry) / risk
            if 2.0 <= rr <= 4.0:
                return level
    else:
        levels = sorted({x for x in lows if x < entry}, reverse=True)
        for level in levels:
            rr = (entry - level) / risk
            if 2.0 <= rr <= 4.0:
                return level
    return None


def build_plan(rows_15m, rows_5m=None):
    """Return an independent TraderSpy-style continuation plan or WAIT."""
    if len(rows_15m) < 160:
        return {"status": "DATA-LIMITED", "reason": "need >=160 15m candles"}

    tf1h = aggregate(rows_15m, 4)
    tf4h = aggregate(rows_15m, 16)
    if len(tf1h) < 40 or len(tf4h) < 8:
        return {"status": "DATA-LIMITED", "reason": "insufficient 1h/4h history"}

    candidates = {}
    for direction in ("LONG", "SHORT"):
        m15 = _side_metrics(rows_15m, direction)
        m1h = _side_metrics(tf1h, direction)
        m4h = _side_metrics(tf4h, direction)
        if not all((m15, m1h, m4h)):
            continue

        mtf = int(m1h["score"] >= 55.0) + int(m4h["score"] >= 55.0)
        score = (
            0.30 * m15["score"] +
            0.25 * m1h["score"] +
            0.25 * m4h["score"] +
            0.20 * (mtf / 2.0 * 100.0)
        )
        # TraderSpy-style validation is confluence, not one-indicator voting.
        if mtf < 2 or not m15["pullback_ok"] or not m15["trigger"]:
            continue
        candidates[direction] = (score, m15, m1h, m4h)

    if not candidates:
        return {"status": "WAIT", "reason": "no multi-timeframe confluence candidate"}

    direction, (score, m15, m1h, m4h) = max(
        candidates.items(), key=lambda item: item[1][0]
    )
    opposite = "SHORT" if direction == "LONG" else "LONG"
    if opposite in candidates and score - candidates[opposite][0] < 8.0:
        return {"status": "WAIT", "reason": "directional confluence too close"}

    if score < 70.0:
        return {"status": "WAIT", "direction": direction,
                "confidence": round(score, 1),
                "reason": "validation score below 70"}

    entry = m15["price"]
    a = m15["atr"]
    recent_low = min(_low(r) for r in rows_15m[-8:])
    recent_high = max(_high(r) for r in rows_15m[-8:])
    if direction == "LONG":
        stop = min(recent_low - 0.15 * a, entry - 1.5 * a)
        risk = entry - stop
    else:
        stop = max(recent_high + 0.15 * a, entry + 1.5 * a)
        risk = stop - entry

    risk_pct = risk / entry * 100.0 if entry else 999.0
    if risk <= 0 or risk_pct > 2.0 or risk_pct < 0.10:
        return {"status": "WAIT", "direction": direction,
                "confidence": round(score, 1),
                "reason": "volatility-adjusted stop outside risk bounds",
                "risk_pct": round(risk_pct, 4)}

    target = _structure_target(rows_15m, direction, entry, risk)
    if target is None:
        target = entry + 2.0 * risk if direction == "LONG" else entry - 2.0 * risk

    reward_r = (
        (target - entry) / risk if direction == "LONG"
        else (entry - target) / risk
    )
    if reward_r < 2.0:
        return {"status": "WAIT", "reason": "target below 2R"}

    return {
        "status": "ACTION LONG" if direction == "LONG" else "ACTION SHORT",
        "direction": direction,
        "confidence": round(score, 1),
        "entry": round(entry, 12),
        "entry_low": round(entry, 12),
        "entry_high": round(entry, 12),
        "stop": round(stop, 12),
        "target": round(target, 12),
        "risk_pct": round(risk_pct, 4),
        "reward_r": round(reward_r, 2),
        "rsi_15m": round(m15["rsi"], 2),
        "rsi_1h": round(m1h["rsi"], 2),
        "rsi_4h": round(m4h["rsi"], 2),
        "volume_15m": round(m15["volume_ratio"], 2),
        "adx_15m": round(m15["adx"], 2),
        "ema50_distance_atr": round(m15["ema50_distance_atr"], 3),
        "timeframes": "4H/1H/15m",
        "reason": "TraderSpy-style: MTF trend + momentum + RSI + volume + ADX + pullback + closed-candle trigger",
    }

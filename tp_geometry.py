"""Flow/trend/structure-aware take-profit geometry.

Production responsibility:
- consume a FINAL calibrated entry and stop;
- generate concrete price targets from observable structure;
- use current trend and flow/liquidity conviction to select target distance;
- never replace entry timing/calibration;
- enforce a 2R..8R target envelope.

No fixed TP1/TP2/TP3 rung is used for the selected target.
"""
from math import isfinite


MIN_TARGET_R = 2.0
MAX_TARGET_R = 8.0


def _f(v, default=0.0):
    try:
        x = float(v)
        return x if isfinite(x) else default
    except (TypeError, ValueError):
        return default


def _close(r): return _f(r[4])
def _high(r): return _f(r[2])
def _low(r): return _f(r[3])


def _ema(values, period):
    if len(values) < period:
        return None
    value = sum(values[:period]) / period
    alpha = 2.0 / (period + 1.0)
    for x in values[period:]:
        value = alpha * x + (1.0 - alpha) * value
    return value


def _trend_strength(rows_15m, direction):
    closes = [_close(x) for x in rows_15m]
    if len(closes) < 50:
        return 0.0
    fast = _ema(closes[-80:], 20)
    slow = _ema(closes[-80:], 50)
    if fast is None or slow is None or slow <= 0:
        return 0.0
    separation = abs(fast - slow) / slow
    aligned = (
        direction == "LONG" and fast >= slow and closes[-1] >= fast
    ) or (
        direction == "SHORT" and fast <= slow and closes[-1] <= fast
    )
    return max(0.0, min(1.0, separation / 0.01)) if aligned else 0.0


def _flow_conviction(context):
    context = context or {}
    keys = ("order_flow_score", "whale_score", "liquidation_score",
            "flow_conviction", "liquidity_sweep_score", "volume_score")
    vals = [_f(context.get(k), None) for k in keys]
    vals = [max(0.0, min(1.0, x)) for x in vals if x is not None]
    return sum(vals) / len(vals) if vals else 0.5


def _pivots(rows, direction, lookback=64):
    window = rows[-lookback:] if len(rows) >= lookback else rows[:]
    levels = []
    for i in range(2, len(window) - 2):
        c = _close(window[i])
        if direction == "LONG":
            if c >= _close(window[i-1]) and c >= _close(window[i+1]):
                levels.append(c)
        else:
            if c <= _close(window[i-1]) and c <= _close(window[i+1]):
                levels.append(c)
    return levels


def _range_boundary(rows, direction, lookback=64):
    window = rows[-lookback:] if len(rows) >= lookback else rows
    if not window:
        return None
    return max(_high(x) for x in window) if direction == "LONG" else min(_low(x) for x in window)


def _candidate_levels(rows_15m, rows_5m, direction, entry, risk):
    levels = []
    for level in _pivots(rows_15m, direction):
        levels.append(("15m_pivot", level))
    for level in _pivots(rows_5m, direction, 80):
        levels.append(("5m_pivot", level))
    boundary = _range_boundary(rows_15m, direction)
    if boundary is not None:
        levels.append(("15m_range_boundary", boundary))

    # ATR-like recent range projections provide a target only when structure
    # does not offer a clean opposing level.
    recent = rows_5m[-14:] if len(rows_5m) >= 14 else rows_5m
    if recent:
        avg_range = sum(_high(x) - _low(x) for x in recent) / len(recent)
        for mult in (2.0, 3.0, 4.0):
            level = entry + avg_range * mult if direction == "LONG" else entry - avg_range * mult
            levels.append(("5m_range_projection", level))

    out = []
    for source, level in levels:
        level = _f(level)
        if level <= 0:
            continue
        reward = (level - entry) / risk if direction == "LONG" else (entry - level) / risk
        if MIN_TARGET_R <= reward <= MAX_TARGET_R:
            out.append((source, level, reward))
    return out


def calibrate_tp(rows_15m, rows_5m, direction, entry, stop, context=None):
    """Return a concrete TP selected from current structure + flow/trend.

    The target is deliberately independent from entry timing. A target is
    returned only when a price level can support the required 2R..8R envelope.
    """
    entry, stop = _f(entry), _f(stop)
    if direction not in {"LONG", "SHORT"} or entry <= 0 or stop <= 0:
        return None

    risk = entry - stop if direction == "LONG" else stop - entry
    if risk <= 0:
        return None

    trend = _trend_strength(rows_15m or [], direction)
    flow = _flow_conviction(context)
    conviction = max(0.0, min(1.0, 0.55 * trend + 0.45 * flow))
    desired_r = MIN_TARGET_R + (MAX_TARGET_R - MIN_TARGET_R) * conviction

    candidates = _candidate_levels(rows_15m or [], rows_5m or [], direction, entry, risk)
    if not candidates:
        return None

    # Prefer the structurally closest level to the calibrated desired R,
    # with a small preference for higher-timeframe structure.
    source_weight = {
        "15m_pivot": 0.10,
        "15m_range_boundary": 0.08,
        "5m_pivot": 0.03,
        "5m_range_projection": 0.0,
    }
    ranked = sorted(
        candidates,
        key=lambda x: (
            abs(x[2] - desired_r) - source_weight.get(x[0], 0.0),
            x[2],
        ),
    )
    source, target, reward_r = ranked[0]

    return {
        "target": round(target, 12),
        "reward_r": round(reward_r, 4),
        "target_source": source,
        "trend_strength": round(trend, 4),
        "flow_conviction": round(flow, 4),
        "desired_reward_r": round(desired_r, 4),
        "min_reward_r": MIN_TARGET_R,
        "max_reward_r": MAX_TARGET_R,
    }

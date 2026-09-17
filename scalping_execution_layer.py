"""15m-30m scalping execution layer for the unchanged V2.2 scoring engine.

This module deliberately does NOT calculate or alter the V2.2 score/gate.
It converts an already-qualified extreme reversal into a short-lived
execution setup using closed 15m candles and a 30m confirmation.
"""
from datetime import datetime, timedelta, timezone

MAX_CONFIRMATION_MINUTES = 30
MAX_TRIGGER_GAP_ATR = 1.25
STOP_ATR_BUFFER = 0.25
REWARD_R = 2.0
MIN_RISK_PCT = 0.20
MAX_RISK_PCT = 8.0


def _f(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _close(row): return float(row[4])
def _high(row): return float(row[2])
def _low(row): return float(row[3])


def aggregate_30m(rows):
    """Aggregate closed 15m candles into closed 30m candles."""
    if not isinstance(rows, list):
        return []
    usable = len(rows) - (len(rows) % 2)
    out = []
    for i in range(0, usable, 2):
        group = rows[i:i + 2]
        out.append([
            group[0][0], group[0][1], max(_high(x) for x in group),
            min(_low(x) for x in group), _close(group[-1]),
            sum(float(x[5]) for x in group)
        ])
    return out


def _trigger(rows, direction):
    """Use the immediately preceding 30m structure as a 15m execution trigger."""
    if len(rows) < 4:
        return None
    previous = rows[-4:-2]
    if direction == 'LONG':
        return max(_high(x) for x in previous)
    if direction == 'SHORT':
        return min(_low(x) for x in previous)
    return None


def build_plan(features, rows_15m, direction):
    """Build a 15m trigger + 30m confirmation plan from an existing V2.2 extreme."""
    if direction not in {'LONG', 'SHORT'}:
        return {'status': 'INVALID', 'direction': direction, 'reason': 'invalid direction'}
    if not features or features.get('data_ok') is not True or len(rows_15m) < 4:
        return {'status': 'DATA-LIMITED', 'direction': direction, 'reason': 'scalping execution data unavailable'}

    price = _f(features.get('price'))
    atr = _f(features.get('atr'))
    if price is None or atr is None or price <= 0 or atr <= 0:
        return {'status': 'DATA-LIMITED', 'direction': direction, 'reason': 'price/ATR unavailable'}

    trigger = _trigger(rows_15m, direction)
    if trigger is None or trigger <= 0:
        return {'status': 'DATA-LIMITED', 'direction': direction, 'reason': '15m trigger unavailable'}

    # Preserve V2.2's extreme-based risk geometry: the execution layer changes
    # timing, not the scoring engine. Stop remains anchored to the 24h extreme.
    low = _f(features.get('extreme_low_24'))
    high = _f(features.get('extreme_high_24'))
    if low is None or high is None:
        return {'status': 'DATA-LIMITED', 'direction': direction, 'reason': 'V2.2 extreme anchors unavailable'}

    if direction == 'LONG':
        stop = low - STOP_ATR_BUFFER * atr
        risk = trigger - stop
    else:
        stop = high + STOP_ATR_BUFFER * atr
        risk = stop - trigger
    if risk <= 0:
        return {'status': 'INVALID', 'direction': direction, 'reason': 'non-positive trigger risk'}

    risk_pct = risk / trigger * 100
    if risk_pct < MIN_RISK_PCT or risk_pct > MAX_RISK_PCT:
        return {
            'status': 'WAIT', 'direction': direction, 'trigger': round(trigger, 12),
            'stop': round(stop, 12), 'risk_pct': round(risk_pct, 4),
            'reward_r': REWARD_R, 'reason': 'trigger risk outside configured execution band'
        }

    # Confirmation is based only on the latest closed 30m candle. The trigger
    # itself comes from the prior 30m structure, avoiding same-bar lookahead.
    rows_30m = aggregate_30m(rows_15m)
    if len(rows_30m) < 2:
        return {'status': 'DATA-LIMITED', 'direction': direction, 'reason': '30m confirmation unavailable'}
    confirmation_close = _close(rows_30m[-1])
    confirmed = confirmation_close >= trigger if direction == 'LONG' else confirmation_close <= trigger
    gap_atr = ((trigger - price) if direction == 'LONG' else (price - trigger)) / atr
    stale = not confirmed and gap_atr > MAX_TRIGGER_GAP_ATR

    target = trigger + REWARD_R * risk if direction == 'LONG' else trigger - REWARD_R * risk
    timestamp = _timestamp(rows_15m[-1][0])
    expiry = timestamp + timedelta(minutes=MAX_CONFIRMATION_MINUTES) if timestamp else None

    if stale:
        status = 'STALE'
        reason = '15m trigger became stale before 30m confirmation'
    elif confirmed:
        status = 'ACTION LONG' if direction == 'LONG' else 'ACTION SHORT'
        reason = '15m trigger confirmed by closed 30m structure'
    else:
        status = 'WAIT FOR LONG TRIGGER' if direction == 'LONG' else 'WAIT FOR SHORT TRIGGER'
        reason = 'V2.2 extreme valid; awaiting 15m trigger and 30m confirmation'

    return {
        'status': status, 'direction': direction, 'trigger': round(trigger, 12),
        'stop': round(stop, 12), 'target': round(target, 12),
        'risk_pct': round(risk_pct, 4), 'reward_r': REWARD_R,
        'confirmation_close': round(confirmation_close, 12),
        'confirmed': confirmed, 'trigger_gap_atr': round(gap_atr, 4),
        'max_trigger_gap_atr': MAX_TRIGGER_GAP_ATR,
        'confirmation_timeframe': '30m', 'trigger_timeframe': '15m',
        'valid_until': expiry.isoformat() if expiry else '', 'reason': reason
    }


def _timestamp(value):
    try:
        v = float(value)
        if v > 10_000_000_000:
            v /= 1000
        return datetime.fromtimestamp(v, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None

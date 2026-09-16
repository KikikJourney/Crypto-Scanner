"""Actionable confirmation layer built on top of V2.2 extreme reversal signals.

V2.2 answers: is price at a true extreme?
This layer answers: has structure actually confirmed the reversal?

No API calls live here; all decisions are deterministic from supplied features
and closed market snapshots.
"""

MIN_RISK_PCT = 0.20
MAX_RISK_PCT = 8.0
TRIGGER_LOOKBACK_HOURS = 4
STOP_ATR_BUFFER = 0.25
REWARD_R = 2.0
ADVERSE_R = 1.0


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_action_plan(features, direction):
    """Return a conditional action plan from an already-qualified extreme.

    The trigger is the prior 4-hour structure boundary. It deliberately uses
    completed hourly bars before the current bar, so the trigger itself has no
    look-ahead bias.
    """
    if not features or features.get('data_ok') is not True:
        return {'status': 'DATA-LIMITED', 'direction': direction, 'reason': 'extreme features unavailable'}
    price = _safe_float(features.get('price'))
    atr = _safe_float(features.get('atr'))
    low = _safe_float(features.get('extreme_low_24'))
    high = _safe_float(features.get('extreme_high_24'))
    trigger = _safe_float(features.get('long_trigger' if direction == 'LONG' else 'short_trigger'))
    if None in (price, atr, low, high, trigger) or atr <= 0 or price <= 0:
        return {'status': 'DATA-LIMITED', 'direction': direction, 'reason': 'action features unavailable'}

    if direction == 'LONG':
        stop = low - STOP_ATR_BUFFER * atr
        risk = trigger - stop
        confirmed = price >= trigger
        target = trigger + REWARD_R * risk
    else:
        stop = high + STOP_ATR_BUFFER * atr
        risk = stop - trigger
        confirmed = price <= trigger
        target = trigger - REWARD_R * risk

    if risk <= 0:
        return {'status': 'INVALID', 'direction': direction, 'reason': 'non-positive trigger risk'}
    risk_pct = risk / trigger * 100
    if risk_pct < MIN_RISK_PCT or risk_pct > MAX_RISK_PCT:
        return {'status': 'WAIT', 'direction': direction, 'trigger': trigger, 'stop': stop, 'target': target,
                'risk_pct': risk_pct, 'reason': 'trigger risk outside configured execution band'}
    return {
        'status': 'ACTION LONG' if direction == 'LONG' and confirmed else 'ACTION SHORT' if direction == 'SHORT' and confirmed else 'WAIT FOR LONG TRIGGER' if direction == 'LONG' else 'WAIT FOR SHORT TRIGGER',
        'direction': direction,
        'trigger': round(trigger, 12),
        'stop': round(stop, 12),
        'target': round(target, 12),
        'risk_pct': round(risk_pct, 4),
        'reward_r': REWARD_R,
        'adverse_r': ADVERSE_R,
        'reason': '4H structure reclaim confirmed' if confirmed else 'extreme valid; 4H structure reclaim not yet confirmed',
    }


def _action_outcome(direction, entry, future, stop, target):
    price = _safe_float(future)
    if None in (price, entry, stop, target):
        return None
    if direction == 'LONG':
        favorable = price >= target
        adverse = price <= stop
    else:
        favorable = price <= target
        adverse = price >= stop
    if favorable and adverse:
        return 'AMBIGUOUS'
    if favorable:
        return 'EXPANSION'
    if adverse:
        return 'FAIL'
    return None

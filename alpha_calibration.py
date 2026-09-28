"""Unified Alpha Hunter calibration engine.

Single calibration contract for scanner opportunity quality:
trend + order flow + open interest + funding + crowding + volatility +
location + structure + liquidity/reversal + volume + entry timing.

The engine produces direction-aware component scores and a composite quality
score. It estimates timing quality; it does not claim an exact market bottom/top.
Entry geometry, SL geometry and TP geometry remain separate responsibilities.
"""
from math import isfinite, log

WEIGHTS = {
    "trend": 0.12, "order_flow": 0.14, "open_interest": 0.10,
    "funding": 0.08, "crowding": 0.10, "volatility": 0.08,
    "location": 0.14, "structure": 0.08, "liquidity": 0.06,
    "volume": 0.04, "entry_timing": 0.06,
}
MIN_COMPONENTS = 6

def clamp(value, low=0.0, high=1.0):
    try: x = float(value)
    except (TypeError, ValueError): return None
    if not isfinite(x): return None
    return max(low, min(high, x))

def _num(context, *keys):
    for key in keys:
        try: value = float(context.get(key))
        except (TypeError, ValueError): continue
        if isfinite(value): return value
    return None

def _directional_binary(value, direction):
    value = clamp(value)
    if value is None: return None
    return value if direction == "LONG" else 1.0 - value

def _trend(context, direction):
    value = _num(context, "trend_score", "trend_strength", "trend_alignment")
    if value is not None: return clamp(value)
    fast, slow, price = _num(context, "ema_fast"), _num(context, "ema_slow"), _num(context, "price", "current_price")
    if None in (fast, slow, price) or slow == 0: return None
    return clamp(0.5 + 0.25 * ((fast > slow) if direction == "LONG" else (fast < slow)) + 0.25 * ((price >= fast) if direction == "LONG" else (price <= fast)))

def _order_flow(context, direction):
    direct = _num(context, "order_flow_score", "flow_conviction", "taker_flow_score")
    if direct is not None: return clamp(direct)
    ratio = _num(context, "taker_buy_sell_ratio", "taker_ratio")
    if ratio is None or ratio <= 0: return None
    score = clamp(0.5 + 0.5 * log(ratio) / log(4))
    return score if direction == "LONG" else 1.0 - score

def _oi(context, direction):
    direct = _num(context, "open_interest_score", "oi_alignment_score")
    if direct is not None: return clamp(direct)
    oi_change, price_change = _num(context, "oi_change_pct", "open_interest_change_pct"), _num(context, "price_change_pct", "return_pct")
    if oi_change is None or price_change is None: return None
    move = price_change if direction == "LONG" else -price_change
    if oi_change >= 0 and move > 0: return clamp(0.5 + min(0.5, move / 2.0))
    if oi_change > 0 and move < 0: return clamp(0.5 - min(0.5, abs(move) / 2.0))
    return 0.65 if oi_change < 0 else 0.5

def _funding(context, direction):
    direct = _num(context, "funding_score")
    if direct is not None: return clamp(direct)
    funding = _num(context, "funding_rate", "funding")
    if funding is None: return None
    magnitude = min(1.0, abs(funding) / 0.0015)
    favorable = funding < 0 if direction == "LONG" else funding > 0
    return clamp(0.5 + (magnitude if favorable else -magnitude) * 0.5)

def _crowding(context, direction):
    direct = _num(context, "crowding_score", "positioning_score")
    if direct is not None: return clamp(direct)
    ratio = _num(context, "long_short_ratio", "global_long_short_ratio")
    if ratio is None or ratio <= 0: return None
    return clamp(0.5 + min(0.5, max(0.0, (1.0 - ratio) if direction == "LONG" else (ratio - 1.0)))

def _volatility(context, direction):
    direct = _num(context, "volatility_score", "atr_regime_score")
    if direct is not None: return clamp(direct)
    atr_ratio = _num(context, "atr_ratio")
    if atr_ratio is not None: return clamp(1.0 - abs(atr_ratio - 1.25) / 1.25)
    atr_pct = _num(context, "atr_pct", "atr_percent")
    return clamp(1.0 - abs(atr_pct - 1.0) / 1.5) if atr_pct is not None else None

def _location(context, direction):
    direct = _num(context, "location_score", "entry_location_score")
    if direct is not None: return clamp(direct)
    pos = _num(context, "range_position", "range_pos", "position_15m")
    if pos is None: return None
    return clamp((0.50 - pos) / 0.50) if direction == "LONG" else clamp((pos - 0.50) / 0.50)

def _structure(context, direction):
    direct = _num(context, "structure_score", "structure_alignment")
    if direct is not None: return clamp(direct)
    shift = _num(context, "structure_shift_score", "structure_shift_5m")
    return _directional_binary(shift, direction) if shift is not None else None

def _liquidity(context, direction):
    direct = _num(context, "liquidity_score", "liquidity_sweep_score", "reversal_score")
    if direct is not None: return clamp(direct)
    sweep = _num(context, "sweep_score", "liquidity_sweep")
    return clamp(sweep) if sweep is not None else None

def _volume(context, direction):
    direct = _num(context, "volume_score")
    if direct is not None: return clamp(direct)
    ratio = _num(context, "volume_ratio", "volume_ratio_5m")
    return clamp((ratio - 0.75) / 1.25) if ratio is not None else None

def _entry_timing(context, direction):
    direct = _num(context, "entry_timing_score", "timing_score")
    if direct is not None: return clamp(direct)
    distance = _num(context, "entry_distance_atr")
    return clamp(1.0 - distance / 2.0) if distance is not None else None

def calibrate_alpha(direction, context=None):
    if direction not in {"LONG", "SHORT"}: raise ValueError("direction must be LONG or SHORT")
    context = context or {}
    calculators = {"trend": _trend, "order_flow": _order_flow, "open_interest": _oi, "funding": _funding, "crowding": _crowding, "volatility": _volatility, "location": _location, "structure": _structure, "liquidity": _liquidity, "volume": _volume, "entry_timing": _entry_timing}
    components, weighted, weight_total = {}, 0.0, 0.0
    for name, weight in WEIGHTS.items():
        value = calculators[name](context, direction)
        components[name] = None if value is None else round(clamp(value), 4)
        if value is not None: weighted += weight * value; weight_total += weight
    populated = sum(v is not None for v in components.values())
    completeness = populated / len(components)
    quality = weighted / weight_total * 100.0 if weight_total else 0.0
    timing_values = [components[k] for k in ("location", "entry_timing", "liquidity") if components[k] is not None]
    timing_score = sum(timing_values) / len(timing_values) * 100.0 if timing_values else 0.0
    return {"direction": direction, "quality_score": round(quality, 2), "timing_score": round(timing_score, 2), "data_completeness": round(completeness, 3), "populated_components": populated, "component_count": len(components), "components": components, "calibration_contract": "trend+orderflow+OI+funding+crowding+volatility+location+structure+liquidity+volume+timing", "calibration_status": "FULL" if populated == len(components) else "PARTIAL" if populated >= MIN_COMPONENTS else "DATA_LIMITED"}

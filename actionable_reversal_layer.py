"""Actionable confirmation layer built on top of V2.2 extreme reversal signals.

V2.2 answers: is price at a true extreme?
This layer answers: has structure actually confirmed the reversal?

The layer is intentionally deterministic and conservative. A trigger that is
now materially behind price is marked STALE rather than being carried forward
as a live WAIT setup. A stale setup must re-qualify as a new extreme event.
"""
MIN_RISK_PCT=0.20
MAX_RISK_PCT=8.0
TRIGGER_LOOKBACK_HOURS=4
STOP_ATR_BUFFER=0.25
REWARD_R=2.0
ADVERSE_R=1.0
MAX_TRIGGER_GAP_ATR=1.25

def _safe_float(value):
    try:return float(value)
    except (TypeError,ValueError):return None

def _trigger_gap_atr(price,trigger,atr,direction):
    if atr is None or atr<=0:return None
    gap=(trigger-price) if direction=='SHORT' else (price-trigger)
    return gap/atr

def build_action_plan(features,direction):
    """Build a conditional action plan and reject materially stale triggers."""
    if direction not in {'LONG','SHORT'}:
        return {'status':'INVALID','direction':direction,'reason':'invalid direction'}
    if not features or features.get('data_ok') is not True:
        return {'status':'DATA-LIMITED','direction':direction,'reason':'extreme features unavailable'}
    price=_safe_float(features.get('price'));atr=_safe_float(features.get('atr'))
    low=_safe_float(features.get('extreme_low_24'));high=_safe_float(features.get('extreme_high_24'))
    trigger=_safe_float(features.get('long_trigger' if direction=='LONG' else 'short_trigger'))
    if None in (price,atr,low,high,trigger) or atr<=0 or price<=0:
        return {'status':'DATA-LIMITED','direction':direction,'reason':'action features unavailable'}
    if direction=='LONG':
        stop=low-STOP_ATR_BUFFER*atr; risk=trigger-stop; confirmed=price>=trigger; target=trigger+REWARD_R*risk
    else:
        stop=high+STOP_ATR_BUFFER*atr; risk=stop-trigger; confirmed=price<=trigger; target=trigger-REWARD_R*risk
    if risk<=0:return {'status':'INVALID','direction':direction,'reason':'non-positive trigger risk'}
    risk_pct=risk/trigger*100
    gap_atr=_trigger_gap_atr(price,trigger,atr,direction)
    if not confirmed and gap_atr is not None and gap_atr>MAX_TRIGGER_GAP_ATR:
        return {'status':'STALE','direction':direction,'trigger':round(trigger,12),'stop':round(stop,12),'target':round(target,12),
                'risk_pct':round(risk_pct,4),'trigger_gap_atr':round(gap_atr,4),'max_trigger_gap_atr':MAX_TRIGGER_GAP_ATR,
                'reason':'trigger became stale: price moved too far from the unconfirmed structure'}
    if risk_pct<MIN_RISK_PCT or risk_pct>MAX_RISK_PCT:
        return {'status':'WAIT','direction':direction,'trigger':trigger,'stop':stop,'target':target,'risk_pct':risk_pct,
                'trigger_gap_atr':gap_atr,'reason':'trigger risk outside configured execution band'}
    return {'status':'ACTION LONG' if direction=='LONG' and confirmed else 'ACTION SHORT' if direction=='SHORT' and confirmed else 'WAIT FOR LONG TRIGGER' if direction=='LONG' else 'WAIT FOR SHORT TRIGGER',
            'direction':direction,'trigger':round(trigger,12),'stop':round(stop,12),'target':round(target,12),'risk_pct':round(risk_pct,4),
            'trigger_gap_atr':round(gap_atr,4) if gap_atr is not None else None,'reward_r':REWARD_R,'adverse_r':ADVERSE_R,
            'reason':'4H structure reclaim confirmed' if confirmed else 'extreme valid; 4H structure reclaim not yet confirmed'}

def _action_outcome(direction,entry,future,stop,target):
    price=_safe_float(future)
    if None in (price,entry,stop,target):return None
    if direction=='LONG':favorable=price>=target;adverse=price<=stop
    else:favorable=price<=target;adverse=price>=stop
    if favorable and adverse:return 'AMBIGUOUS'
    if favorable:return 'EXPANSION'
    if adverse:return 'FAIL'
    return None

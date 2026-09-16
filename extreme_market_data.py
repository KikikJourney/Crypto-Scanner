"""Build 15m/1h extreme-location and confirmation features from closed candles."""
from scanner_v2 import clamp

def _close(r): return float(r[4])
def _high(r): return float(r[2])
def _low(r): return float(r[3])

def _atr(rows,n=14):
    trs=[]; prev=None
    for r in rows:
        h,l,c=_high(r),_low(r),_close(r); trs.append(h-l if prev is None else max(h-l,abs(h-prev),abs(l-prev))); prev=c
    return sum(trs[-n:])/min(n,len(trs)) if trs else 0.0

def _aggregate_hourly(rows):
    out=[]; usable=len(rows)-len(rows)%4
    for i in range(0,usable,4):
        g=rows[i:i+4]; out.append([g[0][0],g[0][1],max(_high(x) for x in g),min(_low(x) for x in g),_close(g[-1]),sum(float(x[5]) for x in g)])
    return out

def _timestamp_iso(value):
    try:
        v=float(value)
        if v>10_000_000_000:v/=1000
        from datetime import datetime,timezone
        return datetime.fromtimestamp(v,tz=timezone.utc).isoformat()
    except (TypeError,ValueError,OSError): return ''

def build_features(rows,current_price=None):
    """Build structure from CLOSED candles and evaluate location/actionability at live price."""
    if not isinstance(rows,list) or len(rows)<192:return {'data_ok':False}
    rows=rows[-192:]; hourly=_aggregate_hourly(rows)
    if len(hourly)<48:return {'data_ok':False}
    h24=hourly[-24:]; h48=hourly[-48:]
    hi24=max(_high(x) for x in h24); lo24=min(_low(x) for x in h24); hi48=max(_high(x) for x in h48); lo48=min(_low(x) for x in h48)
    price=float(current_price) if current_price is not None else _close(rows[-1])
    if price<=0:return {'data_ok':False}
    p24_raw=(price-lo24)/(hi24-lo24) if hi24>lo24 else .5; p48_raw=(price-lo48)/(hi48-lo48) if hi48>lo48 else .5
    p24=clamp(p24_raw); p48=clamp(p48_raw)
    atr=_atr(hourly); dist_low=abs(price-lo24)/atr if atr else 99; dist_high=abs(hi24-price)/atr if atr else 99
    hourly_closes=[_close(x) for x in hourly]; move_low=max(0,(hourly_closes[-13]-price)/atr) if atr and len(hourly_closes)>=13 else 0; move_high=max(0,(price-hourly_closes[-13])/atr) if atr and len(hourly_closes)>=13 else 0
    recent=[_close(x) for x in hourly[-4:]]; turn_long=clamp((recent[-1]-min(recent[:-1]))/(atr or 1)); turn_short=clamp((max(recent[:-1])-recent[-1])/(atr or 1)); prior4=hourly[-5:-1]
    long_trigger=max(_high(x) for x in prior4); short_trigger=min(_low(x) for x in prior4)
    long_trigger_gap=max(0.0,(long_trigger-price)/(atr or 1)); short_trigger_gap=max(0.0,(price-short_trigger)/(atr or 1))
    return {'data_ok':True,'price':price,'atr':atr,'atr_pct':(atr/price*100) if price else 0.0,'atr_basis':'1H','timestamp':_timestamp_iso(rows[-1][0]),'h1_pos_24':p24,'h1_pos_48':p48,'h1_pos_24_raw':p24_raw,'h1_pos_48_raw':p48_raw,'dist_low_atr':dist_low,'dist_high_atr':dist_high,'move_into_low_atr':move_low,'move_into_high_atr':move_high,'turn_long':turn_long,'turn_short':turn_short,'extreme_low_24':lo24,'extreme_high_24':hi24,'long_trigger':long_trigger,'short_trigger':short_trigger,'trigger_gap_atr_long':long_trigger_gap,'trigger_gap_atr_short':short_trigger_gap}

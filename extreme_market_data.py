"""Build 15m/1h extreme-location features from closed candles."""
from scanner_v2 import clamp


def _close(r): return float(r[4])
def _high(r): return float(r[2])
def _low(r): return float(r[3])


def _atr(rows,n=14):
    trs=[]; prev=None
    for r in rows:
        h,l,c=_high(r),_low(r),_close(r)
        trs.append(h-l if prev is None else max(h-l,abs(h-prev),abs(l-prev))); prev=c
    return sum(trs[-n:])/min(n,len(trs)) if trs else 0.0


def _aggregate_hourly(rows):
    out=[]; usable=len(rows)-len(rows)%4
    for i in range(0,usable,4):
        g=rows[i:i+4]
        out.append([g[0][0],g[0][1],max(_high(x) for x in g),min(_low(x) for x in g),_close(g[-1]),sum(float(x[5]) for x in g)])
    return out


def build_features(rows,current_price=None):
    """Build features from CLOSED 15m candles only."""
    if not isinstance(rows,list) or len(rows)<192: return {'data_ok':False}
    rows=rows[-192:]; hourly=_aggregate_hourly(rows)
    if len(hourly)<48: return {'data_ok':False}
    h24=hourly[-24:]; h48=hourly[-48:]
    hi24=max(_high(x) for x in h24); lo24=min(_low(x) for x in h24); hi48=max(_high(x) for x in h48); lo48=min(_low(x) for x in h48)
    price=_close(rows[-1])
    p24=clamp((price-lo24)/(hi24-lo24)) if hi24>lo24 else .5
    p48=clamp((price-lo48)/(hi48-lo48)) if hi48>lo48 else .5
    atr=_atr(rows); dist_low=(price-lo24)/atr if atr else 99; dist_high=(hi24-price)/atr if atr else 99
    c=[_close(x) for x in rows]
    move_low=max(0,(c[-49]-price)/atr) if atr and len(c)>=49 else 0
    move_high=max(0,(price-c[-49])/atr) if atr and len(c)>=49 else 0
    turn_long=clamp((c[-1]-min(c[-4:-1]))/(atr or 1)); turn_short=clamp((max(c[-4:-1])-c[-1])/(atr or 1))
    return {'data_ok':True,'price':price,'atr':atr,'atr_pct':(atr/price*100) if price else 0.0,'h1_pos_24':p24,'h1_pos_48':p48,'dist_low_atr':dist_low,'dist_high_atr':dist_high,'move_into_low_atr':move_low,'move_into_high_atr':move_high,'turn_long':turn_long,'turn_short':turn_short}

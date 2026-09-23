"""Research-only adverse-excursion timing diagnostic for scalping forward-test evidence.

Measures when favorable 0.5R and adverse 1.0R excursions first occur after a
signal. This does not change scanner rules. The purpose is to distinguish
entry-timing/adverse-excursion problems from directional signal problems without
tuning a production threshold to a small sample.
"""
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

INPUT = Path("data/scalping_forward_test.csv")
MARKET = Path("data/scalping_market_5m.csv")
OUTPUT = Path("data/scalping_execution_timing_report.csv")
FAVORABLE_R = 0.5
ADVERSE_R = 1.0
HORIZON_MINUTES = 120
FIELDS = ["scope","sample","resolved","expansion","fail","favorable_0_5r_before_adverse_1r","adverse_1r_before_favorable_0_5r","neither_threshold_reached","mean_first_favorable_bar","mean_first_adverse_bar","median_first_favorable_bar","median_first_adverse_bar"]

def _f(v):
    try: return float(v)
    except (TypeError, ValueError): return None

def _ts(v):
    dt = datetime.fromisoformat(str(v).replace("Z","+00:00"))
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt

def _load(path):
    if not path.exists(): return []
    with path.open(newline="", encoding="utf-8") as f: return list(csv.DictReader(f))

def _future(action, market):
    start=_ts(action["timestamp"]); end=start+timedelta(minutes=HORIZON_MINUTES)
    return [r for r in market if r.get("provider")==action.get("provider") and r.get("symbol")==action.get("symbol") and start < _ts(r["timestamp"]) and (_ts(r["close_timestamp"]) if r.get("close_timestamp") else _ts(r["timestamp"])+timedelta(minutes=5)) <= end]

def _measure(action, market):
    entry,stop=_f(action.get("entry")),_f(action.get("stop"))
    if None in (entry,stop) or entry <= 0: return None
    risk=abs(entry-stop)
    if risk <= 0: return None
    first_favorable=first_adverse=None
    for index,candle in enumerate(_future(action,market),1):
        high,low=_f(candle.get("high")),_f(candle.get("low"))
        if None in (high,low): continue
        favorable_r=((high-entry)/risk) if action["direction"]=="LONG" else ((entry-low)/risk)
        adverse_r=((entry-low)/risk) if action["direction"]=="LONG" else ((high-entry)/risk)
        if first_favorable is None and favorable_r >= FAVORABLE_R: first_favorable=index
        if first_adverse is None and adverse_r >= ADVERSE_R: first_adverse=index
        if first_favorable is not None and first_adverse is not None: break
    return first_favorable,first_adverse

def _median(values):
    if not values: return ""
    values=sorted(values); return round(values[len(values)//2],4)

def _summarize(scope,rows,market):
    measured=[_measure(r,market) for r in rows]
    measured=[x for x in measured if x is not None]
    if not measured: return {k:(scope if k=="scope" else 0) for k in FIELDS}
    fav_before=sum(f is not None and (a is None or f<a) for f,a in measured)
    adv_before=sum(a is not None and (f is None or a<f) for f,a in measured)
    neither=sum(f is None and a is None for f,a in measured)
    fav=[f for f,_ in measured if f is not None]; adv=[a for _,a in measured if a is not None]
    outcomes=[r.get("first_touch") for r in rows]
    return {"scope":scope,"sample":len(rows),"resolved":len(measured),"expansion":outcomes.count("EXPANSION"),"fail":outcomes.count("FAIL"),"favorable_0_5r_before_adverse_1r":fav_before,"adverse_1r_before_favorable_0_5r":adv_before,"neither_threshold_reached":neither,"mean_first_favorable_bar":round(sum(fav)/len(fav),4) if fav else "","mean_first_adverse_bar":round(sum(adv)/len(adv),4) if adv else "","median_first_favorable_bar":_median(fav),"median_first_adverse_bar":_median(adv)}

def write(rows=None,market_rows=None,path=OUTPUT):
    rows=_load(INPUT) if rows is None else rows
    market=_load(MARKET) if market_rows is None else market_rows
    rows=[r for r in rows if r.get("first_touch") in {"EXPANSION","FAIL"}]
    scopes=[("ALL",rows),("LONG",[r for r in rows if r.get("direction")=="LONG"]),("SHORT",[r for r in rows if r.get("direction")=="SHORT"])]
    result=[_summarize(scope,subset,market) for scope,subset in scopes]
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    with Path(path).open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=FIELDS); w.writeheader(); w.writerows(result)
    return result

if __name__=="__main__":
    for row in write(): print(row)

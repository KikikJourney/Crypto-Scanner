"""Forward-test Alpha Opportunity Hunter signals against subsequent 15m candles.

This is shadow-only. It never changes scanner decisions or sends Telegram signals.
"""
from __future__ import annotations
import csv, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests

BASE="https://api.bitget.com"
PRODUCT="USDT-FUTURES"
INPUT=Path("data/alpha_opportunity_watch.csv")
OUTPUT=Path("data/alpha_forward_audit.csv")
TIMEOUT=10
WINDOWS=(1,2,4,8)

S=requests.Session()
S.headers.update({"User-Agent":"Zorathvael-Alpha-Forward-Audit/1.0"})

FIELDS=[
 "signal_timestamp","symbol","direction","state","alpha_score","entry",
 "age_minutes","window_15m","window_30m","window_1h","window_2h",
 "mfe_pct_2h","mae_pct_2h","result_2h","status"
]

def get(path, params=None, retries=3):
    last=None
    for attempt in range(retries+1):
        try:
            r=S.get(BASE+path,params=params,timeout=TIMEOUT)
            if r.status_code==429 or r.status_code>=500:
                raise RuntimeError(f"HTTP {r.status_code}")
            r.raise_for_status()
            data=r.json()
            if str(data.get("code")) not in {"00000","0","None"} and data.get("code") is not None:
                raise RuntimeError(f"Bitget {data.get('code')}: {data.get('msg')}")
            return data
        except (requests.RequestException,RuntimeError) as exc:
            last=exc
            if attempt<retries:
                time.sleep(min(4.0,0.5*(2**attempt)))
    raise last or RuntimeError("request failed")

def candles(symbol, limit=12):
    raw=get("/api/v2/mix/market/candles",{
        "symbol":symbol,"productType":PRODUCT,"granularity":"15m","limit":limit
    }).get("data",[])
    return list(reversed(raw))

def pct(entry,value,direction):
    if direction=="LONG":
        return (value/entry-1)*100
    return (entry/value-1)*100

def evaluate(row, rows):
    entry=float(row["price"])
    direction=row["direction"]
    signal_time=datetime.fromisoformat(row["timestamp"].replace("Z","+00:00"))
    now=datetime.now(timezone.utc)
    age=max(0.0,(now-signal_time).total_seconds()/60.0)

    # Only candles whose close starts after the signal timestamp are eligible.
    future=[r for r in rows if datetime.fromtimestamp(int(r[0])/1000,tz=timezone.utc)>signal_time]
    available={}
    for w in WINDOWS:
        if len(future)>=w:
            chunk=future[:w]
            highs=[float(r[2]) for r in chunk]
            lows=[float(r[3]) for r in chunk]
            close=float(chunk[-1][4])
            favorable=max(pct(entry,h,direction) for h in highs) if direction=="LONG" else max(pct(entry,l,direction) for l in lows)
            adverse=min(pct(entry,l,direction) for l in lows) if direction=="LONG" else min(pct(entry,h,direction) for h in highs)
            available[w]=(favorable,adverse,pct(entry,close,direction))

    labels={1:"window_15m",2:"window_30m",4:"window_1h",8:"window_2h"}
    out={labels[w]:(f"{available[w][2]:.4f}" if w in available else "") for w in WINDOWS}
    if 8 in available:
        mfe,mae,_=available[8]
        # Directional follow-through: positive close return at 2h.
        result="FOLLOW_THROUGH" if available[8][2]>0 else "FAIL"
        out.update(mfe_pct_2h=f"{mfe:.4f}",mae_pct_2h=f"{mae:.4f}",result_2h=result,status="COMPLETE")
    else:
        out.update(mfe_pct_2h="",mae_pct_2h="",result_2h="",status="PENDING")
    return age,out

def run():
    if not INPUT.exists():
        raise FileNotFoundError(INPUT)
    with INPUT.open(newline="",encoding="utf-8") as f:
        rows=list(csv.DictReader(f))
    results=[]
    for row in rows:
        try:
            age,metrics=evaluate(row,candles(row["symbol"]))
            results.append({
                "signal_timestamp":row["timestamp"],"symbol":row["symbol"],
                "direction":row["direction"],"state":row["state"],
                "alpha_score":row["alpha_score"],"entry":row["price"],
                "age_minutes":f"{age:.1f}",**metrics
            })
        except Exception as exc:
            results.append({
                "signal_timestamp":row["timestamp"],"symbol":row["symbol"],
                "direction":row["direction"],"state":row["state"],
                "alpha_score":row["alpha_score"],"entry":row["price"],
                "age_minutes":"","window_15m":"","window_30m":"",
                "window_1h":"","window_2h":"","mfe_pct_2h":"",
                "mae_pct_2h":"","result_2h":"","status":f"ERROR:{exc}"
            })
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    with OUTPUT.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=FIELDS); w.writeheader(); w.writerows(results)
    complete=[r for r in results if r["status"]=="COMPLETE"]
    follow=sum(r["result_2h"]=="FOLLOW_THROUGH" for r in complete)
    print(f"Alpha forward audit: {len(results)} signals | {len(complete)} complete | {follow} follow-through")
    for r in results:
        print(r["state"],r["direction"],r["symbol"],r["status"],r["window_2h"])
    return results

if __name__=="__main__":
    run()

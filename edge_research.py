"""Historical edge research for the Alpha Edge Council.

This is research only: it never emits live Telegram actions and never changes
production geometry. It evaluates the exact event family used by the scanner
on closed 5m candles and separates train/test periods.
"""
import csv, json, math, os
from pathlib import Path
from datetime import datetime, timezone
import requests

BASE=os.getenv("BINANCE_BASE_URL","https://fapi.binance.com").rstrip("/")
S=requests.Session(); S.headers.update({"User-Agent":"Zorathvael-Edge-Research/1.0"})
SYMBOLS=int(os.getenv("EDGE_RESEARCH_SYMBOLS","20"))
LIMIT=1500
HORIZON=48

def f(x,d=0):
    try:return float(x)
    except:return d

def get(path,p):
    r=S.get(BASE+path,params=p,timeout=15); r.raise_for_status(); return r.json()

def bars(symbol):
    rows=get("/fapi/v1/klines",{"symbol":symbol,"interval":"5m","limit":LIMIT})
    return [{"t":int(x[0]),"o":f(x[1]),"h":f(x[2]),"l":f(x[3]),"c":f(x[4]),"v":f(x[5])} for x in rows[:-1]]

def event(r,i,d):
    if i<60 or i+HORIZON>=len(r):return None
    w=r[i-36:i]
    hi=max(x["h"] for x in w); lo=min(x["l"] for x in w); span=hi-lo
    if span<=0:return None
    prev=r[i-7:i]; x=r[i]
    if d=="LONG":
        sweep=x["l"]<min(z["l"] for z in prev) and x["c"]>min(z["l"] for z in prev)
        impulse=x["c"]>x["o"] and (x["c"]-x["o"])/x["o"]>.0015
        zlo,zhi=hi-span*.786,hi-span*.50
    else:
        sweep=x["h"]>max(z["h"] for z in prev) and x["c"]<max(z["h"] for z in prev)
        impulse=x["c"]<x["o"] and (x["o"]-x["c"])/x["o"]>.0015
        zlo,zhi=lo+span*.50,lo+span*.786
    zone_lo,zone_hi=min(zlo,zhi),max(zlo,zhi)
    # Require the next bars to enter the calibrated pullback zone.
    fill=None
    for j in range(i+1,min(i+7,len(r))):
        if zone_lo<=r[j]["c"]<=zone_hi:
            fill=j;break
    if fill is None or not sweep or not impulse:return None
    entry=(zone_lo+zone_hi)/2
    sl=entry*(.995 if d=="LONG" else 1.005)
    tp=entry*(1.015 if d=="LONG" else .985)
    fut=r[fill+1:fill+HORIZON+1]
    if not fut:return None
    mfe=max(((z["h"]-entry)/entry if d=="LONG" else (entry-z["l"])/entry) for z in fut)
    mae=max(((entry-z["l"])/entry if d=="LONG" else (z["h"]-entry)/entry) for z in fut)
    outcome="UNRESOLVED"
    net=0
    ts=""
    for z in fut:
        hit_tp=z["h"]>=tp if d=="LONG" else z["l"]<=tp
        hit_sl=z["l"]<=sl if d=="LONG" else z["h"]>=sl
        if hit_tp and hit_sl:
            outcome="AMBIGUOUS"; net=0; ts=str(z["t"]); break
        if hit_tp:
            outcome="WIN"; net=1; ts=str(z["t"]); break
        if hit_sl:
            outcome="LOSS"; net=-1; ts=str(z["t"]); break
    return {"timestamp":r[fill]["t"],"direction":d,"regime":"unknown","net_r":net,
            "outcome":outcome,"mfe_pct":mfe*100,"mae_pct":mae*100,"symbol":""}

def main():
    info=get("/fapi/v1/exchangeInfo",{})
    active=[x["symbol"] for x in info["symbols"] if x.get("status")=="TRADING" and x.get("contractType")=="PERPETUAL" and x.get("quoteAsset")=="USDT"]
    ticks=get("/fapi/v1/ticker/24hr",{})
    tv={x["symbol"]:f(x.get("quoteVolume")) for x in ticks}
    syms=sorted([s for s in active if tv.get(s,0)>10_000_000],key=lambda s:tv[s],reverse=True)[:SYMBOLS]
    rows=[]
    for s in syms:
        try:
            r=bars(s)
            split=int(len(r)*.70)
            for d in ("LONG","SHORT"):
                for i in range(60,split): 
                    x=event(r,i,d)
                    if x:x.update(symbol=s,regime="train");rows.append(x)
                for i in range(split,len(r)-HORIZON-1):
                    x=event(r,i,d)
                    if x:x.update(symbol=s,regime="test");rows.append(x)
        except Exception as e:
            print("WARN",s,type(e).__name__,str(e)[:120])
    out=[]
    for regime in ("train","test","all"):
        subset=rows if regime=="all" else [x for x in rows if x["regime"]==regime]
        resolved=[x for x in subset if x["outcome"] in ("WIN","LOSS")]
        vals=[x["net_r"] for x in resolved]
        wins=sum(v>0 for v in vals); losses=sum(v<0 for v in vals)
        gw=sum(v for v in vals if v>0); gl=-sum(v for v in vals if v<0)
        peak=eq=dd=0
        for v in vals:
            eq+=v;peak=max(peak,eq);dd=max(dd,peak-eq)
        out.append({"sample":len(subset),"resolved":len(resolved),"wins":wins,"losses":losses,
                    "win_rate_pct":round(100*wins/len(resolved),3) if resolved else 0,
                    "expectancy_r":round(sum(vals)/len(vals),5) if vals else 0,
                    "profit_factor":round(gw/gl,4) if gl else None,
                    "max_drawdown_r":round(dd,4),"avg_mfe_pct":round(sum(x["mfe_pct"] for x in resolved)/len(resolved),4) if resolved else 0,
                    "avg_mae_pct":round(sum(x["mae_pct"] for x in resolved)/len(resolved),4) if resolved else 0,
                    "regime":regime})
    Path("edge_evidence.json").write_text(json.dumps({"version":"edge-research-v1","generated_at":datetime.now(timezone.utc).isoformat(),"summary":out,"events":rows},indent=2),encoding="utf-8")
    print(json.dumps({"symbols":len(syms),"events":len(rows),"summary":out},indent=2))

if __name__=="__main__":main()

"""Historical thesis laboratory.

Research-only. Does not change production scoring, thresholds, entries, SL or TP.
Uses persisted point-in-time action + forward-test evidence to test whether
entry-location and signal evidence agree before any production change.

Outputs a compact evidence matrix suitable for walk-forward review.
"""
import csv
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ACTION = Path("data/scalping_action_history.csv")
FORWARD = Path("data/scalping_forward_test.csv")
MARKET = Path("data/scalping_market_5m.csv")
REPORT = Path("data/historical_thesis_lab.csv")
SUMMARY = Path("data/historical_thesis_lab_summary.csv")

OUTCOMES = {"EXPANSION", "FAIL", "AMBIGUOUS"}

def f(v):
    try: return float(v)
    except (TypeError, ValueError): return None

def ts(v):
    d = datetime.fromisoformat(str(v).replace("Z","+00:00"))
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d

def load(p):
    if not p.exists(): return []
    with p.open(newline="",encoding="utf-8") as h: return list(csv.DictReader(h))

def close_ts(r):
    return ts(r["close_timestamp"]) if r.get("close_timestamp") else ts(r["timestamp"])+timedelta(minutes=5)

def bucket(v, edges, labels):
    x=f(v)
    if x is None: return "UNKNOWN"
    for edge,label in zip(edges,labels):
        if x < edge: return label
    return labels[-1] + "+"

def location(method_rows, direction, price):
    if not method_rows or price is None: return None
    lows=[f(r.get("low")) for r in method_rows]
    highs=[f(r.get("high")) for r in method_rows]
    lows=[x for x in lows if x is not None]; highs=[x for x in highs if x is not None]
    if not lows or not highs or max(highs)==min(lows): return None
    lo,hi=min(lows),max(highs)
    return (price-lo)/(hi-lo)

def pre_market(action, market):
    t=ts(action["timestamp"])
    rows=[r for r in market if r.get("provider")==action.get("provider")
          and r.get("symbol")==action.get("symbol") and close_ts(r)<=t]
    return sorted(rows,key=lambda r:close_ts(r))

def extremes(rows,n,direction):
    w=rows[-n:]
    vals=[f(r.get("low" if direction=="LONG" else "high")) for r in w]
    vals=[x for x in vals if x is not None]
    return min(vals) if direction=="LONG" and vals else max(vals) if vals else None

def outcome_value(r):
    o=r.get("first_touch")
    if o=="EXPANSION":
        return f(r.get("outcome_r"))
    if o=="FAIL": return -1.0
    return 0.0 if o=="AMBIGUOUS" else None

def summarize(rows, key):
    groups=defaultdict(list)
    for r in rows: groups[key(r)].append(r)
    out=[]
    for k,v in sorted(groups.items(),key=lambda x:str(x[0])):
        resolved=[r for r in v if r.get("first_touch") in OUTCOMES]
        vals=[outcome_value(r) for r in resolved]
        vals=[x for x in vals if x is not None]
        wins=sum(r.get("first_touch")=="EXPANSION" for r in resolved)
        losses=sum(r.get("first_touch")=="FAIL" for r in resolved)
        out.append({
            "cohort":str(k),"sample":len(v),"resolved":len(resolved),
            "wins":wins,"losses":losses,
            "win_rate_pct":round(100*wins/len(resolved),3) if resolved else 0,
            "expectancy_r":round(sum(vals)/len(vals),5) if vals else 0,
            "mfe_mean_pct":round(sum(f(r.get("mfe_pct")) or 0 for r in resolved)/len(resolved),5) if resolved else 0,
            "mae_mean_pct":round(sum(f(r.get("mae_pct")) or 0 for r in resolved)/len(resolved),5) if resolved else 0,
        })
    return out

def main():
    actions={r.get("id"):r for r in load(ACTION)}
    forward=load(FORWARD)
    market=load(MARKET)
    rows=[]
    for ft in forward:
        if ft.get("strategy_version")!="scalp-structure-v1": continue
        a=actions.get(ft.get("id"),ft)
        pre=pre_market(a,market)
        price=f(a.get("entry"))
        l40=extremes(pre,40,a.get("direction"))
        l100=extremes(pre,100,a.get("direction"))
        loc40=location(pre[-40:],a.get("direction"),price) if len(pre)>=40 else None
        loc100=location(pre[-100:],a.get("direction"),price) if len(pre)>=100 else None
        rows.append({
            "id":ft.get("id",""),"timestamp":ft.get("timestamp",""),"symbol":ft.get("symbol",""),
            "direction":ft.get("direction",""),"confidence":ft.get("confidence",""),
            "location_15m":ft.get("location_15m",""),"reversal_5m":ft.get("reversal_5m",""),
            "exhaustion_15m":ft.get("exhaustion_15m",""),"base_15m":ft.get("base_15m",""),
            "structure_shift_5m":ft.get("structure_shift_5m",""),"reversal_trigger_5m":ft.get("reversal_trigger_5m",""),
            "early_reversal_score":ft.get("early_reversal_score",""),"entry":ft.get("entry",""),
            "low40":l40 if l40 is not None else "","high100_anchor":l100 if l100 is not None else "",
            "range_pos40":round(loc40,5) if loc40 is not None else "",
            "range_pos100":round(loc100,5) if loc100 is not None else "",
            "first_touch":ft.get("first_touch",""),"outcome_r":ft.get("outcome_r",""),
            "mfe_pct":ft.get("mfe_pct",""),"mae_pct":ft.get("mae_pct",""),
        })
    REPORT.parent.mkdir(parents=True,exist_ok=True)
    fields=list(rows[0].keys()) if rows else []
    with REPORT.open("w",newline="",encoding="utf-8") as h:
        w=csv.DictWriter(h,fieldnames=fields); w.writeheader(); w.writerows(rows)
    specs=[
        ("direction",lambda r:r["direction"]),
        ("confidence",lambda r:bucket(r["confidence"],[85,90],["<85","85-89.9","90-100"])),
        ("location_15m",lambda r:r["location_15m"]),
        ("reversal_5m",lambda r:r["reversal_5m"]),
        ("exhaustion_15m",lambda r:r["exhaustion_15m"]),
        ("base_15m",lambda r:r["base_15m"]),
        ("structure_shift_5m",lambda r:r["structure_shift_5m"]),
        ("reversal_trigger_5m",lambda r:r["reversal_trigger_5m"]),
        ("range_pos40",lambda r:bucket(r["range_pos40"],[0.2,0.4,0.6,0.8],["0-.2",".2-.4",".4-.6",".6-.8",".8-1"])),
        ("range_pos100",lambda r:bucket(r["range_pos100"],[0.2,0.4,0.6,0.8],["0-.2",".2-.4",".4-.6",".6-.8",".8-1"])),
    ]
    summary=[]
    for name,fn in specs:
        for x in summarize(rows,fn):
            x["feature"]=name; summary.append(x)
    with SUMMARY.open("w",newline="",encoding="utf-8") as h:
        fields=["feature","cohort","sample","resolved","wins","losses","win_rate_pct","expectancy_r","mfe_mean_pct","mae_mean_pct"]
        w=csv.DictWriter(h,fieldnames=fields); w.writeheader(); w.writerows(summary)
    print("HISTORICAL THESIS LAB")
    print(f"signals={len(rows)} market_rows={len(market)}")
    for feature in ["direction","confidence","location_15m","range_pos40","range_pos100"]:
        print(feature)
        for x in summary:
            if x["feature"]==feature: print(x)

if __name__=="__main__":
    main()

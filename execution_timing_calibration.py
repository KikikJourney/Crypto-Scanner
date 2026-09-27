"""Historical entry-timing calibration shadow.

Tests WHEN to execute independently of entry geometry/SL/TP design.
It sweeps closed 5m confirmation offsets after each action timestamp.
No threshold/scoring changes and no production rule is selected from a
small sample; the report exposes timing evidence for an auditable decision.
"""
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

ACTION_HISTORY_FILE = Path("data/scalping_action_history.csv")
MARKET_FILE = Path("data/scalping_market_5m.csv")
REPORT_FILE = Path("data/scalping_timing_calibration_report.csv")
DETAIL_FILE = Path("data/scalping_timing_calibration.csv")
STRATEGY_VERSION = "scalp-structure-v1"
HORIZON_MINUTES = 120
OFFSETS = (0, 1, 2, 3, 4)
MIN_SAMPLE_FOR_REVIEW = 30

FIELDS = ["offset_bars","offset_minutes","sample","eligible","resolved","wins","losses","ambiguous","unresolved","win_rate_pct","net_r","expectancy_r","avg_entry_delay_min"]
DETAIL_FIELDS = ["id","timestamp","symbol","direction","offset_bars","candidate_timestamp","candidate_entry","baseline_entry","baseline_stop","baseline_target","status","outcome","outcome_r","outcome_timestamp","reason"]

def _f(v):
    try: return float(v)
    except (TypeError, ValueError): return None

def _ts(v):
    dt = datetime.fromisoformat(str(v).replace("Z","+00:00"))
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt

def _close_ts(row):
    return _ts(row["close_timestamp"]) if row.get("close_timestamp") else _ts(row["timestamp"])+timedelta(minutes=5)

def _load(path):
    if not path.exists(): return []
    with path.open(newline="",encoding="utf-8") as f: return list(csv.DictReader(f))

def _touch(direction,candle,stop,target):
    high,low=_f(candle.get("high")),_f(candle.get("low"))
    if None in (high,low,stop,target): return None
    favorable=high>=target if direction=="LONG" else low<=target
    adverse=low<=stop if direction=="LONG" else high>=stop
    if favorable and adverse: return "AMBIGUOUS"
    if favorable: return "EXPANSION"
    if adverse: return "FAIL"
    return None

def _future(action,market):
    start=_ts(action["timestamp"]); end=start+timedelta(minutes=HORIZON_MINUTES)
    return [r for r in sorted(market,key=lambda x:_ts(x["timestamp"]))
            if r.get("provider")==action.get("provider")
            and r.get("symbol")==action.get("symbol")
            and _ts(r["timestamp"])>start and _close_ts(r)<=end]

def calibrate(actions=None,market_rows=None):
    actions=_load(ACTION_HISTORY_FILE) if actions is None else actions
    market=_load(MARKET_FILE) if market_rows is None else market_rows
    actions=[r for r in actions if r.get("strategy_version")==STRATEGY_VERSION and r.get("direction") in {"LONG","SHORT"}]
    details=[]
    for action in sorted(actions,key=lambda r:r.get("timestamp","")):
        future=_future(action,market)
        entry0,stop,target=_f(action.get("entry")),_f(action.get("stop")),_f(action.get("target"))
        for offset in OFFSETS:
            row={k:"" for k in DETAIL_FIELDS}
            row.update({"id":action.get("id",""),"timestamp":action.get("timestamp",""),"symbol":action.get("symbol",""),"direction":action.get("direction",""),"offset_bars":offset,"status":"SKIPPED"})
            if None in (entry0,stop,target) or len(future)<=offset:
                row["reason"]="insufficient future candles or invalid execution fields"; details.append(row); continue
            candle=future[offset]; candidate=_f(candle.get("close"))
            if candidate is None or candidate<=0:
                row["reason"]="invalid candidate close"; details.append(row); continue
            direction=action["direction"]
            preserved=candidate>=entry0 if direction=="LONG" else candidate<=entry0
            candidate_touch=_touch(direction,candle,stop,target)
            row.update({"candidate_timestamp":_close_ts(candle).isoformat(),"candidate_entry":f"{candidate:.12g}","baseline_entry":f"{entry0:.12g}","baseline_stop":f"{stop:.12g}","baseline_target":f"{target:.12g}"})
            if not preserved:
                row["reason"]="closed candle did not preserve signal direction"; details.append(row); continue
            if candidate_touch:
                row["reason"]="candidate candle also touched baseline stop/target; intrabar order ambiguous"; details.append(row); continue
            risk=entry0-stop if direction=="LONG" else stop-entry0
            if risk<=0:
                row["reason"]="non-positive baseline risk"; details.append(row); continue
            reward=abs((target-candidate)/risk)
            row["status"]="ELIGIBLE_UNRESOLVED"
            for c in future[offset+1:]:
                outcome=_touch(direction,c,stop,target)
                if outcome:
                    row.update({"status":"RESOLVED","outcome":outcome,"outcome_r":f"{reward:.6f}" if outcome=="EXPANSION" else "-1.0" if outcome=="FAIL" else "","outcome_timestamp":_close_ts(c).isoformat()})
                    break
            details.append(row)
    return details

def _summary(details):
    rows=[]
    for offset in OFFSETS:
        subset=[r for r in details if int(r["offset_bars"])==offset]
        resolved=[r for r in subset if r["outcome"] in {"EXPANSION","FAIL","AMBIGUOUS"}]
        vals=[_f(r.get("outcome_r")) or 0.0 if r["outcome"]=="EXPANSION" else -1.0 if r["outcome"]=="FAIL" else 0.0 for r in resolved]
        delays=[(int(r["offset_bars"])+1)*5 for r in subset if r["status"]!="SKIPPED"]
        rows.append({"offset_bars":offset,"offset_minutes":offset*5,"sample":len(subset),"eligible":sum(r["status"]!="SKIPPED" for r in subset),"resolved":len(resolved),"wins":sum(r["outcome"]=="EXPANSION" for r in resolved),"losses":sum(r["outcome"]=="FAIL" for r in resolved),"ambiguous":sum(r["outcome"]=="AMBIGUOUS" for r in resolved),"unresolved":sum(r["status"]=="ELIGIBLE_UNRESOLVED" for r in subset),"win_rate_pct":round(100*sum(r["outcome"]=="EXPANSION" for r in resolved)/len(resolved),4) if resolved else 0.0,"net_r":round(sum(vals),4),"expectancy_r":round(sum(vals)/len(resolved),6) if resolved else 0.0,"avg_entry_delay_min":round(sum(delays)/len(delays),2) if delays else 0.0})
    return rows

def write(details=None):
    details=calibrate() if details is None else details
    summary=_summary(details)
    REPORT_FILE.parent.mkdir(parents=True,exist_ok=True)
    with REPORT_FILE.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=FIELDS); w.writeheader(); w.writerows(summary)
    with DETAIL_FILE.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=DETAIL_FIELDS); w.writeheader(); w.writerows(details)
    return summary

if __name__=="__main__":
    for row in write(): print("Timing calibration:",row)

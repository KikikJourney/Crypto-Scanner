"""Shadow execution calibration for early-reversal scalping actions.

This module does not change live execution rules. It evaluates a conservative,
closed-candle confirmation model against persisted current-strategy actions.
"""
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

ACTION_HISTORY_FILE = Path("data/scalping_action_history.csv")
MARKET_FILE = Path("data/scalping_market_5m.csv")
FORWARD_FILE = Path("data/scalping_forward_test.csv")
REPORT_FILE = Path("data/scalping_execution_calibration_report.csv")
DETAIL_FILE = Path("data/scalping_execution_calibration.csv")
CURRENT_STRATEGY_VERSION = "scalp-structure-v1"
HORIZON_MINUTES = 120
MAX_RISK_PCT = 2.0
REWARD_R = 2.0

REPORT_FIELDS = ["model","sample","eligible","resolved","wins","losses","ambiguous","unresolved","skipped","win_rate_pct","net_r","expectancy_r","max_drawdown_r","max_risk_pct","min_sample_for_review"]
DETAIL_FIELDS = ["id","timestamp","symbol","direction","confidence","baseline_outcome","confirmation_timestamp","confirmation_close","calibrated_entry","calibrated_stop","calibrated_target","risk_pct","status","outcome","outcome_r","outcome_timestamp","reason"]

def _f(v):
    try: return float(v)
    except (TypeError, ValueError): return None

def _ts(v):
    dt = datetime.fromisoformat(str(v).replace("Z","+00:00"))
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt

def _load(path):
    if not path.exists(): return []
    with path.open(newline="", encoding="utf-8") as f: return list(csv.DictReader(f))

def _close_ts(row):
    return _ts(row["close_timestamp"]) if row.get("close_timestamp") else _ts(row["timestamp"])+timedelta(minutes=5)

def _future(action, market):
    ts=_ts(action["timestamp"]); end=ts+timedelta(minutes=HORIZON_MINUTES)
    return [r for r in market if r.get("provider")==action.get("provider") and r.get("symbol")==action.get("symbol") and ts < _ts(r["timestamp"]) and _close_ts(r)<=end]

def _touch(direction,candle,stop,target):
    high,low=_f(candle.get("high")),_f(candle.get("low"))
    if None in (high,low,stop,target): return None
    favorable=high>=target if direction=="LONG" else low<=target
    adverse=low<=stop if direction=="LONG" else high>=stop
    if favorable and adverse: return "AMBIGUOUS"
    if favorable: return "EXPANSION"
    if adverse: return "FAIL"
    return None

def calibrate(actions=None,market_rows=None):
    actions=_load(ACTION_HISTORY_FILE) if actions is None else actions
    market=_load(MARKET_FILE) if market_rows is None else market_rows
    actions=[r for r in actions if r.get("strategy_version")==CURRENT_STRATEGY_VERSION and r.get("direction") in {"LONG","SHORT"}]
    market=sorted(market,key=lambda r:_ts(r["timestamp"]))
    baseline={r.get("id"):r for r in _load(FORWARD_FILE)}
    detail=[]
    for action in sorted(actions,key=lambda r:r.get("timestamp","")):
        row={k:"" for k in DETAIL_FIELDS}
        row.update({"id":action.get("id",""),"timestamp":action.get("timestamp",""),"symbol":action.get("symbol",""),"direction":action.get("direction",""),"confidence":action.get("confidence",""),"baseline_outcome":baseline.get(action.get("id"),{}).get("first_touch",""),"status":"SKIPPED"})
        candles=_future(action,market)
        if len(candles)<2: row["reason"]="insufficient future closed candles"; detail.append(row); continue
        c=candles[0]; entry0,stop0,target0,close=_f(action.get("entry")),_f(action.get("stop")),_f(action.get("target")),_f(c.get("close"))
        if None in (entry0,stop0,target0,close): row["reason"]="invalid numeric execution fields"; detail.append(row); continue
        direction=action["direction"]; confirmed=close>=entry0 if direction=="LONG" else close<=entry0
        if not confirmed: row["reason"]="first closed 5m confirmation did not preserve direction"; detail.append(row); continue
        if _touch(direction,c,stop0,target0): row["reason"]="confirmation candle already touched original stop/target"; detail.append(row); continue
        low,high=_f(c.get("low")),_f(c.get("high"))
        if None in (low,high): row["reason"]="invalid confirmation candle"; detail.append(row); continue
        entry=close; stop=min(stop0,low) if direction=="LONG" else max(stop0,high); risk=entry-stop if direction=="LONG" else stop-entry
        if risk<=0: row["reason"]="non-positive calibrated risk"; detail.append(row); continue
        risk_pct=risk/entry*100
        if risk_pct>MAX_RISK_PCT: row["reason"]="calibrated stop exceeds 2% risk cap"; detail.append(row); continue
        target=entry+REWARD_R*risk if direction=="LONG" else entry-REWARD_R*risk
        row.update({"confirmation_timestamp":_close_ts(c).isoformat(),"confirmation_close":f"{close:.12g}","calibrated_entry":f"{entry:.12g}","calibrated_stop":f"{stop:.12g}","calibrated_target":f"{target:.12g}","risk_pct":f"{risk_pct:.6f}","status":"ELIGIBLE_UNRESOLVED","reason":"confirmed 5m close; calibrated execution"})
        for candle in candles[1:]:
            outcome=_touch(direction,candle,stop,target)
            if outcome:
                row.update({"outcome":outcome,"status":"RESOLVED","outcome_r":"2.0" if outcome=="EXPANSION" else "-1.0" if outcome=="FAIL" else "","outcome_timestamp":_close_ts(candle).isoformat()}); break
        detail.append(row)
    return detail

def _summary(detail):
    resolved=[r for r in detail if r["outcome"] in {"EXPANSION","FAIL","AMBIGUOUS"}]
    vals=[2.0 if r["outcome"]=="EXPANSION" else -1.0 if r["outcome"]=="FAIL" else 0.0 for r in resolved]
    eq=peak=dd=0.0
    for v in vals:
        eq+=v; peak=max(peak,eq); dd=min(dd,eq-peak)
    return {"sample":len(detail),"eligible":sum(r["status"]!="SKIPPED" for r in detail),"resolved":len(resolved),"wins":sum(r["outcome"]=="EXPANSION" for r in resolved),"losses":sum(r["outcome"]=="FAIL" for r in resolved),"ambiguous":sum(r["outcome"]=="AMBIGUOUS" for r in resolved),"unresolved":sum(r["status"]=="ELIGIBLE_UNRESOLVED" for r in detail),"skipped":sum(r["status"]=="SKIPPED" for r in detail),"win_rate_pct":round(100*sum(r["outcome"]=="EXPANSION" for r in resolved)/len(resolved),4) if resolved else 0.0,"net_r":round(sum(vals),4),"expectancy_r":round(sum(vals)/len(resolved),6) if resolved else 0.0,"max_drawdown_r":round(dd,4),"max_risk_pct":MAX_RISK_PCT,"min_sample_for_review":30}

def write(detail=None):
    detail=calibrate() if detail is None else detail
    REPORT_FILE.parent.mkdir(parents=True,exist_ok=True)
    base=_load(FORWARD_FILE); br=[r for r in base if r.get("first_touch") in {"EXPANSION","FAIL","AMBIGUOUS"}]; bv=[2.0 if r["first_touch"]=="EXPANSION" else -1.0 if r["first_touch"]=="FAIL" else 0.0 for r in br]
    eq=peak=baseline_dd=0.0
    for value in bv:
        eq += value
        peak = max(peak, eq)
        baseline_dd = min(baseline_dd, eq - peak)
    baseline={"model":"CURRENT_BASELINE","sample":len(base),"eligible":len(base),"resolved":len(br),"wins":sum(r["first_touch"]=="EXPANSION" for r in br),"losses":sum(r["first_touch"]=="FAIL" for r in br),"ambiguous":sum(r["first_touch"]=="AMBIGUOUS" for r in br),"unresolved":len(base)-len(br),"skipped":0,"win_rate_pct":round(100*sum(r["first_touch"]=="EXPANSION" for r in br)/len(br),4) if br else 0.0,"net_r":round(sum(bv),4),"expectancy_r":round(sum(bv)/len(br),6) if br else 0.0,"max_drawdown_r":round(baseline_dd,4),"max_risk_pct":"current","min_sample_for_review":30}
    s=_summary(detail); calibrated={"model":"CONFIRM_5M_CALIBRATED",**s}
    with REPORT_FILE.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=REPORT_FIELDS); w.writeheader(); w.writerow(baseline); w.writerow(calibrated)
    with DETAIL_FILE.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=DETAIL_FIELDS); w.writeheader(); w.writerows(detail)
    return s

if __name__=="__main__":
    s=write(); print(f"Execution calibration shadow: eligible={s['eligible']} resolved={s['resolved']} wins={s['wins']} losses={s['losses']} net_r={s['net_r']:.2f} expectancy_r={s['expectancy_r']:.4f} skipped={s['skipped']}")

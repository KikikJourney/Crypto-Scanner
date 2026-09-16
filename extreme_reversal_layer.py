"""Extreme-location reversal layer with event-level forward-test accounting."""
import csv
from datetime import datetime,timedelta
from pathlib import Path
from scanner_v2 import clamp
EXTREME_FORWARD_FILE=Path('data/extreme_reversal_forward_test.csv');EXTREME_SNAPSHOT_FILE=Path('data/extreme_market_snapshots.csv')
HORIZONS=(1,4,12,24);MIN_EXTREME_SCORE=70.0;MAX_1H_POS_LONG=.30;MIN_1H_POS_SHORT=.70;MAX_24H_POS_LONG=.25;MIN_24H_POS_SHORT=.75;MAX_ATR_FROM_LOW=1.;MAX_ATR_FROM_HIGH=1.;MIN_MOVE_ATR=.75;MIN_TURN=.25;EVENT_GAP_HOURS=2
CSV_FIELDS=['id','timestamp','symbol','provider','direction','signal','score','price','atr_pct','trigger','action_stop','action_target','action_risk_pct','action_reward_r','event_id','event_role','h1','h4','h12','h24'];SNAPSHOT_FIELDS=['id','timestamp','symbol','provider','price']
def _score_long(f):
    if not f or f.get('data_ok') is not True:return None
    p,p24,d,m,t=f['h1_pos_48'],f['h1_pos_24'],f['dist_low_atr'],f['move_into_low_atr'],f['turn_long'];loc=.45*clamp((MAX_1H_POS_LONG-p)/MAX_1H_POS_LONG)+.35*clamp((MAX_24H_POS_LONG-p24)/MAX_24H_POS_LONG)+.20*clamp((MAX_ATR_FROM_LOW-d)/MAX_ATR_FROM_LOW);return round(100*(.70*loc+.20*clamp(m/3)+.10*clamp(t)),1)
def _score_short(f):
    if not f or f.get('data_ok') is not True:return None
    p,p24,d,m,t=f['h1_pos_48'],f['h1_pos_24'],f['dist_high_atr'],f['move_into_high_atr'],f['turn_short'];loc=.45*clamp((p-MIN_1H_POS_SHORT)/(1-MIN_1H_POS_SHORT))+.35*clamp((p24-MIN_24H_POS_SHORT)/(1-MIN_24H_POS_SHORT))+.20*clamp((MAX_ATR_FROM_HIGH-d)/MAX_ATR_FROM_HIGH);return round(100*(.70*loc+.20*clamp(m/3)+.10*clamp(t)),1)
def classify(features):
    if not features or features.get('data_ok') is not True:return {'status':'DATA-LIMITED','direction':'NONE','score':None,'long_score':None,'short_score':None,'blocker':'15m/1h extreme data unavailable'}
    ls,ss=_score_long(features),_score_short(features);lg=features['h1_pos_48']<=MAX_1H_POS_LONG and features['h1_pos_24']<=MAX_24H_POS_LONG and 0<=features['dist_low_atr']<=MAX_ATR_FROM_LOW and features['move_into_low_atr']>=MIN_MOVE_ATR and features['turn_long']>=MIN_TURN;sg=features['h1_pos_48']>=MIN_1H_POS_SHORT and features['h1_pos_24']>=MIN_24H_POS_SHORT and 0<=features['dist_high_atr']<=MAX_ATR_FROM_HIGH and features['move_into_high_atr']>=MIN_MOVE_ATR and features['turn_short']>=MIN_TURN
    c=[]
    if lg and ls>=MIN_EXTREME_SCORE:c.append(('LONG',ls))
    if sg and ss>=MIN_EXTREME_SCORE:c.append(('SHORT',ss))
    if c:
        side,score=max(c,key=lambda x:(x[1],x[0]=='LONG'));return {'status':f'EXTREME REVERSAL {side}','direction':side,'score':score,'long_score':ls,'short_score':ss,'blocker':'none'}
    return {'status':'MONITOR EXTREME','direction':'NONE','score':max(ls,ss),'long_score':ls,'short_score':ss,'blocker':'extreme gate not met'}
def signal_row(result,features,timestamp):
    d=classify(features)
    if not d['status'].startswith('EXTREME REVERSAL'):return None
    from actionable_reversal_layer import build_action_plan
    p=build_action_plan(features,d['direction']);ts=features.get('timestamp') or timestamp
    return {'id':f'{ts}_{result["symbol"]}_EXTREME','timestamp':ts,'symbol':result['symbol'],'provider':result['provider'],'direction':d['direction'],'signal':d['status'],'score':d['score'],'price':features['price'],'atr_pct':features['atr_pct'],'trigger':p.get('trigger',''),'action_stop':p.get('stop',''),'action_target':p.get('target',''),'action_risk_pct':p.get('risk_pct',''),'action_reward_r':p.get('reward_r',''),'event_id':'','event_role':'','h1':'','h4':'','h12':'','h24':''}
def snapshot_row(result,features,timestamp):
    ts=features.get('timestamp') or timestamp;return {'id':f'{ts}_{result["symbol"]}','timestamp':ts,'symbol':result['symbol'],'provider':result['provider'],'price':features['price']}
def _parse_ts(v):return datetime.fromisoformat(v.replace('Z','+00:00'))
def _outcome(direction,entry,future,atr_pct):
    move=(future-entry)/entry*100;fav=move>=2*atr_pct if direction=='LONG' else move<=-2*atr_pct;adv=move<=-atr_pct if direction=='LONG' else move>=atr_pct
    if fav and adv:return 'AMBIGUOUS'
    if fav:return 'EXPANSION'
    if adv:return 'FAIL'
    return None
def _assign_events(rows):
    ordered=sorted(rows,key=lambda r:(_parse_ts(r['timestamp']),r.get('symbol',''),r.get('direction','')));last={}
    for row in ordered:
        key=(row.get('symbol',''),row.get('direction',''));ts=_parse_ts(row['timestamp']);prev=last.get(key)
        if prev is None or ts-prev[0]>timedelta(hours=EVENT_GAP_HOURS):eid=f"{row['symbol']}_{row['direction']}_{row['timestamp']}";row['event_role']='PRIMARY'
        else:eid=prev[1];row['event_role']='DUPLICATE'
        row['event_id']=eid;last[key]=(ts,eid)
    return rows
def _write_forward(rows):
    with EXTREME_FORWARD_FILE.open('w',newline='',encoding='utf-8') as f:w=csv.DictWriter(f,fieldnames=CSV_FIELDS);w.writeheader();w.writerows(rows)
def _migrate():
    EXTREME_FORWARD_FILE.parent.mkdir(parents=True,exist_ok=True)
    if not EXTREME_FORWARD_FILE.exists():_write_forward([]);return
    with EXTREME_FORWARD_FILE.open(newline='',encoding='utf-8') as f:rows=list(csv.DictReader(f))
    _assign_events(rows);_write_forward(rows)
def _migrate_snapshots():
    EXTREME_SNAPSHOT_FILE.parent.mkdir(parents=True,exist_ok=True)
    if not EXTREME_SNAPSHOT_FILE.exists():
        with EXTREME_SNAPSHOT_FILE.open('w',newline='',encoding='utf-8') as f:csv.DictWriter(f,fieldnames=SNAPSHOT_FIELDS).writeheader()
        return
    with EXTREME_SNAPSHOT_FILE.open(newline='',encoding='utf-8') as f:rows=list(csv.DictReader(f))
    clean=[{k:r.get(k,'') for k in SNAPSHOT_FIELDS} for r in rows]
    with EXTREME_SNAPSHOT_FILE.open('w',newline='',encoding='utf-8') as f:w=csv.DictWriter(f,fieldnames=SNAPSHOT_FIELDS);w.writeheader();w.writerows(clean)
def append_rows(rows):
    _migrate()
    with EXTREME_FORWARD_FILE.open(newline='',encoding='utf-8') as f:existing_rows=list(csv.DictReader(f))
    existing={r['id'] for r in existing_rows};fresh=[r for r in rows if r and r['id'] not in existing]
    if not fresh:return 0
    combined=existing_rows+fresh;_assign_events(combined);_write_forward(combined);return len(fresh)
def append_snapshots(rows):
    _migrate_snapshots()
    with EXTREME_SNAPSHOT_FILE.open(newline='',encoding='utf-8') as f:existing={r['id'] for r in csv.DictReader(f)}
    fresh=[r for r in rows if r and r['id'] not in existing]
    if not fresh:return 0
    with EXTREME_SNAPSHOT_FILE.open('a',newline='',encoding='utf-8') as f:csv.DictWriter(f,fieldnames=SNAPSHOT_FIELDS).writerows(fresh)
    return len(fresh)
def evaluate_forward(snapshot_rows=None):
    _migrate();_migrate_snapshots()
    with EXTREME_FORWARD_FILE.open(newline='',encoding='utf-8') as f:rows=list(csv.DictReader(f))
    _assign_events(rows)
    if snapshot_rows is None:
        with EXTREME_SNAPSHOT_FILE.open(newline='',encoding='utf-8') as f:snapshot_rows=list(csv.DictReader(f))
    snapshots={}
    for r in snapshot_rows:snapshots.setdefault(r.get('symbol',''),[]).append(r)
    for v in snapshots.values():v.sort(key=lambda r:_parse_ts(r['timestamp']))
    updated=0
    for row in rows:
        if row.get('event_role')!='PRIMARY':continue
        try:ts=_parse_ts(row['timestamp']);entry=float(row['price']);atr=float(row['atr_pct']);direction=row['direction']
        except (TypeError,ValueError):continue
        futures=[r for r in snapshots.get(row['symbol'],[]) if _parse_ts(r['timestamp'])>ts]
        for h in HORIZONS:
            key=f'h{h}'
            if row[key]:continue
            deadline=ts.timestamp()+h*3600
            for future in futures:
                ft=_parse_ts(future['timestamp'])
                if ft.timestamp()>deadline:break
                try:price=float(future['price'])
                except (TypeError,ValueError):continue
                out=_outcome(direction,entry,price,atr)
                if out:row[key]=out;updated+=1;break
    _write_forward(rows);return updated

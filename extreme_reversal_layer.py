"""Extreme-location reversal layer with event-level forward-test accounting."""
import csv
from datetime import datetime, timedelta
from pathlib import Path
from scanner_v2 import clamp

EXTREME_FORWARD_FILE=Path('data/extreme_reversal_forward_test.csv')
EXTREME_SNAPSHOT_FILE=Path('data/extreme_market_snapshots.csv')
HORIZONS=(1,4,12,24)
MIN_EXTREME_SCORE=70.0
MAX_1H_POS_LONG=0.30
MIN_1H_POS_SHORT=0.70
MAX_24H_POS_LONG=0.25
MIN_24H_POS_SHORT=0.75
MAX_ATR_FROM_LOW=1.0
MAX_ATR_FROM_HIGH=1.0
MIN_MOVE_ATR=0.75
MIN_TURN=0.25
# Accounting rule only: repeated observations inside one continuous opportunity
# are one event. It does not change the trading signal threshold.
EVENT_GAP_HOURS=2
CSV_FIELDS=['id','timestamp','symbol','provider','direction','signal','score','price','atr_pct','event_id','event_role','h1','h4','h12','h24']
SNAPSHOT_FIELDS=['id','timestamp','symbol','provider','price']


def _score_long(f):
    if not f or f.get('data_ok') is not True:return None
    pos1=f['h1_pos_48'];pos24=f['h1_pos_24'];dist=f['dist_low_atr'];move=f['move_into_low_atr'];turn=f['turn_long']
    location=0.45*clamp((MAX_1H_POS_LONG-pos1)/MAX_1H_POS_LONG)+0.35*clamp((MAX_24H_POS_LONG-pos24)/MAX_24H_POS_LONG)+0.20*clamp((MAX_ATR_FROM_LOW-dist)/MAX_ATR_FROM_LOW)
    return round(100*(0.70*location+0.20*clamp(move/3.0)+0.10*clamp(turn)),1)


def _score_short(f):
    if not f or f.get('data_ok') is not True:return None
    pos1=f['h1_pos_48'];pos24=f['h1_pos_24'];dist=f['dist_high_atr'];move=f['move_into_high_atr'];turn=f['turn_short']
    location=0.45*clamp((pos1-MIN_1H_POS_SHORT)/(1-MIN_1H_POS_SHORT))+0.35*clamp((pos24-MIN_24H_POS_SHORT)/(1-MIN_24H_POS_SHORT))+0.20*clamp((MAX_ATR_FROM_HIGH-dist)/MAX_ATR_FROM_HIGH)
    return round(100*(0.70*location+0.20*clamp(move/3.0)+0.10*clamp(turn)),1)


def classify(features):
    if not features or features.get('data_ok') is not True:
        return {'status':'DATA-LIMITED','direction':'NONE','score':None,'long_score':None,'short_score':None,'blocker':'15m/1h extreme data unavailable'}
    ls=_score_long(features);ss=_score_short(features)
    long_gate=features['h1_pos_48']<=MAX_1H_POS_LONG and features['h1_pos_24']<=MAX_24H_POS_LONG and 0<=features['dist_low_atr']<=MAX_ATR_FROM_LOW and features['move_into_low_atr']>=MIN_MOVE_ATR and features['turn_long']>=MIN_TURN
    short_gate=features['h1_pos_48']>=MIN_1H_POS_SHORT and features['h1_pos_24']>=MIN_24H_POS_SHORT and 0<=features['dist_high_atr']<=MAX_ATR_FROM_HIGH and features['move_into_high_atr']>=MIN_MOVE_ATR and features['turn_short']>=MIN_TURN
    candidates=[]
    if long_gate and ls>=MIN_EXTREME_SCORE:candidates.append(('LONG',ls))
    if short_gate and ss>=MIN_EXTREME_SCORE:candidates.append(('SHORT',ss))
    if candidates:
        side,score=max(candidates,key=lambda x:(x[1],x[0]=='LONG'))
        return {'status':f'EXTREME REVERSAL {side}','direction':side,'score':score,'long_score':ls,'short_score':ss,'blocker':'none'}
    return {'status':'MONITOR EXTREME','direction':'NONE','score':max(ls,ss),'long_score':ls,'short_score':ss,'blocker':'extreme gate not met'}


def signal_row(result,features,timestamp):
    d=classify(features)
    if not d['status'].startswith('EXTREME REVERSAL'):return None
    ts=features.get('timestamp') or timestamp
    return {'id':f'{ts}_{result["symbol"]}_EXTREME','timestamp':ts,'symbol':result['symbol'],'provider':result['provider'],'direction':d['direction'],'signal':d['status'],'score':d['score'],'price':features['price'],'atr_pct':features['atr_pct'],'event_id':'','event_role':'','h1':'','h4':'','h12':'','h24':''}


def snapshot_row(result,features,timestamp):
    ts=features.get('timestamp') or timestamp
    return {'id':f'{ts}_{result["symbol"]}','timestamp':ts,'symbol':result['symbol'],'provider':result['provider'],'price':features['price']}


def _parse_ts(v):return datetime.fromisoformat(v.replace('Z','+00:00'))


def _outcome(direction,entry,future,atr_pct):
    move=(future-entry)/entry*100
    favorable=move>=2*atr_pct if direction=='LONG' else move<=-2*atr_pct
    adverse=move<=-atr_pct if direction=='LONG' else move>=atr_pct
    if favorable and adverse:return 'AMBIGUOUS'
    if favorable:return 'EXPANSION'
    if adverse:return 'FAIL'
    return None


def _assign_events(rows):
    """Assign deterministic event IDs and PRIMARY/DUPLICATE roles.

    Same symbol + direction within EVENT_GAP_HOURS is one opportunity.
    The earliest observation is the only row used for forward-test statistics.
    """
    ordered=sorted(rows,key=lambda r:(_parse_ts(r['timestamp']),r.get('symbol',''),r.get('direction','')))
    last={}
    for row in ordered:
        key=(row.get('symbol',''),row.get('direction',''))
        ts=_parse_ts(row['timestamp'])
        prev=last.get(key)
        if prev is None or ts-prev>timedelta(hours=EVENT_GAP_HOURS):
            event_id=f"{row['symbol']}_{row['direction']}_{row['timestamp']}"
            row['event_role']='PRIMARY'
        else:
            event_id=prev[1]
            row['event_role']='DUPLICATE'
        row['event_id']=event_id
        last[key]=(ts,event_id)
    return rows


def _write_forward(rows):
    with EXTREME_FORWARD_FILE.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=CSV_FIELDS);w.writeheader();w.writerows(rows)


def _migrate():
    EXTREME_FORWARD_FILE.parent.mkdir(parents=True,exist_ok=True)
    if not EXTREME_FORWARD_FILE.exists():
        _write_forward([]);return
    with EXTREME_FORWARD_FILE.open(newline='',encoding='utf-8') as f:rows=list(csv.DictReader(f))
    clean=[{k:r.get(k,'') for k in CSV_FIELDS} for r in rows]
    _assign_events(clean)
    _write_forward(clean)


def _migrate_snapshots():
    EXTREME_SNAPSHOT_FILE.parent.mkdir(parents=True,exist_ok=True)
    if not EXTREME_SNAPSHOT_FILE.exists():
        with EXTREME_SNAPSHOT_FILE.open('w',newline='',encoding='utf-8') as f:csv.DictWriter(f,fieldnames=SNAPSHOT_FIELDS).writeheader();return
    with EXTREME_SNAPSHOT_FILE.open(newline='',encoding='utf-8') as f:rows=list(csv.DictReader(f))
    clean=[{k:r.get(k,'') for k in SNAPSHOT_FIELDS} for r in rows]
    with EXTREME_SNAPSHOT_FILE.open('w',newline='',encoding='utf-8') as f:csv.DictWriter(f,fieldnames=SNAPSHOT_FIELDS).writeheader();csv.DictWriter(f,fieldnames=SNAPSHOT_FIELDS).writerows(clean)


def append_rows(rows):
    _migrate()
    with EXTREME_FORWARD_FILE.open(newline='',encoding='utf-8') as f:existing_rows=list(csv.DictReader(f))
    existing={r['id'] for r in existing_rows}
    fresh=[r for r in rows if r and r['id'] not in existing]
    if not fresh:return 0
    combined=existing_rows+fresh
    _assign_events(combined)
    _write_forward(combined)
    return len(fresh)


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
        try:ts=_parse_ts(row['timestamp']);entry=float(row['price']);atr=float(row['atr_pct']);direction=row['direction'];symbol=row['symbol']
        except (TypeError,ValueError):continue
        futures=[r for r in snapshots.get(symbol,[]) if _parse_ts(r['timestamp'])>ts]
        for h in HORIZONS:
            key=f'h{h}'
            if row[key]:continue
            deadline=ts.timestamp()+h*3600
            for future in futures:
                ft=_parse_ts(future['timestamp'])
                if ft.timestamp()>deadline:break
                try:price=float(future['price'])
                except (TypeError,ValueError):continue
                outcome=_outcome(direction,entry,price,atr)
                if outcome:row[key]=outcome;updated+=1;break
    _write_forward(rows)
    return updated


def stats():
    _migrate()
    with EXTREME_FORWARD_FILE.open(newline='',encoding='utf-8') as f:rows=list(csv.DictReader(f))
    events={r['event_id'] for r in rows if r.get('event_id')}
    primary=[r for r in rows if r.get('event_role')=='PRIMARY']
    outcomes=[r[h] for r in primary for h in ('h1','h4','h12','h24') if r[h]]
    return f'Extreme forward-test: {len(rows)} raw signals / {len(events)} independent events / {len(outcomes)} resolved horizon outcomes'

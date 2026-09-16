import csv, math, os, random, statistics, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import requests

VERSION='2.0.1'
BINANCE_BASES=['https://fapi.binance.com','https://fapi1.binance.com','https://fapi2.binance.com','https://fapi3.binance.com','https://fapi4.binance.com']
BYBIT_BASE='https://api.bybit.com'; BITGET_BASE='https://api.bitget.com'
SYMBOLS=['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','DOGEUSDT','SUIUSDT','IOTAUSDT','TAOUSDT','AXLUSDT','BNBUSDT','ADAUSDT','LINKUSDT','AVAXUSDT','APTUSDT','SEIUSDT']
CAPITAL_IDR=900_000; RISK_PCT=0.02
TIMEOUT=12; DATA_DIR=Path('data'); SIGNAL_FILE=DATA_DIR/'reversal_forward_test.csv'
HORIZONS=(1,4,12,24); RANGE_BARS=48; MIN_CANDLES=80; TAKER_WINDOWS=(100,250,500); TAKER_FETCH=500
CSV_FIELDS=['id','timestamp','symbol','provider','price','direction','score','location','exhaustion','flow','reclaim','expansion','atr_pct','rsi','range_pos','range_high','range_low','volume_ratio','taker_100','taker_250','taker_500','taker_ratio','taker_stability','taker_spread_pct','taker_fills','book_ratio','funding','signal','entry_low','entry_high','sl','position_idr','tp1','tp2','tp3','stop_pct','h1','h4','h12','h24']
S=requests.Session(); S.headers.update({'User-Agent':f'Zorathvael-Crypto-Scanner/{VERSION}'})

def clamp(x,a=0.0,b=1.0): return max(a,min(b,x))
def sf(x,d=None):
    try:return float(x)
    except (TypeError,ValueError):return d
def avg(xs):return sum(xs)/len(xs) if xs else None

def _retry_delay(response, attempt):
    """Return bounded retry delay; honor Retry-After when supplied."""
    retry_after=response.headers.get('Retry-After') if response is not None else None
    try:
        if retry_after is not None:
            return min(8.0,max(0.0,float(retry_after)))
    except (TypeError,ValueError):
        pass
    base=1.0 if response is not None and response.status_code==429 else 0.5
    return min(8.0,base*(2**attempt)+random.uniform(0.0,0.35))

def get(base,path,params=None,retries=3):
    last=None
    for i in range(retries+1):
        try:
            r=S.get(base+path,params=params,timeout=TIMEOUT)
            if r.status_code==429 or r.status_code>=500:
                last=RuntimeError(f'HTTP {r.status_code}: {r.text[:160]}')
                if i<retries:
                    time.sleep(_retry_delay(r,i)); continue
            if not r.ok: raise RuntimeError(f'HTTP {r.status_code}: {r.text[:160]}')
            return r.json()
        except requests.RequestException as e:
            last=RuntimeError(f'Network error: {e}')
            if i<retries: time.sleep(min(8.0,0.5*(2**i)+random.uniform(0.0,0.35)))
    raise last or RuntimeError('request failed')

def binance(path,params=None):
    errors=[]
    for base in BINANCE_BASES:
        try:return get(base,path,params)
        except Exception as e:errors.append(f'{base}: {e}')
    raise RuntimeError('Binance unavailable: '+' | '.join(errors))
def bybit(path,params=None):
    d=get(BYBIT_BASE,path,params)
    if d.get('retCode') not in (None,0): raise RuntimeError(f"retCode {d.get('retCode')}: {d.get('retMsg')}")
    return d
def bitget(path,params=None):
    d=get(BITGET_BASE,path,params)
    if d.get('code') not in (None,'00000',0): raise RuntimeError(f"code {d.get('code')}: {d.get('msg')}")
    return d

def ema(values,n):
    if len(values)<n:return None
    e=sum(values[:n])/n; a=2/(n+1)
    for x in values[n:]:e=a*x+(1-a)*e
    return e

def rsi(values,n=14):
    if len(values)<n+1:return None
    gains=[];losses=[]
    for a,b in zip(values[-n-1:-1],values[-n:]):
        d=b-a;gains.append(max(d,0));losses.append(max(-d,0))
    ag=avg(gains);al=avg(losses)
    if al==0:return 100.0
    return 100-100/(1+ag/al)

def candle_features(rows):
    if len(rows)<MIN_CANDLES: raise RuntimeError(f'Need {MIN_CANDLES}+ closed candles, got {len(rows)}')
    c=[float(x[4]) for x in rows];v=[float(x[5]) for x in rows]
    tr=[];prev=None
    for x in rows:
        h,l,cl=map(float,x[2:5]);tr.append(h-l if prev is None else max(h-l,abs(h-prev),abs(l-prev)));prev=cl
    atr14=avg(tr[-14:]); atr5=avg(tr[-5:]); atr20=avg(tr[-20:]); atr_pct=atr14/c[-1]*100
    hi=max(c[-RANGE_BARS:]);lo=min(c[-RANGE_BARS:]);rng=hi-lo;pos=(c[-1]-lo)/rng if rng else .5
    e20=ema(c,20);e50=ema(c,50);r=rsi(c)
    base=avg(v[-21:-1]);vr=v[-1]/base if base else 1.0
    down12=(c[-13]-c[-1])/c[-13] if c[-13] else 0;up12=(c[-1]-c[-13])/c[-13] if c[-13] else 0
    down24=(c[-25]-c[-1])/c[-25] if c[-25] else 0;up24=(c[-1]-c[-25])/c[-25] if c[-25] else 0
    long_move=max(down12,down24);short_move=max(up12,up24)
    long_exhaust=clamp((long_move/(atr_pct/100*8)-0.45)/1.2) if atr_pct else 0
    short_exhaust=clamp((short_move/(atr_pct/100*8)-0.45)/1.2) if atr_pct else 0
    rlong=clamp((45-(r or 50))/20);rshort=clamp(((r or 50)-55)/20)
    compression=clamp(1-(atr5/atr20 if atr20 else 1))
    recent_low=min(c[-7:-1]);recent_high=max(c[-7:-1])
    long_reclaim=clamp((c[-1]-recent_low)/(atr14*1.5)) if atr14 else 0
    short_reject=clamp((recent_high-c[-1])/(atr14*1.5)) if atr14 else 0
    return dict(c=c,v=v,tr=tr,atr=atr14,atr_pct=atr_pct,rsi=r,high=hi,low=lo,pos=pos,ema20=e20,ema50=e50,volume_ratio=vr,
                long_location=clamp((0.38-pos)/0.38),short_location=clamp((pos-0.62)/0.38),
                long_exhaust=0.7*long_exhaust+0.3*rlong,short_exhaust=0.7*short_exhaust+0.3*rshort,
                compression=compression,long_reclaim=long_reclaim,short_reject=short_reject)

def _trade_parts(t):
    if isinstance(t,dict):return str(t.get('side','')).lower(),sf(t.get('price')),sf(t.get('size'))
    try:return str(t[4] if len(t)>4 else t[3]).lower(),sf(t[1]),sf(t[2])
    except (IndexError,TypeError):return '',None,None

def taker_pressure(trades,buy_side='buy',sell_side='sell'):
    ratios=[];n=len(trades);bn=str(buy_side).lower();sn=str(sell_side).lower()
    for window in TAKER_WINDOWS:
        if n<window:ratios.append(None);continue
        buy=sell=0.0
        for t in trades[:window]:
            side,p,q=_trade_parts(t)
            if p is None or q is None or p<=0 or q<=0:continue
            if side in (bn,'buy'):buy+=p*q
            elif side in (sn,'sell'):sell+=p*q
        ratios.append(buy/sell if buy>0 and sell>0 else None)
    valid=[x for x in ratios if x is not None and math.isfinite(x) and x>0]
    if not valid:return ratios,None,None,None,n
    logs=[math.log(x) for x in valid];ml=avg(logs);agg=math.exp(ml);std=statistics.pstdev(logs) if len(logs)>1 else 0
    return ratios,agg,(max(valid)/min(valid)-1)*100 if len(valid)>1 else 0.0,1/(1+std),n

def taker_flow(agg):
    if agg is None:return .5
    return clamp(.5 + math.log(agg)/math.log(4)*.5)

def reversal_scores(f,tf):
    flow=taker_flow(tf['agg']);expansion=0.55*clamp((f['volume_ratio']-1)/2)+0.45*f['compression']
    long_parts=dict(location=f['long_location'],exhaustion=f['long_exhaust'],flow=flow,reclaim=f['long_reclaim'],expansion=expansion)
    short_parts=dict(location=f['short_location'],exhaustion=f['short_exhaust'],flow=1-flow,reclaim=f['short_reject'],expansion=expansion)
    w=dict(location=30,exhaustion=20,flow=20,reclaim=15,expansion=15)
    ls=sum(w[k]*clamp(v) for k,v in long_parts.items());ss=sum(w[k]*clamp(v) for k,v in short_parts.items())
    direction='NONE'
    if ls>=70 and f['long_location']>=0.60 and f['long_reclaim']>=0.25 and flow>=0.55:direction='LONG'
    elif ss>=70 and f['short_location']>=0.60 and f['short_reject']>=0.25 and flow<=0.45:direction='SHORT'
    return round(ls,1),round(ss,1),direction,long_parts,short_parts

def risk_plan(price,atr,direction):
    if direction not in ('LONG','SHORT'):return (None,)*8
    stop=max(.02,min(.07,(atr or 3)*1.5/100));risk=CAPITAL_IDR*RISK_PCT;position=min(CAPITAL_IDR,risk/stop)
    if direction=='LONG':lo=price*.995;hi=price*1.005;sl=lo*(1-stop);r=lo-sl;tp=[lo+1.5*r,lo+3*r,lo+5*r]
    else:lo=price*.995;hi=price*1.005;sl=hi*(1+stop);r=sl-hi;tp=[hi-1.5*r,hi-3*r,hi-5*r]
    return lo,hi,sl,position,*tp,stop*100

def make_result(sym,provider,price,f,tf,book,funding,change):
    ls,ss,d,lp,sp=reversal_scores(f,tf);score=max(ls,ss);plan=risk_plan(price,f['atr_pct'],d);signal=f'PRE-EXPANSION {d}' if d!='NONE' else 'NO SETUP'
    parts=lp if d=='LONG' else sp
    return dict(symbol=sym,provider=provider,price=price,change=change,score=score,direction=d,signal=signal,location=parts['location'],exhaustion=parts['exhaustion'],flow=parts['flow'],reclaim=parts['reclaim'],expansion=parts['expansion'],long_score=ls,short_score=ss,atr_pct=f['atr_pct'],rsi=f['rsi'],range_pos=f['pos'],range_high=f['high'],range_low=f['low'],volume_ratio=f['volume_ratio'],taker_windows=tf['ratios'],taker=tf['agg'],taker_stability=tf['stability'],taker_spread=tf['spread_pct'],taker_fills=tf['fills'],book=book,funding=funding,plan=plan)

def normalize_bitget_candles(raw):return list(reversed(raw[1:]))
def normalize_bybit_candles(raw):return list(reversed(raw[1:]))

def bitget_symbol(sym,btc24):
    pt='USDT-FUTURES';t=bitget('/api/v2/mix/market/ticker',{'symbol':sym,'productType':pt})['data'][0];raw=bitget('/api/v2/mix/market/candles',{'symbol':sym,'productType':pt,'granularity':'1H','limit':MIN_CANDLES+2})['data'];f=candle_features(normalize_bitget_candles(raw));d=bitget('/api/v2/mix/market/merge-depth',{'symbol':sym,'productType':pt,'limit':20})['data'];b=sum(float(x[1]) for x in d.get('bids',[]));a=sum(float(x[1]) for x in d.get('asks',[]));book=b/a if b and a else None;fills=bitget('/api/v2/mix/market/fills-history',{'symbol':sym,'productType':pt,'limit':TAKER_FETCH})['data'];
    if not isinstance(fills,list):raise RuntimeError('fills-history data is not a list')
    tw,agg,sp,st,n=taker_pressure(fills);tf={'ratios':tw,'agg':agg,'spread_pct':sp,'stability':st,'fills':n};return make_result(sym,'Bitget',float(t['lastPr']),f,tf,book,sf(t.get('fundingRate')),float(t.get('change24h',0))*100)

def bybit_symbol(sym,btc24):
    t=bybit('/v5/market/tickers',{'category':'linear','symbol':sym})['result']['list'][0];raw=bybit('/v5/market/kline',{'category':'linear','symbol':sym,'interval':'60','limit':MIN_CANDLES+2})['result']['list'];f=candle_features(normalize_bybit_candles(raw));d=bybit('/v5/market/orderbook',{'category':'linear','symbol':sym,'limit':25})['result'];b=sum(float(x[1]) for x in d.get('b',[]));a=sum(float(x[1]) for x in d.get('a',[]));book=b/a if b and a else None;fills=bybit('/v5/market/recent-trade',{'category':'linear','symbol':sym,'limit':TAKER_FETCH})['result']['list'];tw,agg,sp,st,n=taker_pressure(fills);tf={'ratios':tw,'agg':agg,'spread_pct':sp,'stability':st,'fills':n};fr=bybit('/v5/market/funding/history',{'category':'linear','symbol':sym,'limit':1})['result']['list'];fund=sf(fr[0]['fundingRate']) if fr else None;return make_result(sym,'Bybit',float(t['lastPrice']),f,tf,book,fund,float(t.get('price24hPcnt',0))*100)

def binance_symbol(sym,btc24):
    t=binance('/fapi/v1/ticker/24hr',{'symbol':sym});raw=binance('/fapi/v1/klines',{'symbol':sym,'interval':'1h','limit':MIN_CANDLES+2});f=candle_features(raw[:-1]);tr=binance('/futures/data/takerlongshortRatio',{'symbol':sym,'period':'1h','limit':1});agg=sf(tr[-1]['buySellRatio']) if tr else None;tf={'ratios':[agg,None,None],'agg':agg,'spread_pct':0.0,'stability':1.0,'fills':1};fr=binance('/fapi/v1/fundingRate',{'symbol':sym,'limit':1});fund=sf(fr[-1]['fundingRate']) if fr else None;d=binance('/fapi/v1/depth',{'symbol':sym,'limit':20});b=sum(float(x[1]) for x in d.get('bids',[]));a=sum(float(x[1]) for x in d.get('asks',[]));return make_result(sym,'Binance',float(t['lastPrice']),f,tf,b/a if b and a else None,fund,float(t.get('priceChangePercent',0)))

def discover():
    try:t=binance('/fapi/v1/ticker/24hr',{'symbol':'BTCUSDT'});return 'Binance',float(t.get('priceChangePercent',0))
    except Exception as e:print('WARN: Binance unavailable:',e)
    try:t=bybit('/v5/market/tickers',{'category':'linear','symbol':'BTCUSDT'})['result']['list'][0];return 'Bybit',float(t.get('price24hPcnt',0))*100
    except Exception as e:print('WARN: Bybit unavailable:',e)
    t=bitget('/api/v2/mix/market/ticker',{'symbol':'BTCUSDT','productType':'USDT-FUTURES'})['data'][0];return 'Bitget',float(t.get('change24h',0))*100

def fetch_symbol(sym,provider,btc24):
    if provider=='Bitget':return bitget_symbol(sym,btc24)
    if provider=='Bybit':return bybit_symbol(sym,btc24)
    return binance_symbol(sym,btc24)

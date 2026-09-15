import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import requests

BINANCE_BASES=["https://fapi.binance.com","https://fapi1.binance.com","https://fapi2.binance.com","https://fapi3.binance.com","https://fapi4.binance.com"]
BYBIT_BASE="https://api.bybit.com"
BITGET_BASE="https://api.bitget.com"
CAPITAL_IDR=900_000
RISK_PCT=0.02
SYMBOLS=["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT","DOGEUSDT","SUIUSDT","IOTAUSDT","TAOUSDT","AXLUSDT","BNBUSDT","ADAUSDT","LINKUSDT","AVAXUSDT","APTUSDT","SEIUSDT"]
TIMEOUT=12
S=requests.Session(); S.headers.update({"User-Agent":"Zorathvael-Crypto-Scanner/1.7"})

def clamp(x,a=-1,b=1): return max(a,min(b,x))
def sf(x,d=None):
    try:return float(x)
    except:return d

def get(base,path,p=None,retries=2):
    last=None
    for i in range(retries+1):
        try:
            r=S.get(base+path,params=p,timeout=TIMEOUT)
            if r.status_code==429 or r.status_code>=500:
                last=RuntimeError(f"HTTP {r.status_code}: {r.text[:160]}")
                if i<retries: time.sleep(.7*(i+1)); continue
            if not r.ok: raise RuntimeError(f"HTTP {r.status_code}: {r.text[:160]}")
            try:return r.json()
            except Exception as e: raise RuntimeError(f"Invalid JSON: {e}")
        except requests.RequestException as e:
            last=RuntimeError(f"Network error: {e}")
            if i<retries: time.sleep(.7*(i+1)); continue
    raise last or RuntimeError("request failed")

def binance(path,p=None):
    es=[]
    for b in BINANCE_BASES:
        try:return get(b,path,p)
        except Exception as e:es.append(f"{b}: {e}")
    raise RuntimeError("Binance unavailable: "+" | ".join(es))

def bybit(path,p=None):
    d=get(BYBIT_BASE,path,p)
    if d.get("retCode") not in (None,0):raise RuntimeError(f"retCode {d.get('retCode')}: {d.get('retMsg')}")
    return d

def bitget(path,p=None):
    d=get(BITGET_BASE,path,p)
    if d.get("code") not in (None,"00000",0):raise RuntimeError(f"code {d.get('code')}: {d.get('msg')}")
    return d

def features(raw):
    if len(raw)<25:raise RuntimeError(f"Need 25+ candles, got {len(raw)}")
    rows=list(reversed(raw)); c=[float(x[4]) for x in rows]; v=[float(x[5]) for x in rows]
    m1=(c[-1]/c[-2]-1)*100; m6=(c[-1]/c[-7]-1)*100; m24=(c[-1]/c[0]-1)*100
    base=sum(v[-13:-1])/12; vr=v[-1]/base if base else None
    trs=[]; prev=None
    for x in rows[-15:]:
        h,l,cl=map(float,x[2:5]); trs.append(h-l if prev is None else max(h-l,abs(h-prev),abs(l-prev))); prev=cl
    atr=(sum(trs)/len(trs))/c[-1]*100 if trs else None
    return m1,m6,m24,vr,atr

def score(f,taker,book,funding,btc):
    m1,m6,m24,vr,atr=f
    mom=50+18*clamp(m6/4)+12*clamp(m24/12)
    tak=None if taker is None else 50+35*clamp((taker-1)/.8)
    bk=None if book is None else 50+30*clamp((book-1)/.7)
    vol=None if vr is None else 50+25*clamp((vr-1)/2)
    fund=None if funding is None else 50-30*min(abs(funding)/.001,1)
    br=50+25*clamp(btc/4)
    vals={"momentum":(30,mom),"taker":(20,tak),"orderbook":(15,bk),"volume":(10,vol),"funding":(10,fund),"btc_regime":(15,br)}
    av={k:v for k,v in vals.items() if v[1] is not None}; total=sum(v[0] for v in av.values()); s=sum(w*x for w,x in av.values())/total
    ds=sum(av[k][0]*(av[k][1]-50) for k in ("momentum","taker","orderbook") if k in av)/sum(av[k][0] for k in ("momentum","taker","orderbook") if k in av)
    bias="LONG" if ds>5 else "SHORT" if ds<-5 else "NEUTRAL"
    return round(s,1),bias,total/100

def risk(price,atr,bias):
    sp=max(0.02,min(.07,(atr or 3)*1.5/100)); risk_cash=CAPITAL_IDR*RISK_PCT; pos=min(CAPITAL_IDR,risk_cash/sp)
    if bias=="SHORT":
        lo,hi=price*1.005,price*1.015; sl=hi*(1+sp); r=sl-hi; tp=[hi-1.5*r,hi-3*r,hi-5*r]
    else:
        lo,hi=price*.985,price*.995; sl=lo*(1-sp); r=lo-sl; tp=[lo+1.5*r,lo+3*r,lo+5*r]
    return lo,hi,sl,pos,*tp,sp*100

def result(sym,provider,price,ch,f,taker,book,funding,btc):
    s,b,q=score(f,taker,book,funding,btc); m1,m6,m24,vr,atr=f; lo,hi,sl,pos,*tp,sp=risk(price,atr,b)
    sig="STRONG "+b if s>=75 and b!="NEUTRAL" and q>=.65 else b+" WATCH" if s>=68 and b!="NEUTRAL" and q>=.65 else "NO SETUP"
    return dict(symbol=sym,provider=provider,price=price,score=s,bias=b,signal=sig,quality=q,change=ch,m1=m1,m6=m6,m24=m24,vol=vr,atr=atr,taker=taker,book=book,funding=funding,lo=lo,hi=hi,sl=sl,pos=pos,tp=tp,sp=sp)

def bitget_symbol(sym,btc):
    pt="USDT-FUTURES"; t=bitget("/api/v2/mix/market/ticker",{"symbol":sym,"productType":pt})["data"][0]; price=float(t["lastPr"]); ch=float(t.get("change24h",0))*100; fund=sf(t.get("fundingRate"))
    f=features(bitget("/api/v2/mix/market/candles",{"symbol":sym,"productType":pt,"granularity":"1H","limit":25})["data"])
    d=bitget("/api/v2/mix/market/merge-depth",{"symbol":sym,"productType":pt,"limit":20})["data"]; bids=sum(float(x[1]) for x in d.get("bids",[])); asks=sum(float(x[1]) for x in d.get("asks",[])); book=bids/asks if bids and asks else None
    tr=bitget("/api/v2/mix/market/fills",{"symbol":sym,"productType":pt,"limit":100})["data"]; buy=sum(float(x["price"])*float(x["size"]) for x in tr if x.get("side","").lower()=="buy"); sell=sum(float(x["price"])*float(x["size"]) for x in tr if x.get("side","").lower()=="sell"); tak=buy/sell if buy and sell else None
    return result(sym,"Bitget",price,ch,f,tak,book,fund,btc)

def bybit_symbol(sym,btc):
    t=bybit("/v5/market/tickers",{"category":"linear","symbol":sym})["result"]["list"][0]; price=float(t["lastPrice"]); ch=float(t.get("price24hPcnt",0))*100
    f=features(list(reversed(bybit("/v5/market/kline",{"category":"linear","symbol":sym,"interval":"60","limit":25})["result"]["list"])))
    tr=bybit("/v5/market/recent-trade",{"category":"linear","symbol":sym,"limit":500})["result"]["list"]; buy=sum(float(x[1])*float(x[2]) for x in tr if x.get("side")=="Buy"); sell=sum(float(x[1])*float(x[2]) for x in tr if x.get("side")=="Sell"); tak=buy/sell if buy and sell else None
    d=bybit("/v5/market/orderbook",{"category":"linear","symbol":sym,"limit":25})["result"]; bids=sum(float(x[1]) for x in d.get("b",[])); asks=sum(float(x[1]) for x in d.get("a",[])); book=bids/asks if bids and asks else None
    fr=bybit("/v5/market/funding/history",{"category":"linear","symbol":sym,"limit":1})["result"]["list"]; fund=float(fr[0]["fundingRate"]) if fr else None
    return result(sym,"Bybit",price,ch,f,tak,book,fund,btc)

def binance_symbol(sym,btc):
    t=binance("/fapi/v1/ticker/24hr",{"symbol":sym}); price=float(t["lastPrice"]); ch=float(t.get("priceChangePercent",0)); f=features(binance("/fapi/v1/klines",{"symbol":sym,"interval":"1h","limit":25}))
    tr=binance("/futures/data/takerlongshortRatio",{"symbol":sym,"period":"1h","limit":1}); tak=float(tr[-1]["buySellRatio"]) if tr else None; fr=binance("/fapi/v1/fundingRate",{"symbol":sym,"limit":1}); fund=float(fr[-1]["fundingRate"]) if fr else None
    d=binance("/fapi/v1/depth",{"symbol":sym,"limit":20}); bids=sum(float(x[1]) for x in d.get("bids",[])); asks=sum(float(x[1]) for x in d.get("asks",[])); book=bids/asks if bids and asks else None
    return result(sym,"Binance",price,ch,f,tak,book,fund,btc)

def discover():
    try:
        t=binance("/fapi/v1/ticker/24hr",{"symbol":"BTCUSDT"}); return "Binance",float(t.get("priceChangePercent",0))
    except Exception as e: print("WARN: Binance unavailable:",e)
    try:
        t=bybit("/v5/market/tickers",{"category":"linear","symbol":"BTCUSDT"})["result"]["list"][0]; return "Bybit",float(t.get("price24hPcnt",0))*100
    except Exception as e: print("WARN: Bybit unavailable:",e)
    try:
        t=bitget("/api/v2/mix/market/ticker",{"symbol":"BTCUSDT","productType":"USDT-FUTURES"})["data"][0]; return "Bitget",float(t.get("change24h",0))*100
    except Exception as e: raise SystemExit("FATAL: all Futures providers unavailable: "+str(e))

def btc6(provider):
    if provider=="Binance": return features(binance("/fapi/v1/klines",{"symbol":"BTCUSDT","interval":"1h","limit":25}))[1]
    if provider=="Bybit": return features(list(reversed(bybit("/v5/market/kline",{"category":"linear","symbol":"BTCUSDT","interval":"60","limit":25})["result"]["list"]))))[1]
    return features(bitget("/api/v2/mix/market/candles",{"symbol":"BTCUSDT","productType":"USDT-FUTURES","granularity":"1H","limit":25})["data"])[1]

def send(text):
    tok,chat=os.getenv("TELEGRAM_BOT_TOKEN"),os.getenv("TELEGRAM_CHAT_ID")
    if not tok or not chat: print("INFO: Telegram secrets not configured; console output only."); return
    try:
        r=S.post(f"https://api.telegram.org/bot{tok}/sendMessage",json={"chat_id":chat,"text":text},timeout=TIMEOUT)
        if not r.ok: print("WARN: Telegram:",r.status_code,r.text[:160])
    except Exception as e: print("WARN: Telegram unavailable:",e)

def main():
    print("ZORATHVAEL CRYPTO SCANNER V1.7\nProvider strategy: Binance -> Bybit -> Bitget")
    provider,btc24=discover(); print("Active provider:",provider); btc=btc6(provider); results=[]; errors=[]
    fn=binance_symbol if provider=="Binance" else bybit_symbol if provider=="Bybit" else bitget_symbol
    with ThreadPoolExecutor(max_workers=5) as ex:
        jobs=[ex.submit(fn,s,btc) for s in SYMBOLS]
        for j in as_completed(jobs):
            try: results.append(j.result())
            except Exception as e: errors.append(str(e))
    results.sort(key=lambda x:(x["score"],x["quality"]),reverse=True)
    lines=["ZORATHVAEL CRYPTO SCANNER V1.7",datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),f"Provider: {provider}",f"BTC 24h: {btc24:.2f}% | BTC 6h: {btc:.2f}%",f"Coverage: {len(results)}/{len(SYMBOLS)}",""]
    for i,x in enumerate(results[:10],1):
        lines += [f"{i}. {x['symbol']} | {x['score']:.1f} | {x['signal']} | Quality {x['quality']:.0%}",f"   Bias {x['bias']} | Price {x['price']:.8g} | 24h {x['change']:.2f}% | 1h {x['m1']:.2f}% | 6h {x['m6']:.2f}% | 24h-trend {x['m24']:.2f}%",f"   Vol {x['vol']:.2f}x | ATR {x['atr']:.2f}% | Taker {x['taker'] if x['taker'] is not None else 'N/A'}x | Book {x['book'] if x['book'] is not None else 'N/A'}x | Funding {x['funding'] if x['funding'] is not None else 'N/A'}",f"   Entry {x['lo']:.8g}-{x['hi']:.8g} | SL {x['sl']:.8g} ({x['sp']:.2f}%) | Pos Rp{x['pos']:,.0f}",f"   TP1 {x['tp'][0]:.8g} | TP2 {x['tp'][1]:.8g} | TP3 {x['tp'][2]:.8g}"]
    if errors: lines += [f"\nFailed symbols: {len(errors)}"]+[" - "+e for e in errors[:15]]
    lines += ["","Score is setup quality, NOT probability of profit.","OI and Long/Short are intentionally not fabricated when reliable public historical data is unavailable."]
    text="\n".join(lines); print(text); send(text)

if __name__=="__main__": main()

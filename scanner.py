import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import requests

BINANCE_BASES=["https://fapi.binance.com","https://fapi1.binance.com","https://fapi2.binance.com","https://fapi3.binance.com","https://fapi4.binance.com"]
BYBIT_BASE="https://api.bybit.com"
BITGET_BASE="https://api.bitget.com"
CAPITAL_IDR=900_000
RISK_PCT=0.02
MAX_SYMBOLS=15
SYMBOLS=["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT","DOGEUSDT","SUIUSDT","IOTAUSDT","TAOUSDT","AXLUSDT","BNBUSDT","ADAUSDT","LINKUSDT","AVAXUSDT","APTUSDT","SEIUSDT"]
TIMEOUT=12
S=requests.Session()
S.headers.update({"User-Agent":"Zorathvael-Crypto-Scanner/1.4"})
ACTIVE_BINANCE_BASE=None
ACTIVE_PROVIDER=None

def clamp(x,lo=0.0,hi=1.0): return max(lo,min(hi,x))

def binance_request(path,params=None):
    global ACTIVE_BINANCE_BASE
    bases=([ACTIVE_BINANCE_BASE] if ACTIVE_BINANCE_BASE else [])+[b for b in BINANCE_BASES if b!=ACTIVE_BINANCE_BASE]
    errors=[]
    for base in bases:
        try:
            r=S.get(base+path,params=params,timeout=TIMEOUT)
            if r.ok:
                ACTIVE_BINANCE_BASE=base; return r.json()
            errors.append(f"{base}: HTTP {r.status_code} {r.text[:140]}")
        except Exception as e: errors.append(f"{base}: {type(e).__name__}: {e}")
    raise RuntimeError("Binance unavailable for "+path+"; "+" | ".join(errors))

def bybit_request(path,params=None):
    r=S.get(BYBIT_BASE+path,params=params,timeout=TIMEOUT)
    if not r.ok: raise RuntimeError(f"Bybit HTTP {r.status_code}: {r.text[:180]}")
    data=r.json()
    if data.get("retCode") not in (0,None): raise RuntimeError(f"Bybit retCode {data.get('retCode')}: {data.get('retMsg')}")
    return data

def bitget_request(path,params=None):
    r=S.get(BITGET_BASE+path,params=params,timeout=TIMEOUT)
    if not r.ok: raise RuntimeError(f"Bitget HTTP {r.status_code}: {r.text[:180]}")
    data=r.json()
    if data.get("code") not in ("00000",0,None): raise RuntimeError(f"Bitget code {data.get('code')}: {data.get('msg')}")
    return data

def signal(score): return "STRONG SETUP" if score>=80 else "BUY / WATCH" if score>=70 else "WATCH" if score>=60 else "AVOID"

def risk_plan(price):
    entry_low,entry_high=price*.985,price*.995
    sl=entry_low*.95
    position=(CAPITAL_IDR*RISK_PCT)/.05
    r=entry_low-sl
    return entry_low,entry_high,sl,position,r

def make_result(symbol,provider,price,change24,momentum6,vol_ratio,oi_change,taker_ratio,book_ratio,funding,ls_ratio,btc_change):
    parts={"momentum":20*clamp((momentum6+2)/8),"volume":15*clamp((vol_ratio-.8)/1.7),"oi":15*clamp((oi_change+1)/9),"taker":15*clamp((taker_ratio-.95)/.35),"book":10*clamp((book_ratio-.9)/.35),"funding":10*(1-clamp(abs(funding)/.0015)),"long_short":10*(1-clamp(abs(ls_ratio-1.35)/1.5)),"btc":5*clamp((btc_change+3)/9)}
    score=round(sum(parts.values()),1)
    entry_low,entry_high,sl,position,r=risk_plan(price)
    return {"symbol":symbol,"provider":provider,"price":price,"score":score,"signal":signal(score),"change24":change24,"momentum6":momentum6,"vol_ratio":vol_ratio,"oi_change":oi_change,"taker":taker_ratio,"funding":funding,"book":book_ratio,"ls_ratio":ls_ratio,"entry_low":entry_low,"entry_high":entry_high,"sl":sl,"position_idr":position,"tp1":entry_low+1.5*r,"tp2":entry_low+3*r,"tp3":entry_low+5*r,"parts":parts}

def score_binance(symbol,btc_change):
    t=binance_request("/fapi/v1/ticker/24hr",{"symbol":symbol}); price=float(t["lastPrice"]); change24=float(t.get("priceChangePercent",0))
    kl=binance_request("/fapi/v1/klines",{"symbol":symbol,"interval":"1h","limit":25})
    oi=binance_request("/futures/data/openInterestHist",{"symbol":symbol,"period":"1h","limit":2})
    taker=binance_request("/futures/data/takerlongshortRatio",{"symbol":symbol,"period":"1h","limit":1})
    gls=binance_request("/futures/data/globalLongShortAccountRatio",{"symbol":symbol,"period":"1h","limit":1})
    funding=binance_request("/fapi/v1/fundingRate",{"symbol":symbol,"limit":1})
    depth=binance_request("/fapi/v1/depth",{"symbol":symbol,"limit":20})
    if len(kl)<13 or len(oi)<2 or not taker or not gls or not funding: raise RuntimeError("Incomplete Binance market data")
    closes=[float(x[4]) for x in kl]; vols=[float(x[5]) for x in kl]; momentum6=(closes[-1]/closes[-7]-1)*100; baseline=sum(vols[-13:-1])/12; vol_ratio=vols[-1]/baseline if baseline else 1
    a,b=float(oi[-2]["sumOpenInterest"]),float(oi[-1]["sumOpenInterest"]); oi_change=(b/a-1)*100 if a else 0
    taker_ratio=float(taker[-1]["buySellRatio"]); ls_ratio=float(gls[-1]["longShortRatio"]); funding_rate=float(funding[-1]["fundingRate"])
    bids=sum(float(x[1]) for x in depth.get("bids",[])[:20]); asks=sum(float(x[1]) for x in depth.get("asks",[])[:20])
    if bids<=0 or asks<=0: raise RuntimeError("Invalid Binance orderbook")
    return make_result(symbol,"Binance",price,change24,momentum6,vol_ratio,oi_change,taker_ratio,bids/asks,funding_rate,ls_ratio,btc_change)

def score_bybit(symbol,btc_change):
    items=bybit_request("/v5/market/tickers",{"category":"linear","symbol":symbol})["result"]["list"]
    if not items: raise RuntimeError("Bybit symbol unavailable")
    t=items[0]; price=float(t["lastPrice"]); change24=float(t.get("price24hPcnt",0))*100
    raw=bybit_request("/v5/market/kline",{"category":"linear","symbol":symbol,"interval":"60","limit":25})["result"]["list"]; kl=list(reversed(raw))
    if len(kl)<13: raise RuntimeError("Insufficient Bybit kline data")
    closes=[float(x[4]) for x in kl]; vols=[float(x[5]) for x in kl]; momentum6=(closes[-1]/closes[-7]-1)*100; baseline=sum(vols[-13:-1])/12; vol_ratio=vols[-1]/baseline if baseline else 1
    rawoi=bybit_request("/v5/market/open-interest",{"category":"linear","symbol":symbol,"intervalTime":"1h","limit":2})["result"]["list"]
    if len(rawoi)<2: raise RuntimeError("Insufficient Bybit open-interest data")
    oi=list(reversed(rawoi)); a,b=float(oi[-2]["openInterest"]),float(oi[-1]["openInterest"]); oi_change=(b/a-1)*100 if a else 0
    fr=bybit_request("/v5/market/funding/history",{"category":"linear","symbol":symbol,"limit":1})["result"]["list"]
    if not fr: raise RuntimeError("No Bybit funding data")
    funding=float(fr[0]["fundingRate"])
    ls=bybit_request("/v5/market/account-ratio",{"category":"linear","symbol":symbol,"period":"1h","limit":1})["result"]["list"]
    if not ls: raise RuntimeError("No Bybit long-short data")
    ls_ratio=float(ls[0]["buyRatio"])/max(float(ls[0]["sellRatio"]),1e-9)
    depth=bybit_request("/v5/market/orderbook",{"category":"linear","symbol":symbol,"limit":25})["result"]
    bids=sum(float(x[1]) for x in depth.get("b",[])); asks=sum(float(x[1]) for x in depth.get("a",[]))
    if bids<=0 or asks<=0: raise RuntimeError("Invalid Bybit orderbook")
    trades=bybit_request("/v5/market/recent-trade",{"category":"linear","symbol":symbol,"limit":500})["result"]["list"]
    buy=sum(float(x[1])*float(x[2]) for x in trades if x.get("side")=="Buy"); sell=sum(float(x[1])*float(x[2]) for x in trades if x.get("side")=="Sell")
    if buy<=0 or sell<=0: raise RuntimeError("Invalid Bybit trade-flow sample")
    return make_result(symbol,"Bybit",price,change24,momentum6,vol_ratio,oi_change,buy/sell,bids/asks,funding,ls_ratio,btc_change)

def score_bitget(symbol,btc_change):
    items=bitget_request("/api/v2/mix/market/ticker",{"symbol":symbol,"productType":"usdt-futures"})["data"]
    if not items: raise RuntimeError("Bitget symbol unavailable")
    t=items[0]; price=float(t["lastPr"]); change24=float(t.get("change24h",0))*100
    raw=bitget_request("/api/v2/mix/market/candles",{"symbol":symbol,"productType":"usdt-futures","granularity":"1H","limit":25})["data"]; kl=list(reversed(raw))
    if len(kl)<13: raise RuntimeError("Insufficient Bitget kline data")
    closes=[float(x[4]) for x in kl]; vols=[float(x[5]) for x in kl]; momentum6=(closes[-1]/closes[-7]-1)*100; baseline=sum(vols[-13:-1])/12; vol_ratio=vols[-1]/baseline if baseline else 1
    # Bitget ticker supplies current OI but this version does not infer an OI change without historical OI.
    oi_change=0.0; funding=float(t.get("fundingRate",0))
    depth=bitget_request("/api/v2/mix/market/merge-depth",{"symbol":symbol,"productType":"usdt-futures","limit":20})["data"]
    bids=sum(float(x[1]) for x in depth.get("bids",[])); asks=sum(float(x[1]) for x in depth.get("asks",[]))
    if bids<=0 or asks<=0: raise RuntimeError("Invalid Bitget orderbook")
    trades=bitget_request("/api/v2/mix/market/fills",{"symbol":symbol,"productType":"usdt-futures","limit":100})["data"]
    buy=sum(float(x[1])*float(x[2]) for x in trades if x.get("side")=="buy"); sell=sum(float(x[1])*float(x[2]) for x in trades if x.get("side")=="sell")
    if buy<=0 or sell<=0: raise RuntimeError("Invalid Bitget trade-flow sample")
    ls=bitget_request("/api/v2/mix/market/long-short",{"symbol":symbol,"period":"1h"})["data"]
    if not ls: raise RuntimeError("No Bitget long-short data")
    ls_ratio=float(ls[0]["longShortRatio"])
    return make_result(symbol,"Bitget",price,change24,momentum6,vol_ratio,oi_change,buy/sell,bids/asks,funding,ls_ratio,btc_change)

def score_symbol(symbol,provider,btc_change):
    try:
        if provider=="Binance": return score_binance(symbol,btc_change)
        if provider=="Bybit": return score_bybit(symbol,btc_change)
        return score_bitget(symbol,btc_change)
    except Exception as e: return {"symbol":symbol,"score":-1,"signal":"ERROR","error":str(e)}

def discover_provider():
    global ACTIVE_PROVIDER
    binance_error=None; bybit_error=None
    try:
        t=binance_request("/fapi/v1/ticker/24hr",{"symbol":"BTCUSDT"}); ACTIVE_PROVIDER="Binance"; return "Binance",float(t.get("priceChangePercent",0))
    except Exception as e:
        binance_error=e; print(f"WARN: Binance unavailable: {e}")
    try:
        items=bybit_request("/v5/market/tickers",{"category":"linear","symbol":"BTCUSDT"})["result"]["list"]
        if not items: raise RuntimeError("BTCUSDT unavailable")
        ACTIVE_PROVIDER="Bybit"; return "Bybit",float(items[0].get("price24hPcnt",0))*100
    except Exception as e:
        bybit_error=e; print(f"WARN: Bybit unavailable: {e}")
    try:
        items=bitget_request("/api/v2/mix/market/ticker",{"symbol":"BTCUSDT","productType":"usdt-futures"})["data"]
        if not items: raise RuntimeError("BTCUSDT unavailable")
        ACTIVE_PROVIDER="Bitget"; return "Bitget",float(items[0].get("change24h",0))*100
    except Exception as e:
        raise SystemExit(f"FATAL: all public Futures providers unavailable. Binance={binance_error}; Bybit={bybit_error}; Bitget={e}")

def send_telegram(text):
    token,chat=os.getenv("TELEGRAM_BOT_TOKEN"),os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat: print("INFO: Telegram secrets not configured; console output only."); return False
    try:
        r=S.post(f"https://api.telegram.org/bot{token}/sendMessage",json={"chat_id":chat,"text":text},timeout=TIMEOUT)
        if not r.ok: print(f"WARN: Telegram HTTP {r.status_code}: {r.text[:200]}")
        return r.ok
    except Exception as e: print(f"WARN: Telegram unavailable: {e}"); return False

def main():
    print("ZORATHVAEL CRYPTO SCANNER V1.4")
    print("Provider strategy: Binance -> Bybit -> Bitget")
    provider,btc_change=discover_provider(); print(f"Active provider: {provider}")
    results=[]; errors=[]
    with ThreadPoolExecutor(max_workers=5) as ex:
        jobs=[ex.submit(score_symbol,s,provider,btc_change) for s in SYMBOLS[:MAX_SYMBOLS]]
        for j in as_completed(jobs):
            x=j.result()
            if x.get("score",-1)>=0: results.append(x)
            else: errors.append(f"{x['symbol']}: {x.get('error','unknown error')}")
    if not results: raise SystemExit(f"FATAL: No symbols returned valid {provider} Futures data.")
    results.sort(key=lambda x:x["score"],reverse=True)
    now=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines=["ZORATHVAEL CRYPTO SCANNER V1.4",now,f"Provider: {provider}",f"BTC 24h: {btc_change:.2f}%",""]
    for i,x in enumerate(results[:5],1):
        lines.append(f"{i}. {x['symbol']} | {x['score']:.1f} | {x['signal']}")
        lines.append(f"   Price {x['price']:.8g} | 24h {x['change24']:.2f}% | OI d {x['oi_change']:.2f}% | Taker {x['taker']:.2f}")
        lines.append(f"   Entry {x['entry_low']:.8g}-{x['entry_high']:.8g} | SL {x['sl']:.8g}")
        lines.append(f"   Position max Rp{x['position_idr']:,.0f} | TP1 {x['tp1']:.8g} | TP2 {x['tp2']:.8g} | TP3 {x['tp3']:.8g}")
    if errors:
        lines += ["",f"Warnings: {len(errors)} symbol(s) skipped due to incomplete data."]
        lines.extend(f"- {e}" for e in errors[:5])
    text="\n".join(lines); print(text); send_telegram(text)

if __name__=="__main__": main()

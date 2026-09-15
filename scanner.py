import csv
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests

VERSION = "1.9.1"
BINANCE_BASES = ["https://fapi.binance.com", "https://fapi1.binance.com", "https://fapi2.binance.com", "https://fapi3.binance.com", "https://fapi4.binance.com"]
BYBIT_BASE = "https://api.bybit.com"
BITGET_BASE = "https://api.bitget.com"
CAPITAL_IDR = 900_000
RISK_PCT = 0.02
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "SUIUSDT", "IOTAUSDT", "TAOUSDT", "AXLUSDT", "BNBUSDT", "ADAUSDT", "LINKUSDT", "AVAXUSDT", "APTUSDT", "SEIUSDT"]
TIMEOUT = 12
DATA_DIR = Path("data")
SIGNAL_FILE = DATA_DIR / "forward_test.csv"
HORIZONS = (1, 4, 12, 24)
TAKER_WINDOWS = (100, 250, 500)
CSV_FIELDS = [
    "id","timestamp","symbol","provider","price","score","bias","signal","change24h",
    "m1","m6","m24","volume_ratio","atr_pct","taker_100","taker_250","taker_500",
    "taker_ratio","taker_spread_pct","taker_stability","book_ratio","funding","entry_low",
    "entry_high","sl","position_idr","tp1","tp2","tp3","stop_pct","btc24","btc6","h1","h4","h12","h24"
]

S = requests.Session()
S.headers.update({"User-Agent": f"Zorathvael-Crypto-Scanner/{VERSION}"})

def clamp(x, a=-1, b=1):
    return max(a, min(b, x))

def sf(x, default=None):
    try: return float(x)
    except (TypeError, ValueError): return default

def get(base, path, params=None, retries=2):
    last = None
    for i in range(retries + 1):
        try:
            r = S.get(base + path, params=params, timeout=TIMEOUT)
            if r.status_code == 429 or r.status_code >= 500:
                last = RuntimeError(f"HTTP {r.status_code}: {r.text[:160]}")
                if i < retries:
                    time.sleep(0.8 * (i + 1)); continue
            if not r.ok: raise RuntimeError(f"HTTP {r.status_code}: {r.text[:160]}")
            try: return r.json()
            except Exception as e: raise RuntimeError(f"Invalid JSON: {e}") from e
        except requests.RequestException as e:
            last = RuntimeError(f"Network error: {e}")
            if i < retries: time.sleep(0.8 * (i + 1))
    raise last or RuntimeError("request failed")

def binance(path, params=None):
    errors=[]
    for base in BINANCE_BASES:
        try: return get(base, path, params)
        except Exception as e: errors.append(f"{base}: {e}")
    raise RuntimeError("Binance unavailable: " + " | ".join(errors))

def bybit(path, params=None):
    d=get(BYBIT_BASE,path,params)
    if d.get("retCode") not in (None,0): raise RuntimeError(f"retCode {d.get('retCode')}: {d.get('retMsg')}")
    return d

def bitget(path, params=None):
    d=get(BITGET_BASE,path,params)
    if d.get("code") not in (None,"00000",0): raise RuntimeError(f"code {d.get('code')}: {d.get('msg')}")
    return d

def candle_features(rows):
    if len(rows)<25: raise RuntimeError(f"Need 25+ closed candles, got {len(rows)}")
    c=[float(x[4]) for x in rows]; v=[float(x[5]) for x in rows]
    m1=(c[-1]/c[-2]-1)*100; m6=(c[-1]/c[-7]-1)*100; m24=(c[-1]/c[-25]-1)*100
    base=sum(v[-13:-1])/12; vr=v[-1]/base if base else None
    trs=[]; prev=None
    for x in rows[-15:]:
        h,l,cl=map(float,x[2:5]); trs.append(h-l if prev is None else max(h-l,abs(h-prev),abs(l-prev))); prev=cl
    atr=(sum(trs)/len(trs))/c[-1]*100 if trs else None
    return m1,m6,m24,vr,atr

def bitget_features(sym):
    raw=bitget("/api/v2/mix/market/candles",{"symbol":sym,"productType":"USDT-FUTURES","granularity":"1H","limit":26})["data"]
    return candle_features(list(reversed(raw[1:])))

def bybit_features(sym):
    raw=bybit("/v5/market/kline",{"category":"linear","symbol":sym,"interval":"60","limit":26})["result"]["list"]
    return candle_features(list(reversed(raw[1:])))

def binance_features(sym):
    return candle_features(binance("/fapi/v1/klines",{"symbol":sym,"interval":"1h","limit":26})[:-1])

def ratio_score(ratio, scale):
    if ratio is None or ratio<=0: return None
    return 50+25*clamp(math.log(ratio)/math.log(scale))

def _trade_parts(trade):
    if isinstance(trade, dict):
        side = str(trade.get("side", ""))
        price = sf(trade.get("price"))
        size = sf(trade.get("size"))
    else:
        try:
            side = str(trade[4] if len(trade) > 4 else trade[3])
            price = sf(trade[1]); size = sf(trade[2])
        except (IndexError, TypeError):
            return "", None, None
    return side, price, size

def taker_pressure(trades, buy_side, sell_side, windows=TAKER_WINDOWS):
    """Return per-window ratios, geometric aggregate, spread %, and stability."""
    ratios=[]
    normalized_buy=str(buy_side).lower(); normalized_sell=str(sell_side).lower()
    for n in windows:
        buy=sell=0.0
        for trade in list(trades)[:n]:
            side, price, size = _trade_parts(trade)
            if price is None or size is None or price <= 0 or size <= 0: continue
            side=side.lower()
            if side in (normalized_buy, "buy"):
                buy += price * size
            elif side in (normalized_sell, "sell"):
                sell += price * size
        if buy > 0 and sell > 0: ratios.append(buy/sell)
        else: ratios.append(None)
    valid=[x for x in ratios if x is not None and math.isfinite(x) and x>0]
    if not valid: return [None]*len(windows), None, None, None
    mean_log=sum(math.log(x) for x in valid)/len(valid)
    aggregate=math.exp(mean_log)
    spread_pct=(max(valid)/min(valid)-1)*100 if len(valid)>1 else 0.0
    log_std=math.sqrt(sum((math.log(x)-mean_log)**2 for x in valid)/len(valid)) if len(valid)>1 else 0.0
    stability=1/(1+log_std)
    return ratios, aggregate, spread_pct, stability

def score(f,taker,book,funding,btc):
    m1,m6,m24,vr,atr=f
    mom=50+18*clamp(m6/4)+12*clamp(m24/12)
    tak=ratio_score(taker,1.5); bk=ratio_score(book,1.35)
    vol=None if vr is None else 50+20*clamp((vr-1)/2)
    fund=None if funding is None else 50-25*min(abs(funding)/0.001,1)
    br=50+25*clamp(btc/4)
    vals={"momentum":(30,mom),"taker":(20,tak),"orderbook":(15,bk),"volume":(10,vol),"funding":(10,fund),"btc_regime":(15,br)}
    avail={k:v for k,v in vals.items() if v[1] is not None}; total=sum(v[0] for v in avail.values())
    if not total: raise RuntimeError("No scoring metrics available")
    s=sum(w*x for w,x in avail.values())/total
    dk=[k for k in ("momentum","taker","orderbook") if k in avail]; dw=sum(avail[k][0] for k in dk)
    ds=sum(avail[k][0]*(avail[k][1]-50) for k in dk)/dw
    bias="LONG" if ds>5 else "SHORT" if ds<-5 else "NEUTRAL"
    return round(s,1),bias,total/100

def risk_plan(price,atr,bias):
    if bias not in ("LONG","SHORT"): return (None,)*8
    stop_pct=max(.02,min(.07,(atr or 3)*1.5/100)); risk_cash=CAPITAL_IDR*RISK_PCT; position=min(CAPITAL_IDR,risk_cash/stop_pct)
    if bias=="SHORT":
        lo,hi=price*1.005,price*1.015; sl=hi*(1+stop_pct); r=sl-hi; tp=[hi-1.5*r,hi-3*r,hi-5*r]
    else:
        lo,hi=price*.985,price*.995; sl=lo*(1-stop_pct); r=lo-sl; tp=[lo+1.5*r,lo+3*r,lo+5*r]
    return lo,hi,sl,position,*tp,stop_pct*100

def make_result(sym,provider,price,change,f,taker,taker_windows,taker_spread,taker_stability,book,funding,btc):
    s,bias,cov=score(f,taker,book,funding,btc)
    signal="STRONG "+bias if s>=75 and bias!="NEUTRAL" and cov>=.65 else bias+" WATCH" if s>=68 and bias!="NEUTRAL" and cov>=.65 else "NO SETUP"
    plan=risk_plan(price,f[4],bias) if signal!="NO SETUP" and bias!="NEUTRAL" else (None,)*8
    return dict(symbol=sym,provider=provider,price=price,score=s,bias=bias,signal=signal,coverage=cov,change=change,m1=f[0],m6=f[1],m24=f[2],vol=f[3],atr=f[4],taker=taker,taker_windows=taker_windows,taker_spread=taker_spread,taker_stability=taker_stability,book=book,funding=funding,plan=plan)

def bitget_symbol(sym,btc):
    pt="USDT-FUTURES"; t=bitget("/api/v2/mix/market/ticker",{"symbol":sym,"productType":pt})["data"][0]
    f=bitget_features(sym); d=bitget("/api/v2/mix/market/merge-depth",{"symbol":sym,"productType":pt,"limit":20})["data"]
    bids=sum(float(x[1]) for x in d.get("bids",[])); asks=sum(float(x[1]) for x in d.get("asks",[])); book=bids/asks if bids and asks else None
    trades=bitget("/api/v2/mix/market/fills",{"symbol":sym,"productType":pt,"limit":500})["data"]
    tw,taker,spread,st=taker_pressure(trades,"buy","sell")
    return make_result(sym,"Bitget",float(t["lastPr"]),float(t.get("change24h",0))*100,f,taker,tw,spread,st,book,sf(t.get("fundingRate")),btc)

def bybit_symbol(sym,btc):
    t=bybit("/v5/market/tickers",{"category":"linear","symbol":sym})["result"]["list"][0]; f=bybit_features(sym)
    trades=bybit("/v5/market/recent-trade",{"category":"linear","symbol":sym,"limit":500})["result"]["list"]
    tw,taker,spread,st=taker_pressure(trades,"Buy","Sell")
    d=bybit("/v5/market/orderbook",{"category":"linear","symbol":sym,"limit":25})["result"]; bids=sum(float(x[1]) for x in d.get("b",[])); asks=sum(float(x[1]) for x in d.get("a",[])); book=bids/asks if bids and asks else None
    fr=bybit("/v5/market/funding/history",{"category":"linear","symbol":sym,"limit":1})["result"]["list"]; funding=float(fr[0]["fundingRate"]) if fr else None
    return make_result(sym,"Bybit",float(t["lastPrice"]),float(t.get("price24hPcnt",0))*100,f,taker,tw,spread,st,book,funding,btc)

def binance_symbol(sym,btc):
    t=binance("/fapi/v1/ticker/24hr",{"symbol":sym}); f=binance_features(sym); tr=binance("/futures/data/takerlongshortRatio",{"symbol":sym,"period":"1h","limit":1}); taker=float(tr[-1]["buySellRatio"]) if tr else None
    fr=binance("/fapi/v1/fundingRate",{"symbol":sym,"limit":1}); funding=float(fr[-1]["fundingRate"]) if fr else None
    d=binance("/fapi/v1/depth",{"symbol":sym,"limit":20}); bids=sum(float(x[1]) for x in d.get("bids",[])); asks=sum(float(x[1]) for x in d.get("asks",[])); book=bids/asks if bids and asks else None
    tw=[taker,None,None]; return make_result(sym,"Binance",float(t["lastPrice"]),float(t.get("priceChangePercent",0)),f,taker,tw,0.0,1.0,book,funding,btc)

def discover():
    try:
        t=binance("/fapi/v1/ticker/24hr",{"symbol":"BTCUSDT"}); return "Binance",float(t.get("priceChangePercent",0))
    except Exception as e: print("WARN: Binance unavailable:",e)
    try:
        t=bybit("/v5/market/tickers",{"category":"linear","symbol":"BTCUSDT"})["result"]["list"][0]; return "Bybit",float(t.get("price24hPcnt",0))*100
    except Exception as e: print("WARN: Bybit unavailable:",e)
    t=bitget("/api/v2/mix/market/ticker",{"symbol":"BTCUSDT","productType":"USDT-FUTURES"})["data"][0]; return "Bitget",float(t.get("change24h",0))*100

def btc6(provider):
    return (binance_features if provider=="Binance" else bybit_features if provider=="Bybit" else bitget_features)("BTCUSDT")[1]

def ensure_file():
    DATA_DIR.mkdir(parents=True,exist_ok=True)
    if not SIGNAL_FILE.exists():
        with SIGNAL_FILE.open("w",newline="",encoding="utf-8") as f: csv.DictWriter(f,fieldnames=CSV_FIELDS).writeheader()

def migrate_csv_schema():
    ensure_file()
    with SIGNAL_FILE.open(newline="",encoding="utf-8") as f: rows=list(csv.DictReader(f))
    if not rows: return
    if list(rows[0].keys()) == CSV_FIELDS: return
    for row in rows:
        old=row.get("taker_ratio")
        row.setdefault("taker_100", old if old else "")
        row.setdefault("taker_250", "")
        row.setdefault("taker_500", "")
        row.setdefault("taker_spread_pct", "")
        row.setdefault("taker_stability", "")
        for key in CSV_FIELDS: row.setdefault(key, "")
    with SIGNAL_FILE.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=CSV_FIELDS); w.writeheader(); w.writerows(rows)

def signal_row(x,ts,btc24,btc6v):
    p=x["plan"]; actionable=x["signal"]!="NO SETUP" and x["bias"] in ("LONG","SHORT") and p[0] is not None
    tw=x.get("taker_windows") or [None,None,None]
    return {"id":f"{ts}_{x['symbol']}","timestamp":ts,"symbol":x["symbol"],"provider":x["provider"],"price":x["price"],"score":x["score"],"bias":x["bias"],"signal":x["signal"],"change24h":x["change"],"m1":x["m1"],"m6":x["m6"],"m24":x["m24"],"volume_ratio":x["vol"],"atr_pct":x["atr"],"taker_100":tw[0],"taker_250":tw[1],"taker_500":tw[2],"taker_ratio":x["taker"],"taker_spread_pct":x.get("taker_spread"),"taker_stability":x.get("taker_stability"),"book_ratio":x["book"],"funding":x["funding"],"entry_low":p[0] if actionable else "","entry_high":p[1] if actionable else "","sl":p[2] if actionable else "","position_idr":p[3] if actionable else "","tp1":p[4] if actionable else "","tp2":p[5] if actionable else "","tp3":p[6] if actionable else "","stop_pct":p[7] if actionable else "","btc24":btc24,"btc6":btc6v,"h1":"","h4":"","h12":"","h24":""}

def append_rows(new):
    migrate_csv_schema()
    with SIGNAL_FILE.open(newline="",encoding="utf-8") as f: ids={r.get("id") for r in csv.DictReader(f)}
    fresh=[r for r in new if r["id"] not in ids]
    if fresh:
        with SIGNAL_FILE.open("a",newline="",encoding="utf-8") as f: csv.DictWriter(f,fieldnames=CSV_FIELDS,extrasaction="ignore").writerows(fresh)
    return len(fresh)

def forward_candles(provider,sym):
    if provider=="Bitget":
        raw=bitget("/api/v2/mix/market/candles",{"symbol":sym,"productType":"USDT-FUTURES","granularity":"15m","limit":110})["data"]; return list(reversed(raw))
    if provider=="Bybit":
        raw=bybit("/v5/market/kline",{"category":"linear","symbol":sym,"interval":"15","limit":110})["result"]["list"]; return list(reversed(raw))
    return binance("/fapi/v1/klines",{"symbol":sym,"interval":"15m","limit":110})

def evaluate():
    migrate_csv_schema()
    with SIGNAL_FILE.open(newline="",encoding="utf-8") as f: rows=list(csv.DictReader(f))
    now=datetime.now(timezone.utc); changed=pending=0; cache={}
    for row in rows:
        if row.get("signal")=="NO SETUP" or row.get("bias") not in ("LONG","SHORT") or not row.get("entry_low"): continue
        try: ts=datetime.fromisoformat(row["timestamp"].replace("Z","+00:00")); age=(now-ts).total_seconds()/3600
        except Exception: continue
        if age<1: pending+=1; continue
        try:
            key=(row["provider"],row["symbol"]); cache.setdefault(key,forward_candles(*key)); candles=cache[key]
            base=int(ts.timestamp()*1000); future=[c for c in candles if int(c[0])>=base]
            if not future: continue
            direction=row["bias"]; elo,ehi=float(row["entry_low"]),float(row["entry_high"]); sl,tp1=float(row["sl"]),float(row["tp1"])
            for h in HORIZONS:
                k=f"h{h}"
                if row.get(k) or age<h: continue
                entered=False; outcome="NO_ENTRY"
                for c in future[:h*4]:
                    high,low=float(c[2]),float(c[3])
                    if not entered:
                        entered=(low<=ehi and high>=elo) if direction=="LONG" else (high>=elo and low<=ehi)
                        if not entered: continue
                    slhit,tphit=(low<=sl,high>=tp1) if direction=="LONG" else (high>=sl,low<=tp1)
                    if slhit and tphit: outcome="SL_AND_TP_SAME_CANDLE"; break
                    if slhit: outcome="SL"; break
                    if tphit: outcome="TP1"; break
                if entered and outcome=="NO_ENTRY": outcome="OPEN"
                row[k]=outcome; changed+=1
        except Exception: continue
    if changed:
        with SIGNAL_FILE.open("w",newline="",encoding="utf-8") as f: w=csv.DictWriter(f,fieldnames=CSV_FIELDS); w.writeheader(); w.writerows(rows)
    return changed,pending

def validation_stats():
    migrate_csv_schema()
    with SIGNAL_FILE.open(newline="",encoding="utf-8") as f: rows=list(csv.DictReader(f))
    actionable=[r for r in rows if r.get("signal")!="NO SETUP" and r.get("bias") in ("LONG","SHORT") and r.get("entry_low")]
    out=[f"Validation: {len(actionable)} actionable snapshots / {len(rows)} total snapshots"]
    for horizon in HORIZONS:
        key=f"h{horizon}"; done=[r[key] for r in actionable if r.get(key) in ("TP1","SL","SL_AND_TP_SAME_CANDLE","NO_ENTRY","OPEN")]
        resolved=[x for x in done if x in ("TP1","SL","SL_AND_TP_SAME_CANDLE")]
        if resolved:
            tp=sum(x=="TP1" for x in resolved); amb=sum(x=="SL_AND_TP_SAME_CANDLE" for x in resolved)
            out.append(f"{horizon}h: {len(done)} evaluated | TP1 {tp}/{len(resolved)} ({tp/len(resolved):.0%}) | ambiguous {amb}")
    for side in ("LONG","SHORT"):
        g=[r for r in actionable if r.get("bias")==side]; done=[r for r in g if r.get("h1") in ("TP1","SL","SL_AND_TP_SAME_CANDLE")]
        if done:
            tp=sum(r["h1"]=="TP1" for r in done); out.append(f"1h {side}: {tp}/{len(done)} TP1 ({tp/len(done):.0%})")
    return out

def fmt_ratio(x): return "N/A" if x is None else ">9.99x" if x>=10 else f"{x:.2f}x"
def fmt_num(x): return "N/A" if x is None else f"{x:.3f}"
def fmt_taker_windows(xs): return "/".join("N/A" if x is None else (f">9.99x" if x>=10 else f"{x:.2f}x") for x in xs)

def send(text):
    tok,chat=os.getenv("TELEGRAM_BOT_TOKEN"),os.getenv("TELEGRAM_CHAT_ID")
    if not tok or not chat: print("INFO: Telegram secrets not configured; console output only."); return
    try:
        r=S.post(f"https://api.telegram.org/bot{tok}/sendMessage",json={"chat_id":chat,"text":text},timeout=TIMEOUT)
        if not r.ok: print("WARN: Telegram:",r.status_code,r.text[:160])
    except Exception as e: print("WARN: Telegram unavailable:",e)

def main():
    print(f"ZORATHVAEL CRYPTO SCANNER V{VERSION}\nProvider strategy: Binance -> Bybit -> Bitget")
    provider,btc24=discover(); print("Active provider:",provider); btc=btc6(provider)
    results=[]; errors=[]; fn=binance_symbol if provider=="Binance" else bybit_symbol if provider=="Bybit" else bitget_symbol
    with ThreadPoolExecutor(max_workers=5) as ex:
        jobs=[ex.submit(fn,s,btc) for s in SYMBOLS]
        for j in as_completed(jobs):
            try: results.append(j.result())
            except Exception as e: errors.append(str(e))
    results.sort(key=lambda x:(x["score"],x["coverage"]),reverse=True); ts=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    added=append_rows([signal_row(x,ts,btc24,btc) for x in results]); evaluated,pending=evaluate()
    lines=[f"ZORATHVAEL CRYPTO SCANNER V{VERSION}",datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),f"Provider: {provider}",f"BTC 24h: {btc24:.2f}% | BTC 6h: {btc:.2f}%",f"Coverage: {len(results)}/{len(SYMBOLS)}",""]
    for i,x in enumerate(results[:10],1):
        p=x["plan"]; tw=x.get("taker_windows") or [None,None,None]; funding="N/A" if x["funding"] is None else f"{x['funding']:.6g}"
        lines += [f"{i}. {x['symbol']} | {x['score']:.1f} | {x['signal']} | Core signal coverage {x['coverage']:.0%}",f"   Bias {x['bias']} | Price {x['price']:.8g} | 24h {x['change']:.2f}% | 1h {x['m1']:.2f}% | 6h {x['m6']:.2f}% | 24h-trend {x['m24']:.2f}%",f"   Vol {fmt_num(x['vol'])}x | ATR {fmt_num(x['atr'])}% | Taker 100/250/500 {fmt_taker_windows(tw)} | Agg {fmt_ratio(x['taker'])} | Spread {fmt_num(x.get('taker_spread'))}% | Stability {fmt_num(x.get('taker_stability'))} | Book {fmt_ratio(x['book'])} | Funding {funding}","   Optional data: OI N/A | Long/Short N/A"]
        if x["signal"]!="NO SETUP" and x["bias"] in ("LONG","SHORT"): lines += [f"   Entry {p[0]:.8g}-{p[1]:.8g} | SL {p[2]:.8g} ({p[7]:.2f}%) | Pos Rp{p[3]:,.0f}",f"   TP1 {p[4]:.8g} | TP2 {p[5]:.8g} | TP3 {p[6]:.8g}"]
        elif x["bias"]=="NEUTRAL": lines.append("   Trade plan: N/A (NEUTRAL bias)")
        else: lines.append("   Trade plan: N/A (signal below threshold)")
    if errors: lines += [f"\nFailed symbols: {len(errors)}"]+[" - "+e for e in errors[:15]]
    lines += ["",f"Forward-test store: {SIGNAL_FILE.as_posix()} | snapshots added: {added} | outcomes updated: {evaluated} | pending: {pending}"]+validation_stats()+["","Score is setup quality, NOT probability of profit.","Forward-test results are observational and must not be treated as guaranteed performance.","OI and Long/Short are intentionally not fabricated when reliable public historical data is unavailable.","Forward test uses 15m candles and the original signal provider for outcome evaluation.","Taker pressure uses 100/250/500-fill geometric aggregation; stability is an auditable consistency metric and is not used in score."]
    text="\n".join(lines); print(text); send(text)

if __name__=="__main__": main()

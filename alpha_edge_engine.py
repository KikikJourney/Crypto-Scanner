"""Unified Alpha Edge Hunter engine.

Production architecture:
REGIME -> LIQUIDITY -> FLOW -> STRUCTURE -> DISPLACEMENT -> PULLBACK
-> TIMING -> EDGE EVIDENCE -> GEOMETRY -> TELEGRAM.

Calibration and margin geometry are deliberately independent.
No 40-candle rule is used.
"""
import csv, json, math, os, time, sys
from datetime import datetime, timezone
from pathlib import Path
import requests

VERSION = "qwen-alpha-hunter-v1"
BINANCE = os.getenv("BINANCE_BASE_URL", "https://fapi.binance.com").rstrip("/")
BITGET = os.getenv("BITGET_BASE_URL", "https://api.bitget.com").rstrip("/")
MARGIN = 10.0
LEVERAGE = 20
SL_MARGIN_PCT = -10.0
TP_MARGIN_PCTS = (30.0, 60.0, 120.0)
MAX_SYMBOLS = int(os.getenv("EDGE_MAX_SYMBOLS", "40"))
MIN_TURNOVER = float(os.getenv("EDGE_MIN_TURNOVER", "10000000"))
TIMEOUT = 12
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Zorathvael-AI-Market-Engine/1.0"})

# Hugging Face financial foundation model: Kronos-small.
# The model is the market-decision engine; deterministic features are context
# and execution/risk guards, not the primary signal generator.
AI_MODEL_ID = os.getenv("AI_MODEL_ID", "NeoQuasar/Kronos-small")
AI_TOKENIZER_ID = os.getenv("AI_TOKENIZER_ID", "NeoQuasar/Kronos-Tokenizer-base")
AI_CONTEXT = int(os.getenv("AI_CONTEXT", "256"))
AI_HORIZON = int(os.getenv("AI_HORIZON", "12"))
AI_SAMPLES = int(os.getenv("AI_SAMPLES", "1"))
AI_ON_QWEN_CANDIDATES = os.getenv("AI_ON_QWEN_CANDIDATES", "0") == "1"
AI_MIN_EDGE = float(os.getenv("AI_MIN_EDGE", "0.0015"))
QWEN_MODEL_ID = os.getenv("QWEN_MODEL_ID", "Qwen/Qwen3-0.6B")
QWEN_SCREEN_SYMBOLS = int(os.getenv("QWEN_SCREEN_SYMBOLS", "12"))
QWEN_MAX_PICKS = int(os.getenv("QWEN_MAX_PICKS", "4"))
_QWEN_MODEL = None
_QWEN_TOKENIZER = None
_QWEN_LOCK = __import__("threading").Lock()
_AI_PREDICTOR = None
_AI_LOCK = __import__("threading").Lock()

def load_ai_engine():
    global _AI_PREDICTOR
    if _AI_PREDICTOR is not None:
        return _AI_PREDICTOR
    with _AI_LOCK:
        if _AI_PREDICTOR is not None:
            return _AI_PREDICTOR
        vendor=os.getenv("KRONOS_VENDOR_PATH",".vendor/kronos")
        if vendor not in sys.path:
            sys.path.insert(0,vendor)
        from model import Kronos, KronosTokenizer, KronosPredictor
        import torch
        device="cuda:0" if torch.cuda.is_available() else "cpu"
        tok=KronosTokenizer.from_pretrained(AI_TOKENIZER_ID)
        model=Kronos.from_pretrained(AI_MODEL_ID)
        model.eval(); tok.eval()
        _AI_PREDICTOR=KronosPredictor(model,tok,device=device,max_context=AI_CONTEXT)
        print(f"AI_ENGINE_READY model={AI_MODEL_ID} device={device} context={AI_CONTEXT}")
    return _AI_PREDICTOR

def ai_market_forecast(rows):
    """Run the Hugging Face financial foundation model and turn its forecast into market intelligence."""
    import pandas as pd
    if len(rows)<AI_CONTEXT+20:return None
    data=rows[-AI_CONTEXT:]
    ts=pd.Series(pd.to_datetime([x["t"] for x in data],unit="ms",utc=True))
    df=pd.DataFrame({
        "open":[x["o"] for x in data],"high":[x["h"] for x in data],
        "low":[x["l"] for x in data],"close":[x["c"] for x in data],
        "volume":[x["v"] for x in data],
    })
    step=ts.iloc[-1]-ts.iloc[-2]
    yts=pd.Series([ts.iloc[-1]+step*(i+1) for i in range(AI_HORIZON)])
    predictor=load_ai_engine()
    pred=predictor.predict(df,ts,yts,pred_len=AI_HORIZON,T=0.9,top_p=0.9,sample_count=AI_SAMPLES,verbose=False)
    last=df["close"].iloc[-1]
    closes=pred["close"].astype(float).values
    highs=pred["high"].astype(float).values
    lows=pred["low"].astype(float).values
    ret=(closes[-1]/last)-1 if last else 0
    path_ret=(float(closes.mean())/last)-1 if last else 0
    upside=(float(highs.max())/last)-1 if last else 0
    downside=(float(lows.min())/last)-1 if last else 0
    direction="LONG" if ret>AI_MIN_EDGE and path_ret>0 else "SHORT" if ret<-AI_MIN_EDGE and path_ret<0 else "NEUTRAL"
    separation=abs(ret)/(abs(upside-downside)+1e-9)
    confidence=max(0,min(100,round(50+separation*50+min(25,abs(ret)*10000))))
    return {"model":AI_MODEL_ID,"direction":direction,"confidence":confidence,
            "return":ret,"path_return":path_ret,"upside":upside,"downside":downside,
            "forecast_close":float(closes[-1]),"forecast_high":float(highs.max()),
            "forecast_low":float(lows.min()),"horizon":AI_HORIZON}

def load_qwen_engine():
    global _QWEN_MODEL, _QWEN_TOKENIZER
    if _QWEN_MODEL is not None:
        return _QWEN_TOKENIZER, _QWEN_MODEL
    with _QWEN_LOCK:
        if _QWEN_MODEL is not None:
            return _QWEN_TOKENIZER, _QWEN_MODEL
        import torch
        from transformers import AutoTokenizer, AutoModelForCausalLM
        tok = AutoTokenizer.from_pretrained(QWEN_MODEL_ID)
        model = AutoModelForCausalLM.from_pretrained(
            QWEN_MODEL_ID, torch_dtype=torch.bfloat16, device_map="auto", low_cpu_mem_usage=True
        )
        model.eval()
        _QWEN_TOKENIZER, _QWEN_MODEL = tok, model
        print(f"QWEN_ENGINE_READY model={QWEN_MODEL_ID}")
    return _QWEN_TOKENIZER, _QWEN_MODEL

def _qwen_json(text):
    text=text.strip()
    if "</think>" in text:
        text=text.split("</think>")[-1].strip()
    start=text.find("["); end=text.rfind("]")
    if start<0 or end<=start: return []
    try:
        obj=json.loads(text[start:end+1])
        return obj if isinstance(obj,list) else []
    except Exception:
        return []

def qwen_screen(ticks, source):
    """Qwen is the primary intelligence layer that screens the liquid universe before entry calibration."""
    packets=[]
    for t in ticks[:QWEN_SCREEN_SYMBOLS]:
        sym=t.get("symbol","")
        try:
            rr=fetch_candles(source,sym,"15m",90)
            if len(rr)<60: continue
            closes=[x["c"] for x in rr]; vols=[x["v"] for x in rr]; p=closes[-1] or 1
            e20=ema(closes,20); e50=ema(closes,50); a=atr(rr,14)
            vr=(sum(vols[-5:])/5)/(sum(vols[-25:-5])/20 or 1)
            hi=max(x["h"] for x in rr[-48:]); lo=min(x["l"] for x in rr[-48:])
            packets.append({
                "symbol":sym,"price":p,"chg_3":(p/closes[-4]-1)*100,
                "chg_12":(p/closes[-13]-1)*100,"chg_24":(p/closes[-25]-1)*100,
                "atr_pct":(a/p*100) if p else 0,"rsi":rsi(rr),"volume_ratio":vr,
                "ema20_50_pct":((e20/e50)-1)*100 if e50 else 0,
                "range_pos":(p-lo)/(hi-lo) if hi>lo else .5,
                "last_body_pct":abs(rr[-1]["c"]-rr[-1]["o"])/p*100 if p else 0,
                "turnover":f(t.get("quoteVolume",t.get("usdtVolume",0)))
            })
        except Exception:
            continue
    if not packets: return {}
    prompt = """You are Qwen, the primary crypto-futures screening intelligence for a 15m scalping Alpha Hunter.
Select only coins with a credible LONG bottom-entry or SHORT top-entry setup forming now.
Prefer exhaustion/reversal, liquidity location, favorable trend transition, volume confirmation and non-chasing price location.
Reject extended moves, weak liquidity, contradictory structure and noise. The next stage calculates exact pullback entry/SL/TP.
Return ONLY JSON array, max PICKS objects, ranked best first:
{"symbol":"XXXUSDT","direction":"LONG|SHORT","score":0-100,"reason":"brief evidence"}
Do not force picks.
MARKET TABLE:
""".replace("PICKS",str(QWEN_MAX_PICKS))+json.dumps(packets,separators=(",",":"))
    tok,model=load_qwen_engine()
    messages=[{"role":"system","content":"You are a disciplined quantitative crypto-futures market screener. Output strict JSON when requested."},
              {"role":"user","content":prompt}]
    inputs=tok.apply_chat_template(messages,add_generation_prompt=True,tokenize=True,
                                   return_dict=True,return_tensors="pt",enable_thinking=False)
    inputs={k:v.to(model.device) for k,v in inputs.items()}
    import torch
    with torch.inference_mode():
        out=model.generate(**inputs,max_new_tokens=96,do_sample=False)
    text_out=tok.decode(out[0][inputs["input_ids"].shape[-1]:],skip_special_tokens=False)
    picks=_qwen_json(text_out)
    allowed={p["symbol"] for p in packets}; clean={}
    for p in picks:
        if not isinstance(p,dict): continue
        sym=str(p.get("symbol","")).upper(); direction=str(p.get("direction","")).upper()
        if sym in allowed and direction in ("LONG","SHORT"):
            clean[sym]={"direction":direction,"score":max(0,min(100,f(p.get("score"),0))),
                        "reason":str(p.get("reason",""))[:240],"model":QWEN_MODEL_ID}
    print(f"QWEN_SCREEN_DONE universe={len(packets)} picks={len(clean)}")
    return clean

def f(x, d=0.0):
    try:
        x=float(x)
        return x if math.isfinite(x) else d
    except Exception:
        return d

def api(base, path, params=None):
    r=SESSION.get(base+path, params=params or {}, timeout=TIMEOUT)
    r.raise_for_status()
    j=r.json()
    return j

def binance(path, params=None):
    return api(BINANCE, path, params)

def bitget(path, params=None):
    return api(BITGET, path, params)

def candles(rows):
    return [{"t":int(x[0]),"o":f(x[1]),"h":f(x[2]),"l":f(x[3]),"c":f(x[4]),"v":f(x[5])} for x in rows]

def ema(xs,n):
    if not xs:return 0
    n=min(n,len(xs)); e=sum(xs[:n])/n; k=2/(n+1)
    for x in xs[n:]: e=x*k+e*(1-k)
    return e

def atr(r,n=14):
    if len(r)<n+1:return 0
    tr=[max(x["h"]-x["l"],abs(x["h"]-r[i-1]["c"]),abs(x["l"]-r[i-1]["c"])) for i,x in enumerate(r[1:],1)]
    return sum(tr[-n:])/n

def rsi(r,n=14):
    if len(r)<n+1:return 50
    g=l=0
    for i in range(len(r)-n,len(r)):
        d=r[i]["c"]-r[i-1]["c"]; g+=max(d,0); l+=max(-d,0)
    if l==0:return 100
    return 100-100/(1+(g/n)/(l/n))

def percentile(xs,p):
    xs=sorted(xs)
    if not xs:return 0
    i=(len(xs)-1)*p; lo=int(i); hi=min(lo+1,len(xs)-1); q=i-lo
    return xs[lo]*(1-q)+xs[hi]*q

def regime(r):
    p=r[-1]["c"]; a=atr(r); ap=100*a/p if p else 0
    vr=(sum(x["v"] for x in r[-10:])/10)/(sum(x["v"] for x in r[-30:-10])/20 or 1)
    e20,e50=ema([x["c"] for x in r],20),ema([x["c"] for x in r],50)
    drift=100*abs(e20-e50)/p if p else 0
    if ap>=1.2 or vr>=2.0: kind="expansion"
    elif drift>=0.45: kind="trend"
    else: kind="range"
    return {"type":kind,"atr_pct":round(ap,4),"volume_ratio":round(vr,3),"ema_drift_pct":round(drift,4)}

def liquidity_event(r, direction):
    if len(r)<12:return {"sweep":False,"strength":0}
    last=r[-1]; prior=r[-8:-1]
    lo=min(x["l"] for x in prior); hi=max(x["h"] for x in prior)
    if direction=="LONG":
        swept=last["l"]<lo and last["c"]>lo
        wick=last["c"]-last["l"]
    else:
        swept=last["h"]>hi and last["c"]<hi
        wick=last["h"]-last["c"]
    body=abs(last["c"]-last["o"]) or (last["h"]-last["l"])*0.1
    strength=min(1.0,(wick/body)/3) if swept else 0
    return {"sweep":swept,"strength":round(strength,3),"prior_low":lo,"prior_high":hi}

def flow_features(r, direction):
    if len(r)<25:return {"delta":0,"impulse":0,"exhaustion":0,"volume_ratio":0}
    signed=[(1 if x["c"]>x["o"] else -1 if x["c"]<x["o"] else 0)*x["v"] for x in r]
    delta=sum(signed[-5:])/(sum(abs(x) for x in signed[-20:]) or 1)
    move=(r[-1]["c"]-r[-4]["c"])/r[-4]["c"]
    impulse=move if direction=="LONG" else -move
    avg=sum(abs(x) for x in signed[-20:-5])/15 or 1
    exhaustion=max(0,1-abs(sum(signed[-5:]))/(avg*5))
    vr=(sum(x["v"] for x in r[-3:])/3)/(sum(x["v"] for x in r[-20:-3])/17 or 1)
    return {"delta":round(delta,4),"impulse":round(impulse,5),"exhaustion":round(exhaustion,3),"volume_ratio":round(vr,3)}

def pullback_calibration(r, direction):
    """Find a reachable retracement zone after a displacement; no 40-candle extreme."""
    if len(r)<60:return None
    a=atr(r); recent=r[-36:]
    if direction=="LONG":
        lo=min(x["l"] for x in recent[:-4]); hi=max(x["h"] for x in recent[:-4])
        leg=max(0,hi-lo); current=r[-1]["c"]
        if leg<=0:return None
        # Find the most recent bullish displacement leg.
        disp=(current-lo)/leg
        z1=hi-leg*0.50; z2=hi-leg*0.786
        zone_lo,zone_hi=min(z1,z2),max(z1,z2)
        inside=zone_lo<=current<=zone_hi
        trigger=current>r[-2]["c"] and r[-1]["c"]>r[-1]["o"]
    else:
        hi=max(x["h"] for x in recent[:-4]); lo=min(x["l"] for x in recent[:-4])
        leg=max(0,hi-lo); current=r[-1]["c"]
        if leg<=0:return None
        z1=lo+leg*0.50; z2=lo+leg*0.786
        zone_lo,zone_hi=min(z1,z2),max(z1,z2)
        inside=zone_lo<=current<=zone_hi
        trigger=current<r[-2]["c"] and r[-1]["c"]<r[-1]["o"]
    distance=abs(current-(zone_lo+zone_hi)/2)/(a or current*.01)
    timing=max(0,min(100,100-distance*28)) if inside else max(0,70-distance*18)
    return {"zone_low":zone_lo,"zone_high":zone_hi,"inside":inside,"timing":round(timing,2),
            "trigger":trigger,"leg":leg,"atr":a,"disp":round(disp,4)}

def external_features(symbol, source="Binance"):
    out={"open_interest":None,"funding":None,"crowding":None,"taker_ratio":None,"source":"unavailable"}
    try:
        if source == "Binance":
            oi=binance("/fapi/v1/openInterest",{"symbol":symbol})
            fr=binance("/fapi/v1/premiumIndex",{"symbol":symbol})
            out["open_interest"]=f(oi.get("openInterest"))
            out["funding"]=f(fr.get("lastFundingRate"))
            out["source"]="Binance"
        else:
            oi=bitget("/api/v2/mix/market/open-interest",{"productType":"USDT-FUTURES","symbol":symbol})
            fr=bitget("/api/v2/mix/market/current-fund-rate",{"productType":"USDT-FUTURES","symbol":symbol})
            oirows=oi.get("data",[]) if isinstance(oi,dict) else []
            frrows=fr.get("data",[]) if isinstance(fr,dict) else []
            out["open_interest"]=f((oirows[0] if oirows else {}).get("openInterest"))
            out["funding"]=f((frrows[0] if frrows else {}).get("fundingRate"))
            out["source"]="Bitget"
        # Crowding uses account long/short ratio when available.
        try:
            ls=binance("/futures/data/globalLongShortAccountRatio",{"symbol":symbol,"period":"5m","limit":1})
            out["crowding"]=f(ls[-1].get("longShortRatio")) if ls else None
            taker=binance("/futures/data/takerlongshortRatio",{"symbol":symbol,"period":"5m","limit":1})
            out["taker_ratio"]=f(taker[-1].get("buySellRatio")) if taker else None
        except Exception: pass
    except Exception:
        try:
            fr=bitget("/api/v2/mix/market/current-fund-rate",{"productType":"USDT-FUTURES","symbol":symbol})
            out["funding"]=f(fr.get("data",[{}])[0].get("fundingRate"))
            out["source"]="Bitget"
        except Exception: pass
    return out

def fetch_candles(source, symbol, interval, limit):
    if source == "Binance":
        return candles(binance("/fapi/v1/klines",{"symbol":symbol,"interval":interval,"limit":limit})[:-1])
    gran={"5m":"5m","15m":"15m","1h":"1H","4h":"4H"}[interval]
    j=bitget("/api/v2/mix/market/candles",{"productType":"USDT-FUTURES","symbol":symbol,"granularity":gran,"limit":limit})
    rows=j.get("data",[]) if isinstance(j,dict) else j
    return candles([x for x in reversed(rows)])

def mtf(symbol, source):
    data={}
    for interval,limit in (("15m",160),("1h",120),("4h",80)):
        data[interval]=fetch_candles(source,symbol,interval,limit)
    return data

def candidate(symbol, ticker, source, qwen_pick=None):
    try:
        r=fetch_candles(source,symbol,"5m",220)
        if len(r)<160:return None
        p=f(ticker.get("lastPrice",ticker.get("lastPr")))
        reg=regime(r); tfs=mtf(symbol,source)
        ai=ai_market_forecast(r) if AI_ON_QWEN_CANDIDATES else None
        if not ai and not qwen_pick: return None
        ext=external_features(symbol,source)
        a5=atr(r); e20=ema([x["c"] for x in r],20); e50=ema([x["c"] for x in r],50)
        results=[]
        directions=[qwen_pick["direction"]] if qwen_pick else ([ai["direction"]] if ai and ai["direction"]!="NEUTRAL" else [])
        for direction in directions:
            liq=liquidity_event(r,direction); flow=flow_features(r,direction); pb=pullback_calibration(r,direction)
            if not pb:continue
            closes=[x["c"] for x in r]
            structure=(p>e50 and e20>e50) if direction=="LONG" else (p<e50 and e20<e50)
            displacement=flow["impulse"]>0.0015
            flow_ok=flow["delta"]>0.05 if direction=="LONG" else flow["delta"]<-0.05
            sweep_bonus=liq["strength"]
            # OI/funding/crowding are evidence layers, not binary blockers.
            funding=ext["funding"]
            crowd=ext["crowding"]
            crowd_score=0.5
            if crowd is not None:
                crowd_score=max(0,min(1,0.5-0.35*(crowd-1 if direction=="LONG" else 1/crowd-1)))
            fund_score=0.5
            if funding is not None:
                fund_score=max(0,min(1,0.5-(funding*1000 if direction=="LONG" else -funding*1000)*0.15))
            taker=ext.get("taker_ratio")
            taker_score=0.5
            if taker is not None:
                taker_score=max(0,min(1,0.5+(taker-1.0)*0.35*(1 if direction=="LONG" else -1)))
            mtf_score=0
            for rr in tfs.values():
                q=rr[-1]["c"]; ee=ema([x["c"] for x in rr],min(50,len(rr)))
                mtf_score += 1 if (q>ee if direction=="LONG" else q<ee) else 0
            score=(20*(1 if structure else 0)+18*min(1,max(0,flow["delta"]*5+0.5))
                   +15*min(1,max(0,flow["impulse"]*150))
                   +15*min(1,sweep_bonus+0.15)+12*(mtf_score/3)
                   +7*fund_score+8*crowd_score+5*taker_score)
            if pb["trigger"]:score+=8
            if ai:
                score += 15*(ai["confidence"]/100)
                if direction==ai["direction"]: score += 8
            if qwen_pick:
                score += 28*(qwen_pick["score"]/100)
            quality=max(0,min(100,round(score,2)))
            # The entry zone is calibration only. Geometry is applied later.
            results.append((quality,direction,liq,flow,pb,ext,mtf_score))
        if not results:return None
        results.sort(reverse=True,key=lambda x:x[0]); q,d,liq,flow,pb,ext,mtfs=results[0]
        if q<52:return None
        # Require event sequence, but do not require every data source to exist.
        event_score=sum([liq["sweep"],flow["impulse"]>0,flow["exhaustion"]>0.25,pb["trigger"]])
        if event_score<1:return None
        if pb["timing"]<45: return None
        entry=(pb["zone_low"]+pb["zone_high"])/2
        # Use current price only for execution state; never redefine calibration.
        zone_lo,zone_hi=pb["zone_low"],pb["zone_high"]
        sl_move=abs(SL_MARGIN_PCT)/LEVERAGE/100
        tp_moves=[x/LEVERAGE/100 for x in TP_MARGIN_PCTS]
        if d=="LONG":
            sl=entry*(1-sl_move); tps=[entry*(1+x) for x in tp_moves]
        else:
            sl=entry*(1+sl_move); tps=[entry*(1-x) for x in tp_moves]
        return {"symbol":symbol.replace("USDT",""),"symbol_full":symbol,"direction":d,"price":p,
                "entry":entry,"entry_zone_low":zone_lo,"entry_zone_high":zone_hi,"stop":sl,
                "tp1":tps[0],"tp2":tps[1],"tp3":tps[2],"quality":q,"timing":pb["timing"],"ai_engine":ai or {},
                "qwen_screen":qwen_pick or {},
                "regime":reg,"liquidity":liq,"flow":flow,"pullback":pb,"external":ext,
                "mtf_score":mtfs,"calibration":"pullback-50/78.6% displacement retracement",
                "geometry":{"margin_usdt":MARGIN,"leverage":LEVERAGE,"sl_margin_pct":SL_MARGIN_PCT,
                            "tp_margin_pcts":TP_MARGIN_PCTS}}
    except Exception as e:
        return None

def universe():
    try:
        info=binance("/fapi/v1/exchangeInfo")
        ticks=binance("/fapi/v1/ticker/24hr")
        active={x["symbol"] for x in info["symbols"] if x.get("status")=="TRADING" and x.get("contractType")=="PERPETUAL" and x.get("quoteAsset")=="USDT"}
        rows=[x for x in ticks if x.get("symbol") in active and f(x.get("quoteVolume"))>=MIN_TURNOVER]
        return sorted(rows,key=lambda x:f(x.get("quoteVolume")),reverse=True)[:MAX_SYMBOLS],"Binance"
    except Exception:
        data=bitget("/api/v2/mix/market/tickers",{"productType":"USDT-FUTURES"})
        rows=data.get("data",[]) if isinstance(data,dict) else data
        rows=[x for x in rows if f(x.get("usdtVolume",x.get("quoteVolume",0)))>=MIN_TURNOVER]
        return sorted(rows,key=lambda x:f(x.get("usdtVolume",x.get("quoteVolume",0))),reverse=True)[:MAX_SYMBOLS],"Bitget"

def load_edge_evidence():
    p=Path("edge_evidence.json")
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8")).get("summary",[])
        except Exception: pass
    p=Path("data/edge_evidence.csv")
    if not p.exists():return {"status":"NO_EVIDENCE","n":0,"expectancy_r":0}
    with open(p,newline="",encoding="utf-8") as fh: rows=list(csv.DictReader(fh))
    vals=[]
    for x in rows:
        try: vals.append(float(x.get("net_r","")))
        except: pass
    if not vals:return {"status":"NO_EVIDENCE","n":0,"expectancy_r":0}
    wins=sum(v>0 for v in vals); gross_win=sum(v for v in vals if v>0); gross_loss=-sum(v for v in vals if v<0)
    return {"status":"OBSERVED","n":len(vals),"win_rate":wins/len(vals),"expectancy_r":sum(vals)/len(vals),
            "profit_factor":gross_win/gross_loss if gross_loss else float("inf")}

def format_price(v):
    v=f(v)
    d=2 if v>=1000 else 4 if v>=1 else 6 if v>=.01 else 8 if v>=.0001 else 10
    return f"{v:.{d}f}".rstrip("0").rstrip(".")

def telegram_text(x):
    e=x["geometry"]
    return "\n".join([
        f"🏛️ ZORATHVAEL ALPHA EDGE | {x['direction']} {x['symbol']}",
        f"Live: {format_price(x['price'])}",
        "",
        "ENTRY CALIBRATION",
        f"Entry zone: {format_price(x['entry_zone_low'])} – {format_price(x['entry_zone_high'])}",
        f"Calibrated entry: {format_price(x['entry'])}",
        f"Pullback timing: {x['timing']}/100",
        f"Qwen Screen: {x['qwen_screen'].get('model','n/a')} | {x['qwen_screen'].get('direction',x['direction'])} {x['qwen_screen'].get('score',0):.0f}/100",
        f"Qwen rationale: {x['qwen_screen'].get('reason','')}",
        f"Kronos forecast: {x['ai_engine'].get('return',0)*100:.3f}% | Path: {x['ai_engine'].get('path_return',0)*100:.3f}%",
        f"Quality: {x['quality']}/100",
        "",
        "EXECUTION GEOMETRY",
        f"SL: {format_price(x['stop'])}  (-10% margin)",
        f"TP1: {format_price(x['tp1'])} (+30% margin)",
        f"TP2: {format_price(x['tp2'])} (+60% margin)",
        f"TP3: {format_price(x['tp3'])} (+120% margin)",
        f"Margin: {e['margin_usdt']} USDT | Leverage: {e['leverage']}x",
        "",
        "EDGE CONTEXT",
        f"Regime: {x['regime']['type']} | ATR: {x['regime']['atr_pct']}%",
        f"Liquidity sweep: {x['liquidity']['sweep']} | Flow Δ: {x['flow']['delta']}",
        f"Displacement: {x['flow']['impulse']} | Exhaustion: {x['flow']['exhaustion']}",
        f"Funding: {x['external']['funding']} | Crowding: {x['external']['crowding']}",
        f"MTF alignment: {x['mtf_score']}/3 | Data: {x['external']['source']}",
        "",
        "Rule: calibration determines WHERE/WHEN; geometry determines SL/TP. Do not substitute one for the other."
    ])

def scan():
    ticks,source=universe()
    qwen=qwen_screen(ticks,source)
    out=[]
    ranked=[t for t in ticks if t.get("symbol","") in qwen]
    ranked.sort(key=lambda t: qwen[t.get("symbol","")].get("score",0), reverse=True)
    for t in ranked[:QWEN_MAX_PICKS]:
        sym=t.get("symbol","")
        pick=qwen.get(sym)
        if not pick: continue
        x=candidate(sym,t,source,pick)
        if x: out.append(x)
    out.sort(key=lambda x:(x["quality"],x["timing"],x["qwen_screen"].get("score",0)),reverse=True)
    return {"timestamp":datetime.now(timezone.utc).isoformat(),"version":VERSION,"transport":source,
            "universe":len(ticks),"qwen_screened":len(qwen),"qwen_picks":list(qwen.values()),
            "results":out[:10],"edge_evidence":load_edge_evidence()}

def notify(result):
    tok,chat=os.getenv("TELEGRAM_BOT_TOKEN"),os.getenv("TELEGRAM_CHAT_ID")
    if not tok or not chat:return False
    texts=[telegram_text(x) for x in result["results"]]
    if not texts:texts=["🏛️ ZORATHVAEL ALPHA EDGE\nNO ACTIONABLE SETUP — event sequence/calibration did not qualify."]
    for msg in texts:
        r=SESSION.post(f"https://api.telegram.org/bot{tok}/sendMessage",json={"chat_id":chat,"text":msg},timeout=15)
        r.raise_for_status()
    return True

if __name__=="__main__":
    result=scan()
    Path("scanner_result.json").write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding="utf-8")
    print(json.dumps(result,indent=2,ensure_ascii=False))
    notify(result)

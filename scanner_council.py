import os,json,time,requests
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
BASE=os.getenv('BITGET_BASE_URL','https://api.bitget.com').rstrip('/')
PRODUCT='USDT-FUTURES'
TRANSPORT_MODE='bitget'
S=requests.Session();S.headers.update({'User-Agent':'Zorathvael-Scanner-Council/2.0','Accept':'application/json'})
CFG={'limit':60,'minvol':15000000,'top':50,'cons':45,'tp':2.0,'sl':1.5,'ai':3,'timeout':15}
def f(x,d=0.0):
    try:return float(x)
    except:return d
def api(path,p=None):
    try:
        r=S.get(BASE+path,params=p or {},timeout=CFG['timeout'])
        ct=(r.headers.get('content-type') or '').lower(); body=r.text[:240].replace('\\n',' ')
        if r.status_code>=400: raise RuntimeError(f'Bitget HTTP {r.status_code}: {body}')
        if 'json' not in ct and not r.text.lstrip().startswith(('{','[')): raise RuntimeError(f'Bitget non-JSON: {body}')
        j=r.json()
        if str(j.get('code'))!='00000': raise RuntimeError(f"Bitget API {j.get('code')}: {j.get('msg')}")
        return j.get('data',[])
    except Exception as e:
        raise RuntimeError('Bitget unavailable: '+str(e))

def ema(a,n):
    if len(a)<n:return a[-1]
    k=2/(n+1);e=sum(a[:n])/n
    for x in a[n:]:e=x*k+e*(1-k)
    return e
def rsi(a,n=14):
    if len(a)<n+1:return 50
    g=l=0
    for i in range(len(a)-n,len(a)):
        d=a[i]-a[i-1];g+=max(d,0);l+=max(-d,0)
    return 100 if not l else 100-100/(1+(g/n)/(l/n))
def atr(h,l,c,n=14):
    t=[max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])) for i in range(1,len(c))]
    return sum(t[-n:])/n if len(t)>=n else c[-1]*.02
def regime(c,h,l,v,a,p):
    ed=abs(ema(c,20)-ema(c,50))/p*100;rp=(max(h[-30:])-min(l[-30:]))/p*100;ap=a/p*100;vr=sum(v[-10:])/10/(sum(v[-30:])/30 or 1)
    if ed>.5 and rp>1.5 and ap>.3:t='trending'
    elif ap>.8 or vr>1.8:t='volatile'
    else:t='ranging'
    return {'type':t,'desc':t+' | ATR %.2f%% | Vol %.1fx'%(ap,vr),'atrPct':ap,'emaDiff':ed,'volRatio':vr}
def weights(t):
    if t=='trending':return {'wyckoff':1,'of':1.3,'exh':1,'sm':1.5,'struct':.8,'whale':1.8,'mtf':2,'pb':1.2}
    if t=='volatile':return {'wyckoff':1.5,'of':1.5,'exh':1.8,'sm':1.2,'struct':1,'whale':1.5,'mtf':.8,'pb':1.5}
    return {'wyckoff':1.2,'of':1,'exh':1,'sm':1.2,'struct':1.5,'whale':1,'mtf':.8,'pb':1.2}
def agent(i,n,s,sc,reason,conf):return {'id':i,'name':n,'signal':s,'score':sc,'reason':reason,'conf':conf}
def mtf(a,b,c,p):
    x=[[f(z[4]) for z in q] for q in (a,b,c)];t=['bull' if p>ema(q,50) else 'bear' for q in x]
    return {'trend15':t[0],'trend1h':t[1],'trend4h':t[2],'bullCount':t.count('bull'),'bearCount':t.count('bear')}
def pullback(c,h,l,v,d,p,m):
    hi,lo=max(h[-20:]),min(l[-20:]);rr=(hi-p)/(hi-lo or 1);x={'status':'none','direction':'NEUTRAL','retracement':rr*100,'conf':50,'reason':'none','volumeOk':sum(v[-3:])/3<sum(v[-20:])/20*.8}
    if m['trend4h']=='bull' and .15<rr<.8:x.update(status='active' if rr<.382 else 'ending',direction='LONG',conf=70 if rr<.382 else 80,reason='bull pullback %.0f%%'%(rr*100))
    elif m['trend4h']=='bear' and .15<rr<.8:x.update(status='active' if rr<.382 else 'ending',direction='SHORT',conf=70 if rr<.382 else 80,reason='bear rally %.0f%%'%(rr*100))
    return x
def screen(sym,t):
  try:
    k,k15,k1,k4=[api('/api/v2/mix/market/candles',{'symbol':sym,'productType':PRODUCT,'granularity':q,'limit':60}) for q in ('5m','15m','1H','4H')]
    top=api('/api/v2/mix/market/long-short',{'symbol':sym,'period':'5m'});gl=api('/api/v2/mix/market/account-long-short',{'symbol':sym,'period':'5m'});tr=api('/api/v2/mix/market/fills',{'symbol':sym,'productType':PRODUCT,'limit':100})
    c=[f(x[4]) for x in k];o=[f(x[1]) for x in k];h=[f(x[2]) for x in k];l=[f(x[3]) for x in k];v=[f(x[5]) for x in k];p=f(t['lastPr']);a=atr(h,l,c);d=[f(x[9])-f(x[10]) for x in k];cv=[];z=0
    for q in d:z+=q;cv.append(z)
    r=regime(c,h,l,v,a,p);m=mtf(k15,k1,k4,p);ag=[];e21=ema(c,21);e50=ema(c,50);rv=rsi(c);rl=min(l[-20:-1]);rh=max(h[-20:-1]);ll,lh,lc,lo=l[-1],h[-1],c[-1],o[-1];lw=min(lc,lo)-ll;uw=lh-max(lc,lo);bd=abs(lc-lo);rg=lh-ll or 1
    if ll<rl*.997 and lc>rl and lw>bd and lw>rg*.3:ag.append(agent('wyckoff','Wyckoff','LONG',22,'Spring',80))
    elif lh>rh*1.003 and lc<rh and uw>bd and uw>rg*.3:ag.append(agent('wyckoff','Wyckoff','SHORT',22,'Upthrust',80))
    elif p<e21 and p<e50 and rv<35:ag.append(agent('wyckoff','Wyckoff','LONG',12,'Oversold RSI %.1f'%rv,55))
    elif p>e21 and p>e50 and rv>65:ag.append(agent('wyckoff','Wyckoff','SHORT',12,'Overbought RSI %.1f'%rv,55))
    else:ag.append(agent('wyckoff','Wyckoff','NEUTRAL',0,'No pattern',50))
    dr=sum(d[-5:]);s='LONG' if dr>0 else 'SHORT' if dr<0 else 'NEUTRAL';ag.append(agent('of','OrderFlow',s,22 if dr else 0,'Delta '+s,75 if dr else 50))
    flat=(max(cv[-10:])-min(cv[-10:]))/p<.01;avg=sum(abs(x) for x in d[-20:])/20;dec=abs(d[-1])/(avg or 1);pm=(c[-1]-c[-6])/c[-6]*100;s='LONG' if d[-1]<0 and dec<.7 and flat and pm<-.15 else 'SHORT' if d[-1]>0 and dec<.7 and flat and pm>.15 else 'NEUTRAL';ag.append(agent('exh','Exhaustion',s,25 if s!='NEUTRAL' else 0,'CVD/exhaustion',80 if s!='NEUTRAL' else 50))
    tp=f(top[-1].get('longShortRatio',1)) if top else 1;gs=f(gl[-1].get('longShortAccountRatio',1)) if gl else 1;s='LONG' if (gs<=.6 and tp>=1.2) or tp>=1.2 else 'SHORT' if (gs>=1.8 and tp<=.85) or tp<=.85 else 'NEUTRAL';ag.append(agent('sm','SmartMoney',s,25 if (gs<=.6 and tp>=1.2) or (gs>=1.8 and tp<=.85) else 12 if s!='NEUTRAL' else 0,'Positioning',85 if s!='NEUTRAL' else 50))
    rhi,rlo=max(h[-60:]),min(l[-60:]);pos=(p-rlo)/(rhi-rlo or 1);s='LONG' if pos<.2 else 'SHORT' if pos>.8 else 'LONG' if pos<.35 else 'SHORT' if pos>.65 else 'NEUTRAL';ag.append(agent('struct','Structure',s,20 if pos<.2 or pos>.8 else 10 if s!='NEUTRAL' else 0,'Range %.0f%%'%(pos*100),75 if s!='NEUTRAL' else 50))
    wb=ws=wbv=wsv=0
    for x in tr:
      usd=f(x.get('price'))*f(x.get('size'))
      if usd>=30000:
       side=str(x.get('side','')).lower()
       if side=='buy':wb+=1;wbv+=usd
       elif side=='sell':ws+=1;wsv+=usd
    wr=wbv/(wbv+wsv or 1);s='LONG' if wb+ws>=2 and wr>=.6 else 'SHORT' if wb+ws>=2 and wr<=.4 else 'NEUTRAL';ag.append(agent('whale','Whale',s,22 if s!='NEUTRAL' else 0,'Whale flow',80 if s!='NEUTRAL' else 40))
    s='LONG' if m['bullCount']>=2 else 'SHORT' if m['bearCount']>=2 else 'NEUTRAL';ag.append(agent('mtf','MTF',s,22 if abs(m['bullCount']-m['bearCount'])==3 else 12 if s!='NEUTRAL' else 0,'4H/1H/15m alignment',85 if abs(m['bullCount']-m['bearCount'])==3 else 60))
    pb=pullback(c,h,l,v,d,p,m);s=pb['direction'] if pb['status']=='ending' else 'NEUTRAL';ag.append(agent('pb','Pullback',s,20 if s!='NEUTRAL' else 0,pb['reason'],pb['conf']))
    w=weights(r['type']);ls=sh=lw=sw=tw=0
    for x in ag:
      x['weight']=w[x['id']];tw+=x['weight']
      if x['signal']=='LONG':ls+=x['score']*x['weight'];lw+=x['weight']
      elif x['signal']=='SHORT':sh+=x['score']*x['weight'];sw+=x['weight']
    direction='LONG' if ls>sh else 'SHORT' if sh>ls else None
    if not direction:return None
    win,opp,ww=(ls,sh,lw) if direction=='LONG' else (sh,ls,sw);cons=max(0,min(100,round((win-opp*.5)/(120*tw)*100)))
    if cons<CFG['cons'] or ww<2:return None
    if direction=='LONG':sl=rl-a*.8;sl=p-a*CFG['sl'] if sl>=p else sl;tp=p+a*CFG['tp'];rr=(tp-p)/(p-sl)
    else:sl=rh+a*.8;sl=p+a*CFG['sl'] if sl<=p else sl;tp=p-a*CFG['tp'];rr=(p-tp)/(sl-p)
    return {'symbol':sym.replace('USDT',''),'direction':direction,'price':p,'entry':p,'tp':tp,'sl':sl,'rr':rr,'consensus':cons,'longScore':ls,'shortScore':sh,'agents':ag,'weights':w,'regime':r,'mtf':m,'pullback':pb,'topPos':top,'globalLS':gs,'rsi':rv,'atr':a,'atrPct':a/p*100,'rangePos':pos*100,'change24':f(t.get('change24h'))}
  except Exception as e:print('WARN',sym,e);return None
def moderator(x):
  q=json.dumps({'task':'Synthesize 8 agent discussion. JSON only.','symbol':x['symbol'],'regime':x['regime'],'consensus':x['consensus'],'direction':x['direction'],'agents':x['agents']})
  for m in ('mistral','llama','openai-fast',''):
   try:
    u='https://text.pollinations.ai/'+requests.utils.quote(q)+(('?model='+m) if m else '');r=S.get(u,timeout=CFG['timeout']);a=json.loads(r.text[r.text.find('{'):r.text.rfind('}')+1]);v=str(a.get('verdict','SKIP')).upper();v='LONG' if 'LONG' in v and 'SHORT' not in v else 'SHORT' if 'SHORT' in v and 'LONG' not in v else 'SKIP';return {'verdict':v,'score':max(0,min(100,int(a.get('score',50)))),'reasoning':str(a.get('reasoning',''))[:250],'provider':m or 'default'}
   except Exception:pass
  return {'verdict':'ERROR','score':0,'reasoning':'AI moderator unavailable','provider':'-'}
def scan():
  contracts=api('/api/v2/mix/market/contracts',{'productType':PRODUCT});ticks=api('/api/v2/mix/market/tickers',{'productType':PRODUCT})
  tm={x['symbol']:x for x in ticks}
  syms=[x['symbol'] for x in contracts if x.get('symbolType')=='perpetual' and x.get('quoteCoin')=='USDT' and x.get('symbolStatus')=='normal' and f(tm.get(x['symbol'],{}).get('quoteVolume'))>CFG['minvol']]
  syms=sorted(syms,key=lambda s:f(tm[s]['quoteVolume']),reverse=True)[:CFG['top']];out=[]
  print(f'TRANSPORT={TRANSPORT_MODE} | Bitget USDT-FUTURES | symbols={len(syms)}')
  with ThreadPoolExecutor(max_workers=3 if TRANSPORT_MODE=='direct' else 4) as ex:
   for q in as_completed([ex.submit(screen,s,tm[s]) for s in syms]):
    x=q.result()
    if x:out.append(x)
  out.sort(key=lambda x:x['consensus'],reverse=True)
  for x in out[:CFG['ai']]:x['ai']=moderator(x)
  return {'timestamp':datetime.now(timezone.utc).isoformat(),'transport':TRANSPORT_MODE,'scanned':len(syms),'results':out}
def fmt(v):
  v=f(v);d=2 if v>=1000 else 4 if v>=1 else 6 if v>=.01 else 8 if v>=.0001 else 10;return f'{v:.{d}f}'.rstrip('0').rstrip('.')
def notify(x):
  tok,chat=os.getenv('TELEGRAM_BOT_TOKEN'),os.getenv('TELEGRAM_CHAT_ID')
  if not tok or not chat:return
  z=['🏛️ ZORATHVAEL SCANNER COUNCIL',x['timestamp'],f"Transport {x.get('transport','unknown')} | Universe {x['scanned']}"]
  for q in x['results'][:10]:
   z += ['',f"{q['direction']} {q['symbol']} | Consensus {q['consensus']}%",f"Entry {fmt(q['entry'])} | TP {fmt(q['tp'])} | SL {fmt(q['sl'])} | RR {q['rr']:.2f}R",f"Regime {q['regime']['type']} | 4H {q['mtf']['trend4h']} 1H {q['mtf']['trend1h']} 15m {q['mtf']['trend15']}"]
   if q.get('ai'):z.append(f"AI {q['ai']['verdict']} {q['ai']['score']}/100: {q['ai']['reasoning']}")
  try:S.post(f'https://api.telegram.org/bot{tok}/sendMessage',json={'chat_id':chat,'text':'\n'.join(z)},timeout=15)
  except Exception as e:print('Telegram error',e)
if __name__=='__main__':
  try:
    x=scan();print(json.dumps(x,indent=2,ensure_ascii=False));notify(x)
  except RuntimeError as e:
    print('DATA_UNAVAILABLE: '+str(e))
    print('No signal emitted; Bitget Futures transport/data was unavailable.')

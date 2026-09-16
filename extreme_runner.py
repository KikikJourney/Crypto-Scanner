"""V2.2 Extreme Reversal production runner."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
import csv
from pathlib import Path
import scanner_v2 as core
from universe_runner import active_symbols,select_scan_symbols
from extreme_market_data import build_features
from extreme_reversal_layer import classify,append_rows,append_snapshots,evaluate_forward,signal_row,snapshot_row
from extreme_event_stats import format_summary
from actionable_reversal_layer import build_action_plan
from actionable_forward_test import evaluate as evaluate_actionable,format_summary as actionable_summary
WORKERS=8
ACTIONABLE_FILE=Path('data/actionable_signals.csv')
ACTIONABLE_FIELDS=['id','timestamp','symbol','provider','direction','score','entry','trigger','stop','target','risk_pct','reward_r','reason']
def _rows(sym,provider):
    if provider=='Bitget':return core.normalize_bitget_candles(core.bitget('/api/v2/mix/market/candles',{'symbol':sym,'productType':'USDT-FUTURES','granularity':'15m','limit':194})['data'])
    if provider=='Bybit':return core.normalize_bybit_candles(core.bybit('/v5/market/kline',{'category':'linear','symbol':sym,'interval':'15','limit':194})['result']['list'])
    return core.binance('/fapi/v1/klines',{'symbol':sym,'interval':'15m','limit':194})[:-1]
def scan_one(sym,provider,btc24):
    result=core.fetch_symbol(sym,provider,btc24);features=build_features(_rows(sym,provider),result['price']);result['extreme_features']=features;result['extreme']=classify(features);return result
def _build_action_rows(extreme_results):
    rows=[]
    for x in extreme_results:
        f=x['extreme_features'];e=x['extreme'];p=build_action_plan(f,e['direction'])
        if p['status'] not in {'ACTION LONG','ACTION SHORT'}:continue
        rows.append({'id':f"{f['timestamp']}_{x['symbol']}_{e['direction']}_{p['trigger']}",'timestamp':f['timestamp'],'symbol':x['symbol'],'provider':x['provider'],'direction':e['direction'],'score':e['score'],'entry':p['trigger'],'trigger':p['trigger'],'stop':p['stop'],'target':p['target'],'risk_pct':p['risk_pct'],'reward_r':p['reward_r'],'reason':p['reason']})
    return rows
def _write_actionable(rows):
    ACTIONABLE_FILE.parent.mkdir(parents=True,exist_ok=True)
    with ACTIONABLE_FILE.open('w',newline='',encoding='utf-8') as f:csv.DictWriter(f,fieldnames=ACTIONABLE_FIELDS).writeheader();csv.DictWriter(f,fieldnames=ACTIONABLE_FIELDS).writerows(rows)
def _print_action_candidates(extreme_results):
    print('ACTIONABLE EXTREME OUTPUT:')
    if not extreme_results:print('NONE — no extreme candidate reached the V2.2 gate');return
    action_rows=_build_action_rows(extreme_results)
    for x in extreme_results[:20]:
        f=x['extreme_features'];e=x['extreme'];p=build_action_plan(f,e['direction'])
        print(f"{x['symbol']} | {p['status']} | trigger {p.get('trigger','-')} | stop {p.get('stop','-')} | target {p.get('target','-')} | risk {p.get('risk_pct','-')}% | {p.get('reason','')}")
    _write_actionable(action_rows)
def _load_forward_rows():
    from extreme_reversal_layer import EXTREME_FORWARD_FILE
    with EXTREME_FORWARD_FILE.open(newline='',encoding='utf-8') as f:return list(csv.DictReader(f))
def main():
    provider,btc24=core.discover();symbols=active_symbols(provider);scan_symbols,liquid_n,mover_n=select_scan_symbols(provider,symbols)
    print(f'Extreme scan universe: {len(symbols)} active {provider} USDT perpetual symbols');print(f'Extreme deep scan: {len(scan_symbols)} symbols | liquidity bucket={liquid_n} | mover bucket={mover_n} | workers={WORKERS}')
    results=[];errors=[]
    with ThreadPoolExecutor(max_workers=min(WORKERS,len(scan_symbols))) as ex:
        futures={ex.submit(scan_one,s,provider,btc24):s for s in scan_symbols}
        for future in as_completed(futures):
            s=futures[future]
            try:results.append(future.result())
            except Exception as exc:errors.append((s,str(exc)))
    results.sort(key=lambda x:(x['extreme']['score'] if x['extreme']['score'] is not None else -1),reverse=True);ts=datetime.now(timezone.utc).isoformat()
    added=append_rows([signal_row(x,x['extreme_features'],ts) for x in results]);snapshot_added=append_snapshots([snapshot_row(x,x['extreme_features'],ts) for x in results])
    extreme=[x for x in results if x['extreme']['status'].startswith('EXTREME REVERSAL')];print('TOP EXTREME CANDIDATES:')
    if not extreme:print('NONE — no true-extreme reversal passed the V2.2 gate')
    for rank,x in enumerate(extreme[:20],1):
        e=x['extreme'];f=x['extreme_features'];print(f"{rank}. {x['symbol']} | {e['status']} | score {e['score']:.1f} | 24hPos {f['h1_pos_24']:.2f} | 48hPos {f['h1_pos_48']:.2f} | lowDist {f['dist_low_atr']:.2f}ATR | highDist {f['dist_high_atr']:.2f}ATR")
    _print_action_candidates(extreme)
    if not extreme:_write_actionable([])
    print(f'Extreme scan coverage: {len(results)}/{len(scan_symbols)}');
    if errors:
        print(f'Extreme symbol errors: {len(errors)}')
        for s,e in errors[:10]:print(f' - {s}: {e}')
    print(f'Extreme market snapshots added: {snapshot_added}');print(f'Extreme forward-test outcomes updated: {evaluate_forward()}');print(f'Extreme forward-test rows added: {added}');print(format_summary(_load_forward_rows()))
    actionable=evaluate_actionable();print(actionable_summary(actionable))
if __name__=='__main__':main()

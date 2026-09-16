"""V2.2 Extreme Reversal production runner.

Runs after the existing dynamic scanner, then verifies candidates against
closed 15m/1h extreme data and a dedicated market-snapshot stream.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import scanner_v2 as core
from universe_runner import active_symbols, select_scan_symbols
from extreme_market_data import build_features
from extreme_reversal_layer import classify, append_rows, append_snapshots, evaluate_forward, signal_row, snapshot_row
from extreme_event_stats import format_summary

WORKERS=16


def _rows(sym, provider):
    if provider=='Bitget':
        raw=core.bitget('/api/v2/mix/market/candles',{'symbol':sym,'productType':'USDT-FUTURES','granularity':'15m','limit':194})['data']
        return core.normalize_bitget_candles(raw)
    if provider=='Bybit':
        raw=core.bybit('/v5/market/kline',{'category':'linear','symbol':sym,'interval':'15','limit':194})['result']['list']
        return core.normalize_bybit_candles(raw)
    raw=core.binance('/fapi/v1/klines',{'symbol':sym,'interval':'15m','limit':194})
    return raw[:-1]


def scan_one(sym,provider,btc24):
    result=core.fetch_symbol(sym,provider,btc24)
    features=build_features(_rows(sym,provider),result['price'])
    extreme=classify(features)
    result['extreme_features']=features
    result['extreme']=extreme
    return result


def main():
    provider,btc24=core.discover()
    symbols=active_symbols(provider)
    scan_symbols,liquid_n,mover_n=select_scan_symbols(provider,symbols)
    print(f'Extreme scan universe: {len(symbols)} active {provider} USDT perpetual symbols')
    print(f'Extreme deep scan: {len(scan_symbols)} symbols | liquidity bucket={liquid_n} | mover bucket={mover_n} | workers={WORKERS}')
    results=[];errors=[]
    with ThreadPoolExecutor(max_workers=min(WORKERS,len(scan_symbols))) as ex:
        futures={ex.submit(scan_one,s,provider,btc24):s for s in scan_symbols}
        for future in as_completed(futures):
            s=futures[future]
            try:results.append(future.result())
            except Exception as exc:errors.append((s,str(exc)))
    results.sort(key=lambda x:(x['extreme']['score'] if x['extreme']['score'] is not None else -1),reverse=True)
    ts=datetime.now(timezone.utc).isoformat()
    rows=[signal_row(x,x['extreme_features'],ts) for x in results]
    snapshots=[snapshot_row(x,x['extreme_features'],ts) for x in results]
    added=append_rows(rows)
    snapshot_added=append_snapshots(snapshots)
    print('TOP EXTREME CANDIDATES:')
    extreme=[x for x in results if x['extreme']['status'].startswith('EXTREME REVERSAL')]
    if not extreme: print('NONE — no true-extreme reversal passed the V2.2 gate')
    for rank,x in enumerate(extreme[:20],1):
        e=x['extreme']; f=x['extreme_features']
        print(f"{rank}. {x['symbol']} | {e['status']} | score {e['score']:.1f} | 24hPos {f['h1_pos_24']:.2f} | 48hPos {f['h1_pos_48']:.2f} | lowDist {f['dist_low_atr']:.2f}ATR | highDist {f['dist_high_atr']:.2f}ATR")
    print(f'Extreme scan coverage: {len(results)}/{len(scan_symbols)}')
    if errors:
        print(f'Extreme symbol errors: {len(errors)}')
        for s,e in errors[:10]:print(f' - {s}: {e}')
    print(f'Extreme market snapshots added: {snapshot_added}')
    print(f'Extreme forward-test outcomes updated: {evaluate_forward()}')
    print(f'Extreme forward-test rows added: {added}')
    print(format_summary(_load_forward_rows()))


def _load_forward_rows():
    import csv
    from extreme_reversal_layer import EXTREME_FORWARD_FILE
    with EXTREME_FORWARD_FILE.open(newline='',encoding='utf-8') as f:
        return list(csv.DictReader(f))


if __name__=='__main__':main()

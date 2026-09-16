import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import scanner_v2 as core
from diagnostic_v21 import diagnostic_status
from early_reversal_layer import classify as early_classify, append_rows as append_early_rows, evaluate_forward as evaluate_early_forward, stats as early_stats, signal_row as early_signal_row

PRODUCT = 'USDT-FUTURES'
WATCHLIST_FILE = Path('data/universe_watchlist.csv')
LIQUIDITY_BUCKET = 220
MOVER_BUCKET = 80
MAX_SCAN_SYMBOLS = LIQUIDITY_BUCKET + MOVER_BUCKET
SCAN_WORKERS = 8

_ORIGINAL_MAKE_RESULT = core.make_result

def _make_result_with_components(sym, provider, price, f, tf, book, funding, change):
    result = _ORIGINAL_MAKE_RESULT(sym, provider, price, f, tf, book, funding, change)
    result.update({
        'long_location': f['long_location'],
        'long_exhaustion': f['long_exhaust'],
        'long_flow': result['flow'] if result['direction'] == 'LONG' else core.taker_flow(tf['agg']),
        'long_reclaim': f['long_reclaim'],
        'long_expansion': result['expansion'],
        'short_location': f['short_location'],
        'short_exhaustion': f['short_exhaust'],
        'short_flow': 1.0 - core.taker_flow(tf['agg']),
        'short_reject': f['short_reject'],
        'short_expansion': result['expansion'],
    })
    return result

core.make_result = _make_result_with_components

WATCHLIST_FIELDS = [
    'timestamp','rank','symbol','score','long_score','short_score','score_gap_to_70','bias','diagnostic_status','blocker','long_blocker','short_blocker',
    'early_status','early_direction','early_score','early_blocker','early_location','early_exhaustion','early_flow','early_structure',
    'direction','signal','location','exhaustion','flow','reclaim','expansion',
    'long_location','long_exhaustion','long_flow','long_reclaim','long_expansion',
    'short_location','short_exhaustion','short_flow','short_reject','short_expansion',
    'price','range_pos','atr_pct','volume_ratio','taker_ratio','taker_stability','taker_fills','book_ratio','funding','24h_change','selection'
]


def active_bitget_symbols():
    data = core.bitget('/api/v2/mix/market/contracts', {'productType': PRODUCT})['data']
    out = []
    for x in data:
        if str(x.get('symbolStatus', '')).lower() != 'normal': continue
        if str(x.get('quoteCoin', '')).upper() != 'USDT': continue
        if str(x.get('symbolType', '')).lower() != 'perpetual': continue
        sym = str(x.get('symbol', '')).upper()
        if sym.endswith('USDT'): out.append(sym)
    return sorted(set(out))


def active_binance_symbols():
    data = core.binance('/fapi/v1/exchangeInfo')
    return sorted({x['symbol'] for x in data['symbols'] if x.get('status') == 'TRADING' and x.get('contractType') == 'PERPETUAL' and x.get('quoteAsset') == 'USDT'})


def active_bybit_symbols():
    out, cursor = [], ''
    while True:
        params = {'category': 'linear', 'limit': 1000}
        if cursor: params['cursor'] = cursor
        d = core.bybit('/v5/market/instruments-info', params)['result']
        for x in d.get('list', []):
            if x.get('status') == 'Trading' and x.get('quoteCoin') == 'USDT' and x.get('contractType') == 'LinearPerpetual': out.append(x['symbol'])
        cursor = d.get('nextPageCursor', '')
        if not cursor: break
    return sorted(set(out))


def active_symbols(provider):
    if provider == 'Bitget': return active_bitget_symbols()
    if provider == 'Binance': return active_binance_symbols()
    return active_bybit_symbols()


def _num(x):
    try: return float(x)
    except (TypeError, ValueError): return 0.0


def select_scan_symbols(provider, symbols):
    if provider == 'Bitget':
        raw = core.bitget('/api/v2/mix/market/tickers', {'productType': PRODUCT})['data']
        symbol_set = set(symbols)
        ticker = {str(x.get('symbol', '')).upper(): x for x in raw if str(x.get('symbol', '')).upper() in symbol_set}
        liquid = sorted(symbols, key=lambda s: _num(ticker.get(s, {}).get('quoteVolume')), reverse=True)[:LIQUIDITY_BUCKET]
        movers = sorted(symbols, key=lambda s: abs(_num(ticker.get(s, {}).get('change24h'))), reverse=True)[:MOVER_BUCKET]
        return sorted(set(liquid) | set(movers)), len(liquid), len(movers)
    return symbols, len(symbols), 0


def write_watchlist(results, ts):
    WATCHLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for rank, x in enumerate(results, 1):
        d = diagnostic_status(x)
        e = early_classify(x)
        if x['direction'] in ('LONG', 'SHORT') and x['score'] >= 70: selection = 'TARGET'
        elif e['direction'] in ('LONG', 'SHORT') and e['status'].startswith('EARLY REVERSAL'): selection = 'EARLY'
        elif x['direction'] in ('LONG', 'SHORT') and x['score'] >= 55: selection = 'WATCH'
        elif x['score'] >= 50: selection = 'MONITOR'
        else: selection = 'SKIP'
        rows.append({
            'timestamp': ts, 'rank': rank, 'symbol': x['symbol'], 'score': round(x['score'], 1),
            'long_score': d['long_score'], 'short_score': d['short_score'], 'score_gap_to_70': d['score_gap_to_70'],
            'bias': d['bias'], 'diagnostic_status': d['status'], 'blocker': d['blocker'],
            'long_blocker': d['long_blocker'], 'short_blocker': d['short_blocker'],
            'early_status': e['status'], 'early_direction': e['direction'], 'early_score': e['score'] if e['score'] is not None else '',
            'early_blocker': e['blocker'], 'early_location': e['location'] if e['location'] is not None else '',
            'early_exhaustion': e['exhaustion'] if e['exhaustion'] is not None else '', 'early_flow': e['flow'] if e['flow'] is not None else '',
            'early_structure': e['structure'] if e['structure'] is not None else '',
            'direction': x['direction'], 'signal': x['signal'], 'location': round(x['location'], 3),
            'exhaustion': round(x['exhaustion'], 3), 'flow': round(x['flow'], 3), 'reclaim': round(x['reclaim'], 3),
            'expansion': round(x['expansion'], 3),
            'long_location': round(x['long_location'], 3), 'long_exhaustion': round(x['long_exhaustion'], 3),
            'long_flow': round(x['long_flow'], 3), 'long_reclaim': round(x['long_reclaim'], 3), 'long_expansion': round(x['long_expansion'], 3),
            'short_location': round(x['short_location'], 3), 'short_exhaustion': round(x['short_exhaustion'], 3),
            'short_flow': round(x['short_flow'], 3), 'short_reject': round(x['short_reject'], 3), 'short_expansion': round(x['short_expansion'], 3),
            'price': x['price'], 'range_pos': x['range_pos'], 'atr_pct': x['atr_pct'], 'volume_ratio': x['volume_ratio'],
            'taker_ratio': x['taker'], 'taker_stability': x['taker_stability'], 'taker_fills': x['taker_fills'],
            'book_ratio': x['book'], 'funding': x['funding'], '24h_change': x['change'], 'selection': selection,
        })
    with WATCHLIST_FILE.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=WATCHLIST_FIELDS); writer.writeheader(); writer.writerows(rows)


def main():
    provider, btc24 = core.discover()
    symbols = active_symbols(provider)
    if not symbols: raise RuntimeError('Dynamic futures universe is empty')
    scan_symbols, liquid_n, mover_n = select_scan_symbols(provider, symbols)
    print(f'Universe: {len(symbols)} active {provider} USDT perpetual symbols')
    print(f'Deep scan: {len(scan_symbols)} symbols | liquidity bucket={liquid_n} | mover bucket={mover_n} | workers={SCAN_WORKERS}')
    results, errors = [], []
    with ThreadPoolExecutor(max_workers=min(SCAN_WORKERS, len(scan_symbols))) as executor:
        futures = {executor.submit(core.fetch_symbol, s, provider, btc24): s for s in scan_symbols}
        for future in as_completed(futures):
            symbol = futures[future]
            try: results.append(future.result())
            except Exception as exc: errors.append((symbol, str(exc)))
    results.sort(key=lambda x: x['score'], reverse=True)
    ts = datetime.now(timezone.utc).isoformat()
    early_rows = [early_signal_row(x, ts) for x in results]
    early_added = append_early_rows(early_rows)
    write_watchlist(results, ts)
    print(f'Deep-scan coverage: {len(results)}/{len(scan_symbols)}')
    print(f'Universe coverage retained as discovery: {len(symbols)}/{len(symbols)}')
    print('TOP DIAGNOSTIC CANDIDATES:')
    for rank, x in enumerate(results[:25], 1):
        d = diagnostic_status(x); e = early_classify(x)
        early_tag = f" | EARLY {e['score']:.1f}" if e['status'].startswith('EARLY REVERSAL') else ''
        print(f"{rank}. {x['symbol']} | L {d['long_score']:.1f} S {d['short_score']:.1f} | {d['status']} | gap {d['score_gap_to_70']:.1f} | {d['blocker']}{early_tag}")
    if errors:
        print(f'Symbol errors: {len(errors)}')
        for symbol, error in errors[:20]: print(f' - {symbol}: {error}')
    print(f'Watchlist saved: {WATCHLIST_FILE}')
    print(f'Early forward-test rows added: {early_added}')
    with core.SIGNAL_FILE.open(newline='', encoding='utf-8') as f:
        snapshots = list(csv.DictReader(f))
    print(f'Early forward-test outcomes updated: {evaluate_early_forward(snapshots)}')
    print(early_stats())


if __name__ == '__main__': main()

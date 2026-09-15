import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import scanner_v2 as core
from diagnostic_v21 import diagnostic_status

PRODUCT = 'USDT-FUTURES'
WATCHLIST_FILE = Path('data/universe_watchlist.csv')
# Keep the dynamic universe broad, but only deep-scan the most liquid / active contracts.
# This removes hundreds of per-symbol API calls while retaining a separate momentum-mover bucket.
LIQUIDITY_BUCKET = 220
MOVER_BUCKET = 80
MAX_SCAN_SYMBOLS = LIQUIDITY_BUCKET + MOVER_BUCKET
SCAN_WORKERS = 16

WATCHLIST_FIELDS = [
    'timestamp','rank','symbol','score','long_score','short_score','score_gap_to_70','bias','diagnostic_status','blocker',
    'direction','signal','location','exhaustion','flow','reclaim','expansion','price','range_pos','atr_pct','volume_ratio',
    'taker_ratio','taker_stability','taker_fills','book_ratio','funding','24h_change','selection'
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
    """Cheap first-stage universe filter; deep scanner remains unchanged."""
    if provider == 'Bitget':
        raw = core.bitget('/api/v2/mix/market/tickers', {'productType': PRODUCT})['data']
        ticker = {str(x.get('symbol', '')).upper(): x for x in raw if str(x.get('symbol', '')).upper() in set(symbols)}
        liquid = sorted(symbols, key=lambda s: _num(ticker.get(s, {}).get('quoteVolume')), reverse=True)[:LIQUIDITY_BUCKET]
        movers = sorted(symbols, key=lambda s: abs(_num(ticker.get(s, {}).get('change24h'))), reverse=True)[:MOVER_BUCKET]
        selected = sorted(set(liquid) | set(movers))
        return selected, len(liquid), len(movers)

    # Fallback providers: use their existing all-symbol universe when no reliable
    # bulk quote-volume filter is available. Concurrency is still increased below.
    return symbols, len(symbols), 0


def write_watchlist(results, ts):
    WATCHLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for rank, x in enumerate(results, 1):
        d = diagnostic_status(x)
        if x['direction'] in ('LONG', 'SHORT') and x['score'] >= 70: selection = 'TARGET'
        elif x['direction'] in ('LONG', 'SHORT') and x['score'] >= 55: selection = 'WATCH'
        elif x['score'] >= 50: selection = 'MONITOR'
        else: selection = 'SKIP'
        rows.append({
            'timestamp': ts, 'rank': rank, 'symbol': x['symbol'], 'score': round(x['score'], 1),
            'long_score': d['long_score'], 'short_score': d['short_score'], 'score_gap_to_70': d['score_gap_to_70'],
            'bias': d['bias'], 'diagnostic_status': d['status'], 'blocker': d['blocker'],
            'direction': x['direction'], 'signal': x['signal'], 'location': round(x['location'], 3),
            'exhaustion': round(x['exhaustion'], 3), 'flow': round(x['flow'], 3), 'reclaim': round(x['reclaim'], 3),
            'expansion': round(x['expansion'], 3), 'price': x['price'], 'range_pos': x['range_pos'],
            'atr_pct': x['atr_pct'], 'volume_ratio': x['volume_ratio'], 'taker_ratio': x['taker'],
            'taker_stability': x['taker_stability'], 'taker_fills': x['taker_fills'], 'book_ratio': x['book'],
            'funding': x['funding'], '24h_change': x['change'], 'selection': selection,
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
    core.append_rows([core.signal_row(x, ts) for x in results]); write_watchlist(results, ts)
    print(f'Deep-scan coverage: {len(results)}/{len(scan_symbols)}')
    print(f'Universe coverage retained as discovery: {len(symbols)}/{len(symbols)}')
    print('TOP DIAGNOSTIC CANDIDATES:')
    for rank, x in enumerate(results[:25], 1):
        d = diagnostic_status(x)
        print(f"{rank}. {x['symbol']} | L {d['long_score']:.1f} S {d['short_score']:.1f} | {d['status']} | gap {d['score_gap_to_70']:.1f} | {d['blocker']}")
    if errors:
        print(f'Symbol errors: {len(errors)}')
        for symbol, error in errors[:20]: print(f' - {symbol}: {error}')
    print(f'Watchlist saved: {WATCHLIST_FILE}')
    print(f'Forward-test outcomes updated: {core.evaluate_forward()}')
    print(core.validation_stats())


if __name__ == '__main__': main()

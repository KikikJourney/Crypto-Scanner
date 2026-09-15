import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import scanner_v2 as core

PRODUCT = 'USDT-FUTURES'
WATCHLIST_FILE = Path('data/universe_watchlist.csv')
WATCHLIST_FIELDS = [
    'timestamp','rank','symbol','score','direction','signal','location','exhaustion',
    'flow','reclaim','expansion','price','range_pos','atr_pct','volume_ratio',
    'taker_ratio','taker_stability','taker_fills','book_ratio','funding','24h_change','selection'
]


def active_bitget_symbols():
    data = core.bitget('/api/v2/mix/market/contracts', {'productType': PRODUCT})['data']
    out = []
    for x in data:
        if str(x.get('symbolStatus', '')).lower() != 'normal':
            continue
        if str(x.get('quoteCoin', '')).upper() != 'USDT':
            continue
        if str(x.get('symbolType', '')).lower() != 'perpetual':
            continue
        sym = str(x.get('symbol', '')).upper()
        if sym.endswith('USDT'):
            out.append(sym)
    return sorted(set(out))


def active_binance_symbols():
    data = core.binance('/fapi/v1/exchangeInfo')
    return sorted({
        x['symbol'] for x in data['symbols']
        if x.get('status') == 'TRADING'
        and x.get('contractType') == 'PERPETUAL'
        and x.get('quoteAsset') == 'USDT'
    })


def active_bybit_symbols():
    out, cursor = [], ''
    while True:
        params = {'category': 'linear', 'limit': 1000}
        if cursor:
            params['cursor'] = cursor
        d = core.bybit('/v5/market/instruments-info', params)['result']
        for x in d.get('list', []):
            if (x.get('status') == 'Trading'
                    and x.get('quoteCoin') == 'USDT'
                    and x.get('contractType') == 'LinearPerpetual'):
                out.append(x['symbol'])
        cursor = d.get('nextPageCursor', '')
        if not cursor:
            break
    return sorted(set(out))


def active_symbols(provider):
    if provider == 'Bitget':
        return active_bitget_symbols()
    if provider == 'Binance':
        return active_binance_symbols()
    return active_bybit_symbols()


def write_watchlist(results, ts):
    WATCHLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for rank, x in enumerate(results, 1):
        if x['direction'] in ('LONG', 'SHORT') and x['score'] >= 70:
            selection = 'TARGET'
        elif x['direction'] in ('LONG', 'SHORT') and x['score'] >= 55:
            selection = 'WATCH'
        elif x['score'] >= 50:
            selection = 'MONITOR'
        else:
            selection = 'SKIP'
        rows.append({
            'timestamp': ts, 'rank': rank, 'symbol': x['symbol'],
            'score': round(x['score'], 1), 'direction': x['direction'], 'signal': x['signal'],
            'location': round(x['location'], 3), 'exhaustion': round(x['exhaustion'], 3),
            'flow': round(x['flow'], 3), 'reclaim': round(x['reclaim'], 3),
            'expansion': round(x['expansion'], 3), 'price': x['price'],
            'range_pos': x['range_pos'], 'atr_pct': x['atr_pct'],
            'volume_ratio': x['volume_ratio'], 'taker_ratio': x['taker'],
            'taker_stability': x['taker_stability'], 'taker_fills': x['taker_fills'],
            'book_ratio': x['book'], 'funding': x['funding'], '24h_change': x['change'],
            'selection': selection,
        })
    with WATCHLIST_FILE.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=WATCHLIST_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main():
    provider, btc24 = core.discover()
    symbols = active_symbols(provider)
    if not symbols:
        raise RuntimeError('Dynamic futures universe is empty')

    print(f'Universe: {len(symbols)} active {provider} USDT perpetual symbols')
    results, errors = [], []
    with ThreadPoolExecutor(max_workers=min(8, len(symbols))) as executor:
        futures = {executor.submit(core.fetch_symbol, s, provider, btc24): s for s in symbols}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                errors.append((symbol, str(exc)))

    results.sort(key=lambda x: x['score'], reverse=True)
    ts = datetime.now(timezone.utc).isoformat()
    core.append_rows([core.signal_row(x, ts) for x in results])
    write_watchlist(results, ts)

    print(f'Coverage: {len(results)}/{len(symbols)}')
    print('TOP TARGET/WATCH:')
    shown = 0
    for rank, x in enumerate(results, 1):
        if x['direction'] not in ('LONG', 'SHORT') or x['score'] < 50:
            continue
        print(
            f"{rank}. {x['symbol']} | {x['score']:.1f} | {x['signal']} | "
            f"Loc {x['location']:.2f} Exh {x['exhaustion']:.2f} "
            f"Flow {x['flow']:.2f} Reclaim {x['reclaim']:.2f} Expand {x['expansion']:.2f}"
        )
        shown += 1
        if shown >= 25:
            break

    if errors:
        print(f'Symbol errors: {len(errors)}')
        for symbol, error in errors[:20]:
            print(f' - {symbol}: {error}')

    print(f'Watchlist saved: {WATCHLIST_FILE}')
    print(f'Forward-test outcomes updated: {core.evaluate_forward()}')
    print(core.validation_stats())


if __name__ == '__main__':
    main()

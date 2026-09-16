"""Send newly confirmed scanner actions to Telegram without duplicate alerts."""
import csv
import scanner_v2 as core
from pathlib import Path
from telegram_notifier import format_action, send_message

ACTIONS=Path('data/actionable_signals.csv')
STATE=Path('data/telegram_sent_actions.csv')
STATE_FIELDS=['id']


def _live_price(row):
    provider=row.get('provider','')
    symbol=row.get('symbol','')
    if not provider or not symbol:
        return None
    try:
        if provider=='Binance':
            return float(core.binance('/fapi/v1/ticker/price',{'symbol':symbol})['price'])
        if provider=='Bybit':
            data=core.bybit('/v5/market/tickers',{'category':'linear','symbol':symbol})
            return float(data['result']['list'][0]['lastPrice'])
        if provider=='Bitget':
            data=core.bitget('/api/v2/mix/market/ticker',{'symbol':symbol,'productType':'USDT-FUTURES'})
            return float(data['data'][0]['lastPr'])
    except (KeyError,IndexError,TypeError,ValueError,RuntimeError):
        return None
    return None


def _still_actionable(row, live_price):
    """Allow Telegram only while price is between fixed entry and target/stop."""
    if live_price is None:
        return False
    try:
        p=float(live_price);entry=float(row['entry']);stop=float(row['stop']);target=float(row['target'])
    except (KeyError,TypeError,ValueError):
        return False
    if row.get('direction')=='LONG':
        return p>=entry and p<target and p>stop
    if row.get('direction')=='SHORT':
        return p<=entry and p>target and p<stop
    return False


def main():
    if not ACTIONS.exists():
        print('TELEGRAM: no actionable signal file')
        return 0
    with ACTIONS.open(newline='',encoding='utf-8') as f:
        actions=list(csv.DictReader(f))
    STATE.parent.mkdir(parents=True,exist_ok=True)
    sent=set()
    if STATE.exists():
        with STATE.open(newline='',encoding='utf-8') as f:
            sent={r['id'] for r in csv.DictReader(f) if r.get('id')}
    pending=[r for r in actions if r.get('id') and r['id'] not in sent]
    token = __import__('os').environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = __import__('os').environ.get('TELEGRAM_CHAT_ID')
    if not pending:
        print('TELEGRAM: no new confirmed actions')
    elif not token or not chat_id:
        print(f'TELEGRAM: {len(pending)} confirmed action(s) pending; credentials not configured')
        return 0
    else:
        for row in pending:
            live=_live_price(row)
            if not _still_actionable(row,live):
                print(f"TELEGRAM SKIP: {row.get('symbol','?')} {row.get('direction','?')} no longer inside live execution window (price={live})")
                continue
            ok, detail=send_message(format_action(row), token, chat_id)
            if not ok:
                raise RuntimeError(f"Telegram send failed for {row['id']}: {detail}")
            sent.add(row['id'])
            print(f"TELEGRAM SENT: {row['symbol']} {row['direction']} entry={row['entry']} live={live}")
    with STATE.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=STATE_FIELDS); w.writeheader()
        for value in sorted(sent): w.writerow({'id':value})
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

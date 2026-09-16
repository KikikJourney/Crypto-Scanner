"""Send newly confirmed scanner actions to Telegram without duplicate alerts."""
import csv
from pathlib import Path
from telegram_notifier import format_action, send_message

ACTIONS=Path('data/actionable_signals.csv')
STATE=Path('data/telegram_sent_actions.csv')
STATE_FIELDS=['id']


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
            ok, detail=send_message(format_action(row), token, chat_id)
            if not ok:
                raise RuntimeError(f"Telegram send failed for {row['id']}: {detail}")
            sent.add(row['id'])
            print(f"TELEGRAM SENT: {row['symbol']} {row['direction']} entry={row['entry']}")
    with STATE.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=STATE_FIELDS); w.writeheader()
        for value in sorted(sent): w.writerow({'id':value})
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

"""Persistent forward-test for executable scalping actions using future 5m OHLC.

Each scan archives executable actions and a rolling set of closed 5m candles.
Outcomes use first-touch logic: SL/TP is resolved from candle high/low; if both
levels occur in one candle, the result is AMBIGUOUS rather than guessed.
"""
import csv
from datetime import datetime, timedelta
from pathlib import Path

ACTION_FILE = Path('data/actionable_signals.csv')
ACTION_HISTORY_FILE = Path('data/scalping_action_history.csv')
MARKET_FILE = Path('data/scalping_market_5m.csv')
OUTPUT_FILE = Path('data/scalping_forward_test.csv')
HORIZONS_MINUTES = (15, 30, 60, 120)
FIELDS = [
    'id','timestamp','symbol','provider','direction','score','v2_score','confidence',
    'location_15m','reversal_5m','exhaustion_15m','base_15m','structure_shift_5m',
    'reversal_trigger_5m','early_reversal_score','entry','stop','target','risk_pct',
    'reward_r','h15','h30','h60','h120',
    'first_touch','first_touch_timestamp','resolved_horizon','outcome_r','mfe_pct','mae_pct',
]
ACTION_HISTORY_FIELDS = [
    'id','timestamp','symbol','provider','direction','score','v2_score','confidence',
    'location_15m','reversal_5m','exhaustion_15m','base_15m','structure_shift_5m',
    'reversal_trigger_5m','early_reversal_score','entry','stop','target','risk_pct','reward_r',
]
MARKET_FIELDS = ['id','timestamp','close_timestamp','symbol','provider','open','high','low','close']
FORWARD_ACTION_FIELDS = FIELDS


def _ts(value):
    return datetime.fromisoformat(str(value).replace('Z', '+00:00'))


def _f(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _load(path, fields=None):
    if not path.exists():
        return []
    with path.open(newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def _migrate_history():
    ACTION_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not ACTION_HISTORY_FILE.exists():
        _write_rows(ACTION_HISTORY_FILE, ACTION_HISTORY_FIELDS, [])
    rows = _load(ACTION_HISTORY_FILE)
    normalized = [{k: r.get(k, '') for k in ACTION_HISTORY_FIELDS} for r in rows]
    _write_rows(ACTION_HISTORY_FILE, ACTION_HISTORY_FIELDS, normalized)


def _write_rows(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def archive_actions(actions=None):
    """Append newly generated executable actions to an immutable action history."""
    _migrate_history()
    actions = _load(ACTION_FILE) if actions is None else actions
    existing = {r.get('id') for r in _load(ACTION_HISTORY_FILE)}
    fresh = []
    for action in actions:
        if action.get('direction') not in {'LONG', 'SHORT'}:
            continue
        if action.get('id') in existing:
            continue
        fresh.append({k: action.get(k, '') for k in ACTION_HISTORY_FIELDS})
    if fresh:
        with ACTION_HISTORY_FILE.open('a', newline='', encoding='utf-8') as f:
            csv.DictWriter(f, fieldnames=ACTION_HISTORY_FIELDS).writerows(fresh)
    return len(fresh)


def archive_market_candles(results, per_symbol=8):
    """Archive recent closed 5m OHLC; keep enough overlap for 15m scheduled scans."""
    MARKET_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not MARKET_FILE.exists():
        _write_rows(MARKET_FILE, MARKET_FIELDS, [])
    existing_rows = _load(MARKET_FILE)
    migrated = []
    for r in existing_rows:
        if not r.get('close_timestamp') and r.get('timestamp'):
            try:
                r['close_timestamp'] = (_ts(r['timestamp']) + timedelta(minutes=5)).isoformat()
            except ValueError:
                r['close_timestamp'] = ''
        migrated.append({k: r.get(k, '') for k in MARKET_FIELDS})
    if migrated:
        _write_rows(MARKET_FILE, MARKET_FIELDS, migrated)
    existing = {r.get('id') for r in migrated}
    fresh = []
    for result in results:
        rows = result.get('scalping_rows_5m') or []
        for candle in rows[-per_symbol:]:
            if len(candle) < 6:
                continue
            ts = str(candle[0])
            try:
                ts_iso = _ts(ts).isoformat()
            except ValueError:
                try:
                    ts_iso = datetime.fromtimestamp(float(candle[0]) / 1000, tz=_ts(result['scan_timestamp']).tzinfo).isoformat()
                except (TypeError, ValueError):
                    continue
            symbol = result.get('symbol', '')
            provider = result.get('provider', '')
            row_id = f'{provider}_{symbol}_{ts_iso}'
            if row_id in existing:
                continue
            close_ts = (_ts(ts_iso) + timedelta(minutes=5)).isoformat()
            fresh.append({
                'id': row_id,
                'timestamp': ts_iso,
                'close_timestamp': close_ts,
                'symbol': symbol,
                'provider': provider,
                'open': candle[1],
                'high': candle[2],
                'low': candle[3],
                'close': candle[4],
            })
            existing.add(row_id)
    if fresh:
        with MARKET_FILE.open('a', newline='', encoding='utf-8') as f:
            csv.DictWriter(f, fieldnames=MARKET_FIELDS).writerows(fresh)
    return len(fresh)


def _first_touch(direction, high, low, stop, target):
    high, low, stop, target = map(_f, (high, low, stop, target))
    if None in (high, low, stop, target):
        return None
    favorable = high >= target if direction == 'LONG' else low <= target
    adverse = low <= stop if direction == 'LONG' else high >= stop
    if favorable and adverse:
        return 'AMBIGUOUS'
    if favorable:
        return 'EXPANSION'
    if adverse:
        return 'FAIL'
    return None


def _candle_close_timestamp(row):
    value = row.get('close_timestamp')
    if value:
        return _ts(value)
    return _ts(row['timestamp']) + timedelta(minutes=5)


def _market_slice(action, market_rows, horizon):
    ts = _ts(action['timestamp'])
    deadline = ts + timedelta(minutes=horizon)
    return [
        row for row in market_rows
        if row.get('provider') == action.get('provider')
        and row.get('symbol') == action.get('symbol')
        and ts < _candle_close_timestamp(row) <= deadline
    ]


def _metrics(direction, entry, candles):
    entry = _f(entry)
    if entry is None or not candles:
        return '', ''
    highs = [_f(r.get('high')) for r in candles]
    lows = [_f(r.get('low')) for r in candles]
    highs = [x for x in highs if x is not None]
    lows = [x for x in lows if x is not None]
    if not highs or not lows:
        return '', ''
    if direction == 'LONG':
        mfe = (max(highs) - entry) / entry * 100
        mae = (entry - min(lows)) / entry * 100
    else:
        mfe = (entry - min(lows)) / entry * 100
        mae = (max(highs) - entry) / entry * 100
    return round(mfe, 6), round(mae, 6)


def evaluate(actions=None, market_rows=None):
    """Resolve persistent actions from future closed 5m OHLC candles."""
    _migrate_history()
    actions = _load(ACTION_HISTORY_FILE) if actions is None else actions
    market_rows = _load(MARKET_FILE) if market_rows is None else market_rows
    market_rows = sorted(market_rows, key=lambda r: _ts(r['timestamp']))
    output = []

    for action in actions:
        if action.get('direction') not in {'LONG', 'SHORT'}:
            continue
        row = {k: action.get(k, '') for k in FIELDS}
        row['resolved_horizon'] = ''
        row['outcome_r'] = ''
        first_touch = None
        first_touch_ts = ''
        all_future = [
            r for r in market_rows
            if r.get('provider') == action.get('provider')
            and r.get('symbol') == action.get('symbol')
            and _ts(r['timestamp']) > _ts(action['timestamp'])
        ]
        for horizon in HORIZONS_MINUTES:
            key = f'h{horizon}'
            candles = _market_slice(action, market_rows, horizon)
            if candles:
                mfe, mae = _metrics(action['direction'], action.get('entry'), candles)
                if mfe != '':
                    row['mfe_pct'], row['mae_pct'] = mfe, mae
            if row[key]:
                continue
            for candle in candles:
                outcome = _first_touch(
                    action['direction'], candle.get('high'), candle.get('low'),
                    action.get('stop'), action.get('target')
                )
                if outcome:
                    row[key] = outcome
                    if first_touch is None:
                        first_touch = outcome
                        first_touch_ts = _candle_close_timestamp(candle).isoformat()
                        row['resolved_horizon'] = key
                        row['outcome_r'] = (
                            '2.0' if outcome == 'EXPANSION'
                            else '-1.0' if outcome == 'FAIL'
                            else ''
                        )
                    break
        if first_touch is not None:
            row['first_touch'] = first_touch
            row['first_touch_timestamp'] = first_touch_ts
        output.append(row)

    _write_rows(OUTPUT_FILE, FIELDS, output)
    return output


def summarize(rows=None):
    rows = _load(OUTPUT_FILE) if rows is None else rows
    first_touch = [r.get('first_touch') for r in rows if r.get('first_touch')]
    return {
        'actions': len(rows),
        'resolved': len(first_touch),
        'unresolved': len(rows) - len(first_touch),
        'expansion': first_touch.count('EXPANSION'),
        'fail': first_touch.count('FAIL'),
        'ambiguous': first_touch.count('AMBIGUOUS'),
        'net_r': sum(
            2.0 if x == 'EXPANSION' else -1.0 if x == 'FAIL' else 0.0
            for x in first_touch
        ),
    }


def format_summary(rows=None):
    s = summarize(rows)
    return (
        f"Scalping forward-test: {s['actions']} actions / {s['resolved']} resolved / "
        f"{s['unresolved']} unresolved | EXPANSION={s['expansion']}, "
        f"FAIL={s['fail']}, AMBIGUOUS={s['ambiguous']} | NET_R={s['net_r']:.2f}"
    )

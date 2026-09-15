"""Production Early Reversal V2.1 layer.

This layer is deliberately independent from the V2.0 PRE-EXPANSION gate.
It consumes already-computed side-specific components, adds no API calls,
and never uses future candles/data.
"""

import csv
from datetime import datetime, timezone
from pathlib import Path

from scanner_v2 import clamp

EARLY_FORWARD_FILE = Path('data/early_reversal_forward_test.csv')
HORIZONS = (1, 4, 12, 24)
WEIGHTS = {'location': 30, 'exhaustion': 25, 'flow': 25, 'structure': 20}
MIN_SCORE = 65.0
MIN_LOCATION = 0.65
MIN_EXHAUSTION = 0.50
MIN_FLOW = 0.55
MIN_STRUCTURE = 0.15

CSV_FIELDS = [
    'id','timestamp','symbol','provider','direction','signal','score','location','exhaustion',
    'flow','structure','price','atr_pct','h1','h4','h12','h24'
]


def _f(x, default=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _side_parts(result, side):
    if side == 'LONG':
        return {
            'location': _f(result.get('long_location')),
            'exhaustion': _f(result.get('long_exhaustion')),
            'flow': _f(result.get('long_flow')),
            'structure': _f(result.get('long_reclaim')),
        }
    return {
        'location': _f(result.get('short_location')),
        'exhaustion': _f(result.get('short_exhaustion')),
        'flow': _f(result.get('short_flow')),
        'structure': _f(result.get('short_reject')),
    }


def early_score(parts):
    if any(parts[k] is None for k in WEIGHTS):
        return None
    return round(sum(WEIGHTS[k] * clamp(parts[k]) for k in WEIGHTS), 1)


def blockers(parts):
    out = []
    checks = (
        ('location', MIN_LOCATION),
        ('exhaustion', MIN_EXHAUSTION),
        ('flow', MIN_FLOW),
        ('structure', MIN_STRUCTURE),
    )
    for name, threshold in checks:
        value = parts.get(name)
        if value is None:
            out.append(f'{name} data unavailable')
        elif value < threshold:
            out.append(f'{name} {value:.2f}<{threshold:.2f}')
    return '; '.join(out[:3]) if out else 'none'


def classify_side(parts, side):
    score = early_score(parts)
    if score is None:
        return 'DATA-LIMITED', None, blockers(parts)
    if (
        score >= MIN_SCORE
        and parts['location'] >= MIN_LOCATION
        and parts['exhaustion'] >= MIN_EXHAUSTION
        and parts['flow'] >= MIN_FLOW
        and parts['structure'] >= MIN_STRUCTURE
    ):
        return f'EARLY REVERSAL {side}', score, 'none'
    return f'MONITOR {side}', score, blockers(parts)


def classify(result):
    """Return the strongest early side without modifying V2.0 signal semantics."""
    long_parts = _side_parts(result, 'LONG')
    short_parts = _side_parts(result, 'SHORT')
    long_status, long_score, long_blocker = classify_side(long_parts, 'LONG')
    short_status, short_score, short_blocker = classify_side(short_parts, 'SHORT')

    candidates = []
    if long_status == 'EARLY REVERSAL LONG':
        candidates.append(('LONG', long_score))
    if short_status == 'EARLY REVERSAL SHORT':
        candidates.append(('SHORT', short_score))
    if candidates:
        side, score = max(candidates, key=lambda x: (x[1], x[0] == 'LONG'))
        parts = long_parts if side == 'LONG' else short_parts
        return {
            'status': f'EARLY REVERSAL {side}', 'direction': side, 'score': score,
            'location': parts['location'], 'exhaustion': parts['exhaustion'],
            'flow': parts['flow'], 'structure': parts['structure'], 'blocker': 'none',
            'long_score': long_score, 'short_score': short_score,
            'long_blocker': long_blocker, 'short_blocker': short_blocker,
        }

    # If neither side qualifies, expose the stronger side as MONITOR/DATA-LIMITED.
    usable = [(s, v) for s, v in (('LONG', long_score), ('SHORT', short_score)) if v is not None]
    side, score = max(usable, key=lambda x: (x[1], x[0] == 'LONG')) if usable else ('NONE', None)
    parts = long_parts if side == 'LONG' else short_parts if side == 'SHORT' else {k: None for k in WEIGHTS}
    blocker = long_blocker if side == 'LONG' else short_blocker if side == 'SHORT' else 'data-limited: no side data'
    return {
        'status': f'MONITOR {side}' if side != 'NONE' else 'DATA-LIMITED', 'direction': side,
        'score': score, 'location': parts['location'], 'exhaustion': parts['exhaustion'],
        'flow': parts['flow'], 'structure': parts['structure'], 'blocker': blocker,
        'long_score': long_score, 'short_score': short_score,
        'long_blocker': long_blocker, 'short_blocker': short_blocker,
    }


def signal_row(result, timestamp):
    d = classify(result)
    signal = d['status'] if d['status'].startswith('EARLY REVERSAL') else ''
    return {
        'id': f'{timestamp}_{result["symbol"]}_EARLY', 'timestamp': timestamp,
        'symbol': result['symbol'], 'provider': result['provider'], 'direction': d['direction'],
        'signal': signal, 'score': d['score'] if d['score'] is not None else '',
        'location': d['location'] if d['location'] is not None else '',
        'exhaustion': d['exhaustion'] if d['exhaustion'] is not None else '',
        'flow': d['flow'] if d['flow'] is not None else '',
        'structure': d['structure'] if d['structure'] is not None else '',
        'price': result['price'], 'atr_pct': result['atr_pct'],
        'h1': '', 'h4': '', 'h12': '', 'h24': '',
    }


def migrate_csv():
    EARLY_FORWARD_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not EARLY_FORWARD_FILE.exists():
        with EARLY_FORWARD_FILE.open('w', newline='', encoding='utf-8') as f:
            csv.DictWriter(f, fieldnames=CSV_FIELDS).writeheader()
        return
    with EARLY_FORWARD_FILE.open(newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    clean = []
    for row in rows:
        clean.append({k: row.get(k, '') for k in CSV_FIELDS})
    with EARLY_FORWARD_FILE.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS); w.writeheader(); w.writerows(clean)


def append_rows(rows):
    migrate_csv()
    existing = set()
    with EARLY_FORWARD_FILE.open(newline='', encoding='utf-8') as f:
        existing = {r['id'] for r in csv.DictReader(f)}
    fresh = [r for r in rows if r['signal'] and r['id'] not in existing]
    if not fresh:
        return 0
    with EARLY_FORWARD_FILE.open('a', newline='', encoding='utf-8') as f:
        csv.DictWriter(f, fieldnames=CSV_FIELDS).writerows(fresh)
    return len(fresh)


def _parse_ts(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def _outcome(direction, entry, future, atr_pct):
    if atr_pct is None or atr_pct <= 0:
        return None
    move = (future - entry) / entry * 100
    favorable = move >= 2 * atr_pct if direction == 'LONG' else move <= -2 * atr_pct
    adverse = move <= -atr_pct if direction == 'LONG' else move >= atr_pct
    if favorable and adverse:
        return 'AMBIGUOUS'
    if favorable:
        return 'EXPANSION'
    if adverse:
        return 'FAIL'
    return None


def evaluate_forward(snapshot_rows):
    """Evaluate only future snapshots; no look-ahead and no current-row reuse."""
    migrate_csv()
    with EARLY_FORWARD_FILE.open(newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    snapshots = {}
    for row in snapshot_rows:
        try:
            snapshots.setdefault(row['symbol'], []).append(row)
        except KeyError:
            continue
    for values in snapshots.values():
        values.sort(key=lambda r: _parse_ts(r['timestamp']))

    updated = 0
    for row in rows:
        if all(row.get(f'h{h}') for h in HORIZONS):
            continue
        try:
            signal_ts = _parse_ts(row['timestamp']); entry = float(row['price'])
            atr = float(row['atr_pct']); direction = row['direction']; symbol = row['symbol']
        except (TypeError, ValueError):
            continue
        futures = [r for r in snapshots.get(symbol, []) if _parse_ts(r['timestamp']) > signal_ts]
        for h in HORIZONS:
            key = f'h{h}'
            if row[key]:
                continue
            deadline = signal_ts.timestamp() + h * 3600
            outcome = None
            for future in futures:
                if _parse_ts(future['timestamp']).timestamp() > deadline:
                    break
                try: price = float(future['price'])
                except (TypeError, ValueError): continue
                outcome = _outcome(direction, entry, price, atr)
                if outcome: break
            if outcome:
                row[key] = outcome; updated += 1
    with EARLY_FORWARD_FILE.open('w', newline='', encoding='utf-8') as f:
        csv.DictWriter(f, fieldnames=CSV_FIELDS).writeheader(); csv.DictWriter(f, fieldnames=CSV_FIELDS).writerows(rows)
    return updated


def stats():
    migrate_csv()
    with EARLY_FORWARD_FILE.open(newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    signals = len(rows)
    outcomes = [r[h] for r in rows for h in ('h1','h4','h12','h24') if r[h]]
    return f'Early forward-test: {signals} signals / {len(outcomes)} resolved horizon outcomes'

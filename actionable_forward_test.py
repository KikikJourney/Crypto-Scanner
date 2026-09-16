"""Forward-test only confirmed fixed-entry actions.

This module deliberately measures the trade the Telegram channel would receive:
trigger-confirmed entry, fixed stop, fixed target, and future-only outcomes.
It does not count an extreme signal as a trade.
"""
import csv
from datetime import datetime, timedelta
from pathlib import Path

EXTREME_FILE = Path('data/extreme_reversal_forward_test.csv')
SNAPSHOT_FILE = Path('data/extreme_market_snapshots.csv')
ACTION_FILE = Path('data/actionable_forward_test.csv')
HORIZONS = (1, 4, 12, 24)
EVENT_GAP_HOURS = 2
FIELDS = [
    'id', 'timestamp', 'symbol', 'provider', 'direction', 'extreme_event_id',
    'entry', 'stop', 'target', 'risk_pct', 'reward_r', 'source_extreme_score',
    'event_id', 'event_role', 'h1', 'h4', 'h12', 'h24'
]


def _ts(value):
    return datetime.fromisoformat(str(value).replace('Z', '+00:00'))


def _f(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _outcome(direction, price, stop, target):
    price, stop, target = _f(price), _f(stop), _f(target)
    if None in (price, stop, target):
        return None
    if direction == 'LONG':
        favorable = price >= target
        adverse = price <= stop
    else:
        favorable = price <= target
        adverse = price >= stop
    if favorable and adverse:
        return 'AMBIGUOUS'
    if favorable:
        return 'EXPANSION'
    if adverse:
        return 'FAIL'
    return None


def _load(path):
    if not path.exists():
        return []
    with path.open(newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def _write(rows):
    ACTION_FILE.parent.mkdir(parents=True, exist_ok=True)
    with ACTION_FILE.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def _assign_events(rows):
    ordered = sorted(rows, key=lambda r: (_ts(r['timestamp']), r.get('symbol', ''), r.get('direction', '')))
    last = {}
    for row in ordered:
        key = (row.get('symbol', ''), row.get('direction', ''))
        current = _ts(row['timestamp'])
        previous = last.get(key)
        if previous is None or current - previous[0] > timedelta(hours=EVENT_GAP_HOURS):
            event_id = f"{row['symbol']}_{row['direction']}_{row['timestamp']}"
            row['event_role'] = 'PRIMARY'
        else:
            event_id = previous[1]
            row['event_role'] = 'DUPLICATE'
        row['event_id'] = event_id
        last[key] = (current, event_id)
    return rows


def build_confirmed_actions(extreme_rows, snapshots):
    """Convert extreme observations into the first confirmed fixed-entry action."""
    extremes = _assign_events([dict(r) for r in extreme_rows if r.get('event_role') == 'PRIMARY'])
    by_symbol = {}
    for snap in snapshots:
        by_symbol.setdefault(snap.get('symbol', ''), []).append(snap)
    for values in by_symbol.values():
        values.sort(key=lambda r: _ts(r['timestamp']))

    actions = []
    seen = set()
    for extreme in extremes:
        direction = extreme.get('direction', '')
        trigger = _f(extreme.get('trigger'))
        stop = _f(extreme.get('action_stop'))
        target = _f(extreme.get('action_target'))
        if direction not in {'LONG', 'SHORT'} or None in (trigger, stop, target):
            continue
        extreme_ts = _ts(extreme['timestamp'])
        candidates = by_symbol.get(extreme.get('symbol', ''), [])
        confirmed = None
        for snap in candidates:
            snap_ts = _ts(snap['timestamp'])
            if snap_ts < extreme_ts:
                continue
            price = _f(snap.get('price'))
            if price is None:
                continue
            if (direction == 'LONG' and price >= trigger) or (direction == 'SHORT' and price <= trigger):
                confirmed = snap
                break
        if confirmed is None:
            continue
        action_ts = _ts(confirmed['timestamp'])
        key = (extreme.get('symbol', ''), direction, extreme.get('event_id', ''))
        if key in seen:
            continue
        seen.add(key)
        actions.append({
            'id': f"{confirmed['timestamp']}_{extreme['symbol']}_{direction}_{trigger}",
            'timestamp': confirmed['timestamp'],
            'symbol': extreme['symbol'],
            'provider': extreme.get('provider', ''),
            'direction': direction,
            'extreme_event_id': extreme.get('event_id', ''),
            'entry': trigger,
            'stop': stop,
            'target': target,
            'risk_pct': extreme.get('action_risk_pct', ''),
            'reward_r': extreme.get('action_reward_r', '2.0'),
            'source_extreme_score': extreme.get('score', ''),
            'event_id': '',
            'event_role': '',
            'h1': '', 'h4': '', 'h12': '', 'h24': '',
        })
    return actions


def evaluate(rows=None, snapshots=None):
    extremes = _load(EXTREME_FILE) if rows is None else rows
    snapshots = _load(SNAPSHOT_FILE) if snapshots is None else snapshots
    actions = build_confirmed_actions(extremes, snapshots)
    _assign_events(actions)
    # Recompute outcomes from snapshots strictly after confirmed entry.
    by_symbol = {}
    for snap in snapshots:
        by_symbol.setdefault(snap.get('symbol', ''), []).append(snap)
    for values in by_symbol.values():
        values.sort(key=lambda r: _ts(r['timestamp']))
    for action in actions:
        entry_ts = _ts(action['timestamp'])
        futures = [s for s in by_symbol.get(action['symbol'], []) if _ts(s['timestamp']) > entry_ts]
        stop, target = action['stop'], action['target']
        for horizon in HORIZONS:
            deadline = entry_ts + timedelta(hours=horizon)
            key = f'h{horizon}'
            for snap in futures:
                snap_ts = _ts(snap['timestamp'])
                if snap_ts > deadline:
                    break
                outcome = _outcome(action['direction'], snap.get('price'), stop, target)
                if outcome:
                    action[key] = outcome
                    break
    _write(actions)
    return actions


def summarize(rows=None):
    rows = _load(ACTION_FILE) if rows is None else rows
    primary = [r for r in rows if r.get('event_role') == 'PRIMARY']
    resolved = []
    for row in primary:
        values = [row.get(f'h{h}', '') for h in HORIZONS if row.get(f'h{h}', '')]
        if values:
            resolved.append(values[0])
    counts = {v: resolved.count(v) for v in ('EXPANSION', 'FAIL', 'AMBIGUOUS')}
    return {
        'raw_actions': len(rows),
        'independent_events': len({r.get('event_id') for r in primary if r.get('event_id')}),
        'resolved_events': len(resolved),
        'unresolved_events': len(primary) - len(resolved),
        **{f'event_{k.lower()}': v for k, v in counts.items()},
    }


def format_summary(rows=None):
    s = summarize(rows)
    return (
        f"Actionable forward-test: {s['raw_actions']} confirmed actions / "
        f"{s['independent_events']} independent events / {s['resolved_events']} resolved events / "
        f"{s['unresolved_events']} unresolved events | "
        f"event outcome: EXPANSION={s['event_expansion']}, FAIL={s['event_fail']}, "
        f"AMBIGUOUS={s['event_ambiguous']}"
    )

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
MAX_TRIGGER_GAP_ATR = 1.25
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


def _stale_gap_atr(direction, price, trigger, atr_pct):
    price, trigger, atr_pct = _f(price), _f(trigger), _f(atr_pct)
    if None in (price, trigger, atr_pct) or trigger <= 0 or atr_pct <= 0:
        return None
    gap_pct = ((trigger - price) / trigger * 100) if direction == 'LONG' else ((price - trigger) / trigger * 100)
    return gap_pct / atr_pct


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
    ordered = sorted(rows, key=lambda r: (_ts(r['timestamp']), r.get('provider', ''), r.get('symbol', ''), r.get('direction', '')))
    last = {}
    for row in ordered:
        key = (row.get('provider', ''), row.get('symbol', ''), row.get('direction', ''))
        current = _ts(row['timestamp'])
        previous = last.get(key)
        if previous is None or current - previous[0] > timedelta(hours=EVENT_GAP_HOURS):
            event_id = f"{row.get('provider', '')}_{row['symbol']}_{row['direction']}_{row['timestamp']}"
            row['event_role'] = 'PRIMARY'
        else:
            event_id = previous[1]
            row['event_role'] = 'DUPLICATE'
        row['event_id'] = event_id
        last[key] = (current, event_id)
    return rows


def build_confirmed_actions(extreme_rows, snapshots):
    """Convert extreme observations into the first confirmed fixed-entry action.

    Confirmation is provider-specific and must happen before the setup becomes
    more than MAX_TRIGGER_GAP_ATR away from its trigger. A trigger hit after a
    stale excursion is ignored; the setup must qualify as a new extreme event.
    """
    extremes = _assign_events([dict(r) for r in extreme_rows if r.get('event_role') == 'PRIMARY'])
    by_provider_symbol = {}
    for snap in snapshots:
        by_provider_symbol.setdefault((snap.get('provider', ''), snap.get('symbol', '')), []).append(snap)
    for values in by_provider_symbol.values():
        values.sort(key=lambda r: _ts(r['timestamp']))

    actions = []
    seen = set()
    for extreme in extremes:
        direction = extreme.get('direction', '')
        trigger = _f(extreme.get('trigger'))
        stop = _f(extreme.get('action_stop'))
        target = _f(extreme.get('action_target'))
        atr_pct = _f(extreme.get('atr_pct'))
        if direction not in {'LONG', 'SHORT'} or None in (trigger, stop, target, atr_pct) or atr_pct <= 0:
            continue
        extreme_ts = _ts(extreme['timestamp'])
        candidates = by_provider_symbol.get((extreme.get('provider', ''), extreme.get('symbol', '')), [])
        confirmed = None
        stale = False
        for snap in candidates:
            snap_ts = _ts(snap['timestamp'])
            if snap_ts < extreme_ts:
                continue
            price = _f(snap.get('price'))
            if price is None:
                continue
            if (direction == 'LONG' and price >= trigger) or (direction == 'SHORT' and price <= trigger):
                if not stale:
                    confirmed = snap
                break
            gap_atr = _stale_gap_atr(direction, price, trigger, atr_pct)
            if gap_atr is not None and gap_atr > MAX_TRIGGER_GAP_ATR:
                stale = True
                break
        if confirmed is None:
            continue
        key = (extreme.get('provider', ''), extreme.get('symbol', ''), direction, extreme.get('event_id', ''))
        if key in seen:
            continue
        seen.add(key)
        actions.append({
            'id': f"{extreme.get('provider', '')}_{confirmed['timestamp']}_{extreme['symbol']}_{direction}_{trigger}",
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

    # Contract: every confirmed action returned by this function is already
    # event-labelled. Callers (tests, summaries, or evaluate) must not need a
    # second normalization pass merely to obtain event identity.
    return _assign_events(actions)


def evaluate(rows=None, snapshots=None):
    extremes = _load(EXTREME_FILE) if rows is None else rows
    snapshots = _load(SNAPSHOT_FILE) if snapshots is None else snapshots
    actions = build_confirmed_actions(extremes, snapshots)
    # Recompute outcomes from snapshots strictly after confirmed entry and from
    # the same provider as the confirmed action.
    by_provider_symbol = {}
    for snap in snapshots:
        by_provider_symbol.setdefault((snap.get('provider', ''), snap.get('symbol', '')), []).append(snap)
    for values in by_provider_symbol.values():
        values.sort(key=lambda r: _ts(r['timestamp']))
    for action in actions:
        entry_ts = _ts(action['timestamp'])
        futures = [s for s in by_provider_symbol.get((action.get('provider', ''), action['symbol']), []) if _ts(s['timestamp']) > entry_ts]
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

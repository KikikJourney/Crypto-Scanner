"""Forward-test for the 15m-30m scalping execution layer.

The existing V2.2 forward-test remains untouched for historical comparability.
This dataset measures only confirmed scalping actions and uses future-only
snapshots at 15m, 30m, 60m and 120m horizons.
"""
import csv
from datetime import datetime, timedelta
from pathlib import Path

ACTION_FILE = Path('data/actionable_signals.csv')
SNAPSHOT_FILE = Path('data/extreme_market_snapshots.csv')
OUTPUT_FILE = Path('data/scalping_forward_test.csv')
HORIZONS_MINUTES = (15, 30, 60, 120)
FIELDS = ['id','timestamp','symbol','provider','direction','score','v2_score','confidence','location_15m','reversal_5m','entry','stop','target','risk_pct','reward_r','h15','h30','h60','h120']


def _ts(value): return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
def _f(value):
    try: return float(value)
    except (TypeError, ValueError): return None


def _outcome(direction, price, stop, target):
    price, stop, target = _f(price), _f(stop), _f(target)
    if None in (price, stop, target): return None
    favorable = price >= target if direction == 'LONG' else price <= target
    adverse = price <= stop if direction == 'LONG' else price >= stop
    if favorable and adverse: return 'AMBIGUOUS'
    if favorable: return 'EXPANSION'
    if adverse: return 'FAIL'
    return None


def _load(path):
    if not path.exists(): return []
    with path.open(newline='', encoding='utf-8') as f: return list(csv.DictReader(f))


def evaluate(actions=None, snapshots=None):
    actions = _load(ACTION_FILE) if actions is None else actions
    snapshots = _load(SNAPSHOT_FILE) if snapshots is None else snapshots
    by_key = {}
    for snap in snapshots:
        by_key.setdefault((snap.get('provider',''), snap.get('symbol','')), []).append(snap)
    for values in by_key.values(): values.sort(key=lambda r: _ts(r['timestamp']))

    output = []
    for action in actions:
        if action.get('direction') not in {'LONG','SHORT'}: continue
        if not action.get('confirmed') == 'True' and action.get('status') not in {'ACTION LONG','ACTION SHORT'}:
            # Legacy actionable_signals rows have no confirmation/status columns;
            # they are accepted because the runner writes only confirmed actions.
            if not action.get('trigger'): continue
        entry_ts = _ts(action['timestamp'])
        row = {k: action.get(k,'') for k in FIELDS}
        futures = [s for s in by_key.get((action.get('provider',''), action.get('symbol','')), []) if _ts(s['timestamp']) > entry_ts]
        for horizon in HORIZONS_MINUTES:
            deadline = entry_ts + timedelta(minutes=horizon)
            for snap in futures:
                if _ts(snap['timestamp']) > deadline: break
                outcome = _outcome(action['direction'], snap.get('price'), action.get('stop'), action.get('target'))
                if outcome:
                    row[f'h{horizon}'] = outcome
                    break
        output.append(row)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_FILE.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS); writer.writeheader(); writer.writerows(output)
    return output


def summarize(rows=None):
    rows = _load(OUTPUT_FILE) if rows is None else rows
    resolved = []
    for row in rows:
        outcome = next((row.get(f'h{h}') for h in HORIZONS_MINUTES if row.get(f'h{h}')), None)
        if outcome: resolved.append(outcome)
    return {
        'actions': len(rows), 'resolved': len(resolved), 'unresolved': len(rows)-len(resolved),
        'expansion': resolved.count('EXPANSION'), 'fail': resolved.count('FAIL'),
        'ambiguous': resolved.count('AMBIGUOUS')
    }


def format_summary(rows=None):
    s = summarize(rows)
    return (f"Scalping forward-test: {s['actions']} actions / {s['resolved']} resolved / "
            f"{s['unresolved']} unresolved | EXPANSION={s['expansion']}, "
            f"FAIL={s['fail']}, AMBIGUOUS={s['ambiguous']}")

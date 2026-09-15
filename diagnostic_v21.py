"""V2.1 diagnostic layer: explain proximity to a reversal signal without changing entry rules."""

COMPONENTS = ('location', 'exhaustion', 'flow', 'reclaim', 'expansion')


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _derived_parts(x, side):
    """Use exact side fields when available; otherwise derive only exact exposed inputs.

    Missing reclaim/exhaustion/expansion are reported as data-limited rather than guessed.
    """
    prefix = 'long_' if side == 'LONG' else 'short_'
    parts = {name: _f(x.get(prefix + ('reject' if name == 'reclaim' and side == 'SHORT' else name))) for name in COMPONENTS}

    # range_pos is the same input used by scanner_v2's location formulas.
    pos = _f(x.get('range_pos'))
    if parts['location'] is None and pos is not None:
        parts['location'] = max(0.0, min(1.0, (0.38 - pos) / 0.38)) if side == 'LONG' else max(0.0, min(1.0, (pos - 0.62) / 0.38))

    # taker aggregate is the same input used by scanner_v2's taker_flow().
    agg = _f(x.get('taker'))
    if parts['flow'] is None and agg is not None and agg > 0:
        import math
        flow = max(0.0, min(1.0, 0.5 + math.log(agg) / math.log(4) * 0.5))
        parts['flow'] = flow if side == 'LONG' else 1.0 - flow

    return parts


def _blockers(parts, side):
    missing = []
    unknown = []
    if parts['location'] is None:
        unknown.append('location data unavailable')
    elif parts['location'] < 0.60:
        missing.append(f'location {parts["location"]:.2f}<0.60')

    if parts['flow'] is None:
        unknown.append('flow data unavailable')
    elif parts['flow'] < 0.55:
        missing.append(f'flow {parts["flow"]:.2f}<0.55')

    if parts['reclaim'] is None:
        unknown.append('reclaim/rejection data unavailable')
    elif parts['reclaim'] < 0.25:
        label = 'reclaim' if side == 'LONG' else 'rejection'
        missing.append(f'{label} {parts["reclaim"]:.2f}<0.25')

    if parts['exhaustion'] is None:
        unknown.append('exhaustion data unavailable')
    elif parts['exhaustion'] < 0.50:
        missing.append(f'exhaustion {parts["exhaustion"]:.2f}<0.50')

    if parts['expansion'] is None:
        unknown.append('expansion data unavailable')
    elif parts['expansion'] < 0.40:
        missing.append(f'expansion {parts["expansion"]:.2f}<0.40')

    if missing:
        return '; '.join(missing[:3])
    if unknown:
        return 'data-limited: ' + '; '.join(unknown[:2])
    return 'none'


def diagnostic_status(x):
    ls = _f(x.get('long_score')) or 0.0
    ss = _f(x.get('short_score')) or 0.0
    side = 'LONG' if ls >= ss else 'SHORT'
    score = max(ls, ss)
    gap_to_signal = round(max(0.0, 70.0 - score), 1)

    long_blocker = _blockers(_derived_parts(x, 'LONG'), 'LONG')
    short_blocker = _blockers(_derived_parts(x, 'SHORT'), 'SHORT')
    blocker = long_blocker if side == 'LONG' else short_blocker

    if x.get('direction') in ('LONG', 'SHORT'):
        status = f'PRE-EXPANSION {x["direction"]}' if score >= 70 else f'NEAR {x["direction"]}'
        blocker = long_blocker if x['direction'] == 'LONG' else short_blocker
    elif score >= 60:
        status = f'NEAR {side}'
    elif score >= 50:
        status = f'MONITOR {side}'
    else:
        status = 'NO EDGE'

    return {
        'status': status,
        'bias': side,
        'long_score': round(ls, 1),
        'short_score': round(ss, 1),
        'score_gap_to_70': gap_to_signal,
        'blocker': blocker,
        'long_blocker': long_blocker,
        'short_blocker': short_blocker,
    }


def _test():
    # Exact side fields: blockers are identified without guessing.
    x = {
        'long_score': 69, 'short_score': 40, 'direction': 'NONE',
        'long_location': .90, 'long_exhaustion': .90, 'long_flow': .70,
        'long_reclaim': .40, 'long_expansion': .30,
        'short_location': .10, 'short_exhaustion': .10, 'short_flow': .30,
        'short_reject': .10, 'short_expansion': .30,
    }
    r = diagnostic_status(x)
    assert r['bias'] == 'LONG' and r['status'] == 'NEAR LONG'
    assert r['blocker'] == 'expansion 0.30<0.40'

    # Exact SHORT fields: verify short-side flow/rejection handling.
    x = {
        'long_score': 48, 'short_score': 66, 'direction': 'NONE',
        'long_location': .10, 'long_exhaustion': .20, 'long_flow': .20,
        'long_reclaim': .10, 'long_expansion': .20,
        'short_location': .80, 'short_exhaustion': .70, 'short_flow': .40,
        'short_reject': .30, 'short_expansion': .20,
    }
    r = diagnostic_status(x)
    assert r['bias'] == 'SHORT' and r['status'] == 'NEAR SHORT'
    assert 'expansion 0.20<0.40' in r['blocker']

    # Current scanner format: location/flow are exact; other components stay data-limited.
    # range_pos=.10 gives LONG location=.737, so there is no known location blocker.
    # This isolates the intended data-limited condition for unavailable components.
    x = {
        'long_score': 65, 'short_score': 61, 'direction': 'NONE',
        'range_pos': .10, 'taker': 1.6, 'volume_ratio': 2.0,
    }
    r = diagnostic_status(x)
    assert r['bias'] == 'LONG' and r['status'] == 'NEAR LONG'
    assert r['blocker'].startswith('data-limited:')
    assert 'exhaustion data unavailable' in r['blocker'] or 'reclaim/rejection data unavailable' in r['blocker']

    # Equal scores are deterministic and prefer LONG.
    x = {'long_score': 60, 'short_score': 60, 'direction': 'NONE'}
    r = diagnostic_status(x)
    assert r['bias'] == 'LONG' and r['status'] == 'NEAR LONG'

    # A valid actual signal remains a signal; diagnostics never lower the gate.
    x = {
        'long_score': 72, 'short_score': 50, 'direction': 'LONG',
        'long_location': .80, 'long_exhaustion': .80, 'long_flow': .70,
        'long_reclaim': .50, 'long_expansion': .70,
        'short_location': .10, 'short_exhaustion': .10, 'short_flow': .30,
        'short_reject': .10, 'short_expansion': .30,
    }
    r = diagnostic_status(x)
    assert r['status'] == 'PRE-EXPANSION LONG' and r['blocker'] == 'none'

    print('V2.1 diagnostic core tests PASSED')


if __name__ == '__main__':
    _test()

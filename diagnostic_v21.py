"""V2.1 diagnostic layer: explain proximity to a reversal signal without changing entry rules."""

COMPONENTS = ('location', 'exhaustion', 'flow', 'reclaim', 'expansion')


def _side_parts(x, side):
    """Read complete side-specific components exposed by scanner_v2."""
    prefix = 'long_' if side == 'LONG' else 'short_'
    out = {}
    for name in COMPONENTS:
        key = prefix + ('reject' if name == 'reclaim' and side == 'SHORT' else name)
        value = x.get(key)
        try:
            out[name] = float(value)
        except (TypeError, ValueError):
            out[name] = None
    return out


def _blockers(parts, side):
    missing = []
    if parts['location'] is not None and parts['location'] < 0.60:
        missing.append(f'location {parts["location"]:.2f}<0.60')
    if parts['flow'] is not None:
        threshold = 0.55 if side == 'LONG' else 0.55
        if parts['flow'] < threshold:
            missing.append(f'flow {parts["flow"]:.2f}<0.55')
    if parts['reclaim'] is not None and parts['reclaim'] < 0.25:
        label = 'reclaim' if side == 'LONG' else 'rejection'
        missing.append(f'{label} {parts["reclaim"]:.2f}<0.25')
    if parts['exhaustion'] is not None and parts['exhaustion'] < 0.50:
        missing.append(f'exhaustion {parts["exhaustion"]:.2f}<0.50')
    if parts['expansion'] is not None and parts['expansion'] < 0.40:
        missing.append(f'expansion {parts["expansion"]:.2f}<0.40')
    return missing


def _format_blockers(x, side):
    parts = _side_parts(x, side)
    if any(v is None for v in parts.values()):
        return f'{side} components incomplete'
    missing = _blockers(parts, side)
    if not missing:
        return 'none'
    # Most useful blockers first: lowest component values among failing gates.
    ranked = sorted(missing, key=lambda s: float(s.split()[1].split('<')[0]))
    return '; '.join(ranked[:3])


def diagnostic_status(x):
    ls = float(x.get('long_score') or 0)
    ss = float(x.get('short_score') or 0)
    side = 'LONG' if ls >= ss else 'SHORT'
    score = max(ls, ss)
    gap_to_signal = round(max(0.0, 70.0 - score), 1)

    long_blocker = _format_blockers(x, 'LONG')
    short_blocker = _format_blockers(x, 'SHORT')

    if x.get('direction') in ('LONG', 'SHORT'):
        blocker = long_blocker if x['direction'] == 'LONG' else short_blocker
    else:
        # Always report the blockers for the currently stronger side, even when
        # the core has not produced an actionable direction yet.
        blocker = long_blocker if side == 'LONG' else short_blocker

    if score >= 70 and x.get('direction') in ('LONG', 'SHORT'):
        status = f'PRE-EXPANSION {x["direction"]}'
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
    # Near LONG: location and expansion are the meaningful blockers.
    x = {
        'long_score': 65, 'short_score': 61, 'direction': 'NONE',
        'long_location': .80, 'long_exhaustion': .70, 'long_flow': .70,
        'long_reclaim': .30, 'long_expansion': .20,
        'short_location': .10, 'short_exhaustion': .20, 'short_flow': .30,
        'short_reject': .10, 'short_expansion': .20,
    }
    r = diagnostic_status(x)
    assert r['bias'] == 'LONG' and r['status'] == 'NEAR LONG' and r['score_gap_to_70'] == 5.0
    assert 'expansion 0.20<0.40' in r['blocker']

    # Near SHORT: verify short flow is interpreted in the correct direction.
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

    # Equal scores must be deterministic and prefer LONG.
    x = {
        'long_score': 60, 'short_score': 60, 'direction': 'NONE',
        'long_location': .70, 'long_exhaustion': .60, 'long_flow': .60,
        'long_reclaim': .20, 'long_expansion': .50,
        'short_location': .70, 'short_exhaustion': .60, 'short_flow': .60,
        'short_reject': .20, 'short_expansion': .50,
    }
    r = diagnostic_status(x)
    assert r['bias'] == 'LONG' and r['status'] == 'NEAR LONG'
    assert 'reclaim 0.20<0.25' in r['blocker']

    # Strong score but blocked by one component: diagnostic must explain it.
    x = {
        'long_score': 69, 'short_score': 40, 'direction': 'NONE',
        'long_location': .90, 'long_exhaustion': .90, 'long_flow': .70,
        'long_reclaim': .40, 'long_expansion': .30,
        'short_location': .10, 'short_exhaustion': .10, 'short_flow': .30,
        'short_reject': .10, 'short_expansion': .30,
    }
    r = diagnostic_status(x)
    assert r['blocker'] == 'expansion 0.30<0.40'

    # Actual signal still reports side-specific blockers and does not alter entry logic.
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

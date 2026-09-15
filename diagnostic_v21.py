def diagnostic_status(x):
    ls = float(x.get('long_score') or 0)
    ss = float(x.get('short_score') or 0)
    side = 'LONG' if ls >= ss else 'SHORT'
    score = max(ls, ss)
    missing = []
    loc = float(x.get('location') or 0)
    exh = float(x.get('exhaustion') or 0)
    flow = float(x.get('flow') or 0)
    rec = float(x.get('reclaim') or 0)
    exp = float(x.get('expansion') or 0)
    if side == 'LONG':
        if loc < 0.60: missing.append(f'location {loc:.2f}<0.60')
        if flow < 0.55: missing.append(f'flow {flow:.2f}<0.55')
        if rec < 0.25: missing.append(f'reclaim {rec:.2f}<0.25')
    else:
        if loc < 0.60: missing.append(f'location {loc:.2f}<0.60')
        if flow > 0.45: missing.append(f'flow {flow:.2f}>0.45')
        if rec < 0.25: missing.append(f'rejection {rec:.2f}<0.25')
    if exh < 0.50: missing.append(f'exhaustion {exh:.2f}<0.50')
    if exp < 0.40: missing.append(f'expansion {exp:.2f}<0.40')
    if score >= 70 and not missing:
        status = f'PRE-EXPANSION {side}'
    elif score >= 60:
        status = f'NEAR {side}'
    elif score >= 50:
        status = f'MONITOR {side}'
    else:
        status = 'NO EDGE'
    return status, side, round(ls, 1), round(ss, 1), '; '.join(missing[:3])


def _test():
    x = {'long_score':65,'short_score':61,'location':.8,'exhaustion':.3,'flow':.7,'reclaim':.5,'expansion':.2}
    r = diagnostic_status(x)
    assert r[1] == 'LONG' and r[0] == 'NEAR LONG' and 'exhaustion' in r[4]
    x['long_score'] = 72; x['exhaustion'] = .8; x['expansion'] = .7
    r = diagnostic_status(x)
    assert r[0] == 'PRE-EXPANSION LONG'
    x = {'long_score':48,'short_score':66,'location':.8,'exhaustion':.7,'flow':.4,'reclaim':.6,'expansion':.5}
    r = diagnostic_status(x)
    assert r[1] == 'SHORT' and r[0] == 'NEAR SHORT'
    print('V2.1 diagnostic smoke tests PASSED')


if __name__ == '__main__':
    _test()

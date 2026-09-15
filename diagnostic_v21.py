"""V2.1 diagnostic layer: explain proximity to a reversal signal without changing entry rules."""

def diagnostic_status(x):
    ls = float(x.get('long_score') or 0)
    ss = float(x.get('short_score') or 0)
    side = 'LONG' if ls >= ss else 'SHORT'
    score = max(ls, ss)
    gap_to_signal = round(max(0.0, 70.0 - score), 1)
    if x.get('direction') in ('LONG', 'SHORT'):
        loc = float(x.get('location') or 0); exh = float(x.get('exhaustion') or 0)
        flow = float(x.get('flow') or 0); rec = float(x.get('reclaim') or 0); exp = float(x.get('expansion') or 0)
        missing = []
        if loc < 0.60: missing.append(f'location {loc:.2f}<0.60')
        if x.get('direction') == 'LONG' and flow < 0.55: missing.append(f'flow {flow:.2f}<0.55')
        if x.get('direction') == 'SHORT' and flow > 0.45: missing.append(f'flow {flow:.2f}>0.45')
        if rec < 0.25: missing.append(f'reclaim/rejection {rec:.2f}<0.25')
        if exh < 0.50: missing.append(f'exhaustion {exh:.2f}<0.50')
        if exp < 0.40: missing.append(f'expansion {exp:.2f}<0.40')
        blocker = '; '.join(missing[:3]) if missing else 'none'
    else:
        blocker = 'side-specific components unavailable until core exposes both LONG and SHORT component sets'
    if score >= 70 and x.get('direction') in ('LONG', 'SHORT'):
        status = f'PRE-EXPANSION {x["direction"]}'
    elif score >= 60:
        status = f'NEAR {side}'
    elif score >= 50:
        status = f'MONITOR {side}'
    else:
        status = 'NO EDGE'
    return {'status': status, 'bias': side, 'long_score': round(ls,1), 'short_score': round(ss,1), 'score_gap_to_70': gap_to_signal, 'blocker': blocker}

def _test():
    x={'long_score':65,'short_score':61,'direction':'NONE'}; r=diagnostic_status(x)
    assert r['bias']=='LONG' and r['status']=='NEAR LONG' and r['score_gap_to_70']==5.0
    x={'long_score':72,'short_score':61,'direction':'LONG','location':.8,'exhaustion':.8,'flow':.7,'reclaim':.5,'expansion':.7}; r=diagnostic_status(x)
    assert r['status']=='PRE-EXPANSION LONG' and r['blocker']=='none'
    x={'long_score':48,'short_score':66,'direction':'NONE'}; r=diagnostic_status(x)
    assert r['bias']=='SHORT' and r['status']=='NEAR SHORT' and 'unavailable' in r['blocker']
    print('V2.1 diagnostic smoke tests PASSED')

if __name__=='__main__': _test()

"""Event-level statistics for the V2.2 Extreme Reversal forward test."""

HORIZONS=(1,4,12,24)
OUTCOME_VALUES=('EXPANSION','FAIL','AMBIGUOUS')


def summarize(rows):
    """Return raw/horizon/event statistics without double-counting events.

    A resolved event is an independent PRIMARY event with at least one
    resolved horizon. The event outcome is the earliest resolved horizon.
    Horizon counts remain separate because one event may resolve at multiple
    horizons (for example H12 and H24 can both be EXPANSION).
    """
    primary=[r for r in rows if r.get('event_role')=='PRIMARY']
    events={r.get('event_id') for r in primary if r.get('event_id')}
    event_outcomes={}
    horizon_counts={f'h{h}':{o:0 for o in OUTCOME_VALUES} for h in HORIZONS}

    for row in primary:
        event_id=row.get('event_id')
        if not event_id:
            continue
        for h in HORIZONS:
            value=(row.get(f'h{h}') or '').strip().upper()
            if value in OUTCOME_VALUES:
                horizon_counts[f'h{h}'][value]+=1
                event_outcomes.setdefault(event_id,[]).append((h,value))

    resolved=0
    event_counts={o:0 for o in OUTCOME_VALUES}
    for event_id, outcomes in event_outcomes.items():
        if not outcomes:
            continue
        resolved+=1
        earliest=min(outcomes,key=lambda x:x[0])
        event_counts[earliest[1]]+=1

    return {
        'raw_signals':len(rows),
        'independent_events':len(events),
        'resolved_events':resolved,
        'unresolved_events':len(events)-resolved,
        'event_outcomes':event_counts,
        'horizon_outcomes':horizon_counts,
    }


def format_summary(rows):
    s=summarize(rows)
    e=s['event_outcomes']
    h=s['horizon_outcomes']
    horizon_text=' '.join(
        f"H{hours}: E={h[f'h{hours}']['EXPANSION']},F={h[f'h{hours}']['FAIL']},A={h[f'h{hours}']['AMBIGUOUS']}"
        for hours in HORIZONS
    )
    return (
        f"Extreme forward-test: {s['raw_signals']} raw signals / "
        f"{s['independent_events']} independent events / "
        f"{s['resolved_events']} resolved events / "
        f"{s['unresolved_events']} unresolved events | "
        f"event outcome: EXPANSION={e['EXPANSION']}, FAIL={e['FAIL']}, AMBIGUOUS={e['AMBIGUOUS']} | "
        f"horizon outcomes: {horizon_text}"
    )

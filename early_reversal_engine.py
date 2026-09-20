"""Early-reversal detection engine for the scalping brain.

This layer is deliberately separate from V2.2. It looks for a completed
down/up move, price exhaustion near the edge of the recent range, a compact
base, and a closed-candle reversal trigger before allowing an entry.

It is a signal filter, not a profit guarantee. All inputs are closed candles.
"""

from scalping_intelligence import _close, _high, _low, atr, _location_score, _reversal_score


def _closes(rows):
    return [_close(r) for r in rows]


def _impulse_exhaustion_score(rows, direction, lookback=32, impulse_bars=12):
    if len(rows) < max(lookback, impulse_bars + 14):
        return 0.0
    window = rows[-lookback:]
    current = _close(window[-1])
    reference = _close(window[-1 - impulse_bars])
    a = atr(window, 14)
    if not a or a <= 0:
        return 0.0

    if direction == "LONG":
        move = reference - current
    else:
        move = current - reference

    if move <= 0:
        return 0.0
    ratio = move / a
    if ratio >= 2.0:
        return 1.0
    if ratio >= 1.0:
        return 0.5
    return 0.0


def _base_score(rows, direction):
    """Detect compression near the extreme after the directional impulse."""
    if len(rows) < 10:
        return 0.0
    a = atr(rows[-32:], 14)
    if not a or a <= 0:
        return 0.0

    base = rows[-5:]
    base_high = max(_high(r) for r in base)
    base_low = min(_low(r) for r in base)
    base_range = base_high - base_low
    closes = _closes(base)
    close_range = max(closes) - min(closes)

    # A base should be materially tighter than the recent 15m volatility.
    if base_range > 1.75 * a or close_range > 1.25 * a:
        return 0.0

    # Keep the base on the intended side of the recent range.
    location = _location_score(rows, direction)
    if location < 1.0:
        return 0.0
    return 1.0


def _structure_shift_score(rows_5m, direction):
    if len(rows_5m) < 8:
        return 0.0
    prior = rows_5m[-5:-1]
    last = rows_5m[-1]
    if direction == "LONG":
        return 1.0 if _close(last) > max(_high(r) for r in prior) else 0.0
    return 1.0 if _close(last) < min(_low(r) for r in prior) else 0.0


def _reversal_trigger_score(rows_5m, direction):
    reversal = _reversal_score(rows_5m, direction)
    structure = _structure_shift_score(rows_5m, direction)
    if reversal >= 1.0:
        return 1.0
    if reversal >= 0.5 and structure >= 1.0:
        return 1.0
    if reversal >= 0.5:
        return 0.75
    return 0.0


def evaluate_setup(rows_15m, rows_5m, direction):
    """Return objective component scores for an early reversal candidate."""
    if direction not in {"LONG", "SHORT"}:
        return {
            "eligible": False, "score": 0.0, "location_15m": 0.0,
            "exhaustion_15m": 0.0, "base_15m": 0.0,
            "structure_shift_5m": 0.0, "reversal_trigger_5m": 0.0,
            "reason": "invalid direction",
        }
    if len(rows_15m) < 40 or len(rows_5m) < 20:
        return {
            "eligible": False, "score": 0.0, "location_15m": 0.0,
            "exhaustion_15m": 0.0, "base_15m": 0.0,
            "structure_shift_5m": 0.0, "reversal_trigger_5m": 0.0,
            "reason": "insufficient reversal history",
        }

    location = _location_score(rows_15m, direction)
    exhaustion = _impulse_exhaustion_score(rows_15m, direction)
    base = _base_score(rows_15m, direction)
    structure = _structure_shift_score(rows_5m, direction)
    trigger = _reversal_trigger_score(rows_5m, direction)

    # No bottom/top guessing: the setup needs the extreme location, evidence
    # of a completed move, and a closed-candle trigger.
    eligible = (
        location >= 1.0 and
        exhaustion >= 0.5 and
        trigger >= 0.75 and
        (base >= 1.0 or structure >= 1.0)
    )

    score = (
        0.25 * location +
        0.25 * exhaustion +
        0.20 * base +
        0.15 * structure +
        0.15 * trigger
    )
    if not eligible:
        if location < 1.0:
            reason = "reversal zone is not at the preferred range extreme"
        elif exhaustion < 0.5:
            reason = "no sufficient 15m directional exhaustion"
        elif trigger < 0.75:
            reason = "no confirmed 5m reversal trigger"
        else:
            reason = "no 15m base or 5m structure shift"
    else:
        reason = "early reversal setup confirmed"

    return {
        "eligible": eligible,
        "score": round(score, 4),
        "location_15m": location,
        "exhaustion_15m": exhaustion,
        "base_15m": base,
        "structure_shift_5m": structure,
        "reversal_trigger_5m": trigger,
        "reason": reason,
    }


def infer_direction(rows_15m, rows_5m):
    """Infer LONG/SHORT from reversal structure without trend-following bias."""
    candidates = {
        direction: evaluate_setup(rows_15m, rows_5m, direction)
        for direction in ("LONG", "SHORT")
    }
    eligible = [(d, v) for d, v in candidates.items() if v["eligible"]]
    if not eligible:
        return None
    eligible.sort(key=lambda item: item[1]["score"], reverse=True)
    if len(eligible) == 2 and eligible[0][1]["score"] - eligible[1][1]["score"] < 0.20:
        return None
    return eligible[0][0]

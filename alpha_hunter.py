"""Alpha Hunter opportunity-discovery lane.

This lane is intentionally broader than the reversal/action engines. It detects
15m opportunity regimes (volatility + location + 5m participation) and builds
a reachable 100-candle execution plan. It does not modify scanner_v2.py.
"""
from math import isfinite

from scalping_intelligence import _close, _high, _low, _volume, atr, _entry_location_100, _opposing_structure_target, _tp_margin_target
from margin_risk_model import DEFAULT_LEVERAGE, DEFAULT_MARGIN_USDT, MAX_MARGIN_LOSS_PCT


ALPHA_HUNTER_VERSION = "alpha-hunter-v2"


def _f(v, default=0.0):
    try:
        x = float(v)
        return x if isfinite(x) else default
    except (TypeError, ValueError):
        return default


def _range_position(rows, direction, lookback=32):
    if len(rows) < lookback:
        return 0.5
    window = rows[-lookback:]
    high = max(_high(r) for r in window)
    low = min(_low(r) for r in window)
    span = high - low
    if span <= 0:
        return 0.5
    pos = (_close(rows[-1]) - low) / span
    return pos if direction == "LONG" else 1.0 - pos


def _volume_ratio(rows, period=20):
    if len(rows) < period + 1:
        return 0.0
    base = sum(_volume(r) for r in rows[-period-1:-1]) / period
    return _volume(rows[-1]) / base if base > 0 else 0.0


def _impulse(rows, direction, bars=3):
    if len(rows) < bars + 1:
        return 0.0
    start = _close(rows[-bars-1])
    end = _close(rows[-1])
    if start <= 0:
        return 0.0
    move = (end - start) / start
    return move if direction == "LONG" else -move


def _sweep(rows, direction):
    if len(rows) < 8:
        return 0.0
    previous = rows[-7:-1]
    last = rows[-1]
    prior_low = min(_low(r) for r in previous)
    prior_high = max(_high(r) for r in previous)
    if direction == "LONG":
        return 1.0 if _low(last) < prior_low and _close(last) > prior_low else 0.0
    return 1.0 if _high(last) > prior_high and _close(last) < prior_high else 0.0


def _direction_candidates(rows_15m, rows_5m):
    out = []
    for direction in ("LONG", "SHORT"):
        location = _range_position(rows_15m, direction)
        impulse = _impulse(rows_5m, direction)
        volume = _volume_ratio(rows_5m)
        sweep = _sweep(rows_5m, direction)
        # Broad discovery: location is primary, then require actual participation
        # (volume, impulse, or liquidity sweep). This is deliberately less strict
        # than the reversal lane.
        participation = max(
            sweep,
            min(1.0, volume / 1.5),
            min(1.0, max(0.0, impulse) / 0.006),
        )
        if location >= 0.55 and participation >= 0.45:
            out.append((direction, location, impulse, volume, sweep, participation))
    return out


def build_plan(rows_15m, rows_5m):
    if len(rows_15m) < 160 or len(rows_5m) < 60:
        return {"status": "DATA-LIMITED", "reason": "insufficient MTF candles"}

    micro_atr = atr(rows_5m, 14)
    price = _close(rows_5m[-1])
    if not micro_atr or price <= 0:
        return {"status": "DATA-LIMITED", "reason": "price/5m ATR unavailable"}

    atr_pct = micro_atr / price * 100.0
    # Exclude dead/choked markets and pathological spikes. This is a regime gate,
    # not a directional score.
    if atr_pct < 0.12 or atr_pct > 4.0:
        return {"status": "WAIT", "reason": "5m volatility regime outside alpha envelope", "atr_pct": atr_pct}

    candidates = _direction_candidates(rows_15m, rows_5m)
    if not candidates:
        return {"status": "WAIT", "reason": "no alpha opportunity regime", "atr_pct": atr_pct}

    best = None
    for direction, location, impulse, volume, sweep, participation in candidates:
        loc = _entry_location_100(rows_5m, direction, micro_atr)
        if not loc:
            continue
        entry = loc["entry"]
        stop = loc["stop"]
        risk = entry - stop if direction == "LONG" else stop - entry
        if risk <= 0:
            continue
        distance_atr = abs(price - entry) / micro_atr
        risk_pct = risk / price * 100.0
        if distance_atr > 0.90 or risk_pct < 0.10:
            continue

        structural = _opposing_structure_target(rows_15m, direction, entry, risk, 1.0, 20.0)
        # Alpha Hunter uses the same margin model as the execution lane.
        flow_features = {
            "liquidity_sweep_score": sweep,
            "volume_score": min(1.0, max(0.0, volume / 1.5)),
        }
        tp_plan = _tp_margin_target(direction, entry, structural, flow_features, 45.0 + 20.0 * location + 15.0 * participation)
        if tp_plan is None:
            continue
        margin_plan, flow_conviction, structural_margin_pct = tp_plan
        if margin_plan["stop_margin_pct"] > MAX_MARGIN_LOSS_PCT:
            continue
        target = margin_plan["target"]
        reward = (target - entry) / risk if direction == "LONG" else (entry - target) / risk
        score = 45.0 + 20.0 * location + 15.0 * participation
        if sweep:
            score += 10.0
        if volume >= 1.5:
            score += 5.0
        if impulse >= 0.003:
            score += 5.0
        score = min(100.0, score)

        candidate = {
            "status": "ALPHA LONG" if direction == "LONG" else "ALPHA SHORT",
            "direction": direction,
            "confidence": round(score, 1),
            "entry": entry,
            "entry_low": entry - micro_atr * 0.15 if direction == "SHORT" else entry,
            "entry_high": entry + micro_atr * 0.15 if direction == "LONG" else entry,
            "stop": stop,
            "target": target,
            "margin_usdt": margin_plan["margin_usdt"],
            "leverage": margin_plan["leverage"],
            "notional_usdt": margin_plan["notional_usdt"],
            "stop_margin_pct": margin_plan["stop_margin_pct"],
            "tp_margin_pct": margin_plan["tp_margin_pct"],
            "max_loss_usdt": margin_plan["max_loss_usdt"],
            "target_pnl_usdt": margin_plan["target_pnl_usdt"],
            "target_price_move_pct": margin_plan["target_price_move_pct"],
            "flow_conviction": flow_conviction,
            "structural_target_margin_pct": structural_margin_pct,
            "risk_pct": risk_pct,
            "reward_r": reward,
            "atr_pct": atr_pct,
            "entry_distance_atr": distance_atr,
            "location_15m": location,
            "participation": participation,
            "volume_ratio_5m": volume,
            "impulse_5m": impulse,
            "liquidity_sweep_5m": sweep,
            "timeframes": "15m/5m",
            "reason": (
                f"alpha regime: location={location:.2f}, participation={participation:.2f}, "
                f"vol={volume:.2f}x, impulse={impulse:.3%}, ATR={atr_pct:.3f}%"
            ),
        }
        if best is None or candidate["confidence"] > best["confidence"]:
            best = candidate

    return best or {"status": "WAIT", "reason": "alpha execution geometry unavailable", "atr_pct": atr_pct}
